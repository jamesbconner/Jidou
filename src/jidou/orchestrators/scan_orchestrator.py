"""Orchestrator for scanning configured SFTP paths and creating DownloadedFile records.

Scans shallowly: only the immediate children of each configured remote path
are listed on every run. A full recursive walk only ever happens once per
top-level directory, the first time it's seen — Jidou's SFTP sources
(seedbox/torrent-client download folders) are wide, flat, and single-use,
so a directory known once is treated as permanently immutable and is never
walked again. See ``ScannedDirectory``.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.scanned_directory import ScannedDirectory
from jidou.orchestrators._bulk_existence import chunked_existing_paths
from jidou.services.sftp_service import RecursiveListResult, RemoteFile, SFTPService

logger = logging.getLogger(__name__)

# A directory's deep-walk result, or the exception raised while walking it.
_WalkOutcome = tuple[str, "RecursiveListResult | BaseException"]


@dataclass
class ScanResult:
    """Result of a remote SFTP scan operation."""

    paths_scanned: int
    files_found: int
    files_created: int
    files_skipped: int
    dirs_discovered: int = 0


class ScanOrchestrator:
    """Scan configured SFTP remote paths and create DownloadedFile records.

    Files are created with ``show_id=NULL`` and status ``DISCOVERED``; the
    parse phase later matches them to shows.  Duplicate detection uses
    ``remote_path`` alone (unique on the SFTP server regardless of show).

    Only the immediate children of each configured remote path are listed on
    every run. A directory not yet seen is deep-walked once (concurrently,
    bounded by ``sftp.max_workers``) and, if the walk completes without any
    I/O failures or in-flight-upload skips, marked permanently known via a
    ``ScannedDirectory`` row so it is never walked again. A directory already
    known is skipped entirely — no SFTP round trip into it at all.

    Args:
        session: Active async SQLAlchemy session.
        sftp: Configured SFTPService instance.
        remote_paths: List of remote directory paths to scan.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        remote_paths: list[str],
    ) -> None:
        self.session = session
        self.sftp = sftp
        self.remote_paths = remote_paths

    async def run(
        self,
        dry_run: bool = False,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> ScanResult:
        """Scan every remote path and create DISCOVERED records for new files.

        Already-tracked files (any status) are skipped to preserve their
        current pipeline state.

        Args:
            dry_run: Log what would be created without writing to the DB.
            on_progress: Optional async callback(current, total, message).

        Returns:
            ScanResult with counts. ``files_found``/``files_skipped`` reflect
            only files discovered this run (top-level files plus any newly
            deep-walked directories) — a known, skipped directory contributes
            nothing to these counts, unlike a full rescan.
        """
        total = len(self.remote_paths)
        files_found = 0
        files_created = 0
        files_skipped = 0
        dirs_discovered = 0

        for idx, remote_path in enumerate(self.remote_paths, 1):
            if on_progress:
                await on_progress(idx, total, f"Scanning {remote_path}")

            try:
                children = await self.sftp.list_remote_children(remote_path)
            except Exception:
                logger.exception("Failed to list remote path %s; skipping", remote_path)
                continue

            top_level_files = [c for c in children if not c.is_dir]
            top_level_dirs = [c for c in children if c.is_dir]
            files_found += len(top_level_files)

            existing_file_paths = await chunked_existing_paths(
                self.session, DownloadedFile.remote_path, [f.path for f in top_level_files]
            )
            for rf in top_level_files:
                if rf.path in existing_file_paths:
                    files_skipped += 1
                    continue
                if await self._create_discovered_file(rf, dry_run):
                    files_created += 1
                else:
                    files_skipped += 1

            existing_dir_paths = await chunked_existing_paths(
                self.session, ScannedDirectory.remote_path, [d.path for d in top_level_dirs]
            )
            new_dirs = [d for d in top_level_dirs if d.path not in existing_dir_paths]
            dirs_discovered += len(new_dirs)

            if not new_dirs:
                continue

            for dir_path, outcome in await self._deep_walk_new_dirs(new_dirs):
                if isinstance(outcome, BaseException):
                    logger.warning("Failed to deep-walk new directory %s: %s", dir_path, outcome)
                    continue

                files_found += len(outcome.files)
                dir_existing = await chunked_existing_paths(
                    self.session, DownloadedFile.remote_path, [f.path for f in outcome.files]
                )
                for rf in outcome.files:
                    if rf.path in dir_existing:
                        files_skipped += 1
                        continue
                    if await self._create_discovered_file(rf, dry_run):
                        files_created += 1
                    else:
                        files_skipped += 1

                if outcome.fully_walked:
                    if dry_run:
                        logger.info("[DRY RUN] Would mark directory as known: %s", dir_path)
                    else:
                        await self._mark_scanned_directory(dir_path)
                else:
                    logger.info(
                        "Directory %s not fully walked (io_failures=%d, "
                        "recently_modified_skipped=%d) — will retry on next scan",
                        dir_path,
                        outcome.io_failures,
                        outcome.recently_modified_skipped,
                    )

        if not dry_run:
            await self.session.commit()

        logger.info(
            "Scan complete: %d paths, %d found, %d created, %d skipped, "
            "%d new directories discovered (dry_run=%s)",
            total,
            files_found,
            files_created,
            files_skipped,
            dirs_discovered,
            dry_run,
        )
        return ScanResult(
            paths_scanned=total,
            files_found=files_found,
            files_created=files_created,
            files_skipped=files_skipped,
            dirs_discovered=dirs_discovered,
        )

    async def _deep_walk_new_dirs(self, dirs: list[RemoteFile]) -> list[_WalkOutcome]:
        """Deep-walk each newly-discovered directory concurrently (SFTP I/O only).

        Bounded by ``sftp.max_workers``. Exceptions are captured per-directory
        rather than propagated, so one directory's failure doesn't cancel the
        others. Results are collected and returned for the caller to process
        sequentially against the DB session afterward — ``AsyncSession`` is
        not safe for concurrent use, so no session access happens here.

        Args:
            dirs: Newly-discovered top-level directory entries to walk.

        Returns:
            List of ``(remote_path, RecursiveListResult | exception)`` pairs,
            one per input directory.
        """
        semaphore = asyncio.Semaphore(max(1, self.sftp.max_workers))

        async def _walk_one(d: RemoteFile) -> _WalkOutcome:
            async with semaphore:
                try:
                    result = await self.sftp.list_remote_files_recursive(d.path)
                except Exception as exc:
                    return d.path, exc
                return d.path, result

        return await asyncio.gather(*[_walk_one(d) for d in dirs])

    async def _create_discovered_file(self, rf: RemoteFile, dry_run: bool) -> bool:
        """Create a DISCOVERED DownloadedFile row for *rf*.

        Args:
            rf: The remote file to record.
            dry_run: When True, log what would be created without writing.

        Returns:
            True if created (or would be, under dry_run); False if a
            concurrent scan already won the race to create this remote_path.
        """
        if dry_run:
            logger.info("[DRY RUN] Would create DownloadedFile for %s", rf.path)
            return True
        try:
            async with self.session.begin_nested():
                self.session.add(
                    DownloadedFile(
                        show_id=None,
                        original_filename=rf.name,
                        remote_path=rf.path,
                        file_size=rf.size,
                        status=FileStatus.DISCOVERED,
                    )
                )
            return True
        except IntegrityError as exc:
            orig = getattr(exc, "orig", None)
            pgcode = getattr(orig, "pgcode", None)
            if pgcode is not None and pgcode != "23505":
                raise
            logger.debug("Skipping duplicate file (race): remote_path=%s", rf.path)
            return False

    async def _mark_scanned_directory(self, remote_path: str) -> None:
        """Insert a ScannedDirectory row marking *remote_path* as permanently known.

        Args:
            remote_path: Full remote path of the directory to mark.
        """
        try:
            async with self.session.begin_nested():
                self.session.add(ScannedDirectory(remote_path=remote_path))
        except IntegrityError as exc:
            orig = getattr(exc, "orig", None)
            pgcode = getattr(orig, "pgcode", None)
            if pgcode is not None and pgcode != "23505":
                raise
            logger.debug("ScannedDirectory already exists (race): remote_path=%s", remote_path)
