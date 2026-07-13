"""Orchestrator for scanning configured SFTP paths and creating DownloadedFile records.

Scans shallowly: only the immediate children of each configured remote path
are listed on every run. A full recursive walk only ever happens once per
top-level directory, the first time it's seen — Jidou's SFTP sources
(seedbox/torrent-client download folders) are wide, flat, and single-use,
so a directory known once is treated as permanently immutable and is never
walked again. See ``ScannedDirectory``.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.scanned_directory import ScannedDirectory
from jidou.orchestrators._bulk_existence import chunked_existing_paths, insert_or_skip_duplicate
from jidou.services.sftp_service import RecursiveListResult, RemoteFile, SFTPService

logger = logging.getLogger(__name__)


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
    every run. A directory not yet seen is deep-walked once (concurrently
    across all configured remote paths combined, bounded by
    ``sftp.max_workers``) and, if the walk completes without any I/O
    failures, in-flight-upload skips, or deferred-too-fresh subdirectories,
    marked permanently known via a ``ScannedDirectory`` row so it is never
    walked again. A directory already known is skipped entirely — no SFTP
    round trip into it at all.

    Existence checks (both for top-level files and top-level directories, and
    for files found inside newly-walked directories) are batched once across
    *all* configured remote paths rather than once per path, to keep the
    round-trip count constant regardless of how many remote paths are
    configured.

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
            on_progress: Optional async callback(current, total, message),
                called once per configured remote path during the initial
                shallow-listing phase.

        Returns:
            ScanResult with counts. ``files_found``/``files_skipped`` reflect
            only files discovered this run (top-level files plus any newly
            deep-walked directories) — a known, skipped directory contributes
            nothing to these counts, unlike a full rescan. ``dirs_discovered``
            counts only directories actually marked known this run, not
            merely seen as new.
        """
        total = len(self.remote_paths)
        all_top_level_files: list[RemoteFile] = []
        all_top_level_dirs: list[RemoteFile] = []

        # Phase 1: shallow-list every configured remote path.
        for idx, remote_path in enumerate(self.remote_paths, 1):
            if on_progress:
                await on_progress(idx, total, f"Scanning {remote_path}")
            try:
                children = await self.sftp.list_remote_children(remote_path)
            except Exception:
                logger.exception("Failed to list remote path %s; skipping", remote_path)
                continue
            all_top_level_files.extend(c for c in children if not c.is_dir)
            all_top_level_dirs.extend(c for c in children if c.is_dir)

        files_found = len(all_top_level_files)
        files_created = 0
        files_skipped = 0

        # Phase 2: one combined existence check for top-level files across ALL paths.
        existing_file_paths = await chunked_existing_paths(
            self.session, DownloadedFile.remote_path, [f.path for f in all_top_level_files]
        )
        for rf in all_top_level_files:
            if rf.path in existing_file_paths:
                files_skipped += 1
                continue
            if await self._create_discovered_file(rf, dry_run):
                files_created += 1
            else:
                files_skipped += 1

        # Phase 3: one combined existence check for top-level directories across ALL paths.
        existing_dir_paths = await chunked_existing_paths(
            self.session, ScannedDirectory.remote_path, [d.path for d in all_top_level_dirs]
        )
        new_dirs = [d for d in all_top_level_dirs if d.path not in existing_dir_paths]

        dirs_discovered = 0
        if new_dirs:
            # Phase 4: deep-walk ALL new directories concurrently, across every
            # configured remote path together (SFTP I/O only — no session access).
            outcomes = await self.sftp.list_remote_files_recursive_batch([d.path for d in new_dirs])

            successful: list[tuple[str, RecursiveListResult]] = []
            all_new_files: list[RemoteFile] = []
            for dir_path, outcome in outcomes:
                if isinstance(outcome, BaseException):
                    logger.warning("Failed to deep-walk new directory %s: %s", dir_path, outcome)
                    continue
                successful.append((dir_path, outcome))
                all_new_files.extend(outcome.files)

            files_found += len(all_new_files)

            # Phase 5: one combined existence check for files across ALL newly-walked directories.
            new_dir_existing = await chunked_existing_paths(
                self.session, DownloadedFile.remote_path, [f.path for f in all_new_files]
            )
            for rf in all_new_files:
                if rf.path in new_dir_existing:
                    files_skipped += 1
                elif await self._create_discovered_file(rf, dry_run):
                    files_created += 1
                else:
                    files_skipped += 1

            for dir_path, outcome in successful:
                if outcome.fully_walked:
                    if dry_run:
                        logger.info("[DRY RUN] Would mark directory as known: %s", dir_path)
                    else:
                        await self._mark_scanned_directory(dir_path)
                    dirs_discovered += 1
                else:
                    logger.info(
                        "Directory %s not fully walked (io_failures=%d, "
                        "recently_modified_skipped=%d, directories_deferred=%d) "
                        "— will retry on next scan",
                        dir_path,
                        outcome.io_failures,
                        outcome.recently_modified_skipped,
                        outcome.directories_deferred,
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
        row = DownloadedFile.new_from_remote(
            name=rf.name, remote_path=rf.path, size=rf.size, status=FileStatus.DISCOVERED
        )
        return await insert_or_skip_duplicate(self.session, row)

    async def _mark_scanned_directory(self, remote_path: str) -> None:
        """Insert a ScannedDirectory row marking *remote_path* as permanently known.

        Args:
            remote_path: Full remote path of the directory to mark.
        """
        await insert_or_skip_duplicate(self.session, ScannedDirectory(remote_path=remote_path))
