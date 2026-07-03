"""Orchestrator for seeding pre-existing SFTP files as SEEDED records.

Run once before enabling the download schedule when taking over from a legacy
service (e.g. Sync2NAS).  Creates a DownloadedFile record with status SEEDED
for every remote file that is not already tracked, preventing the normal scan →
download pipeline from re-downloading files that already exist on the SFTP server.

The operation is idempotent: re-running skips any remote_path already in the
database regardless of its current status and never mutates existing rows.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)

# Number of remote paths to batch into a single existence-check query.
_EXISTENCE_CHUNK = 1_000


@dataclass
class SeedResult:
    """Result of a baseline seed operation."""

    paths_scanned: int
    paths_failed: int
    files_found: int
    files_seeded: int
    files_skipped: int
    skipped_by_status: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False


class _ExistingRow(NamedTuple):
    remote_path: str
    status: str


class SeedOrchestrator:
    """Seed SEEDED DownloadedFile records for all pre-existing SFTP files.

    Uses the same ``SFTPService.list_remote_files_recursive`` call as
    ``ScanOrchestrator``, so the same ``file_filters`` rules apply (media files
    only; excludes .nfo, .jpg, sample dirs, etc.).

    Args:
        session: Active async SQLAlchemy session.
        sftp: Configured SFTPService instance.
        remote_paths: Remote directory paths to inventory.
        batch_size: Number of new records to insert per commit.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        remote_paths: list[str],
        batch_size: int = 500,
    ) -> None:
        self.session = session
        self.sftp = sftp
        self.remote_paths = remote_paths
        self.batch_size = batch_size

    async def run(
        self,
        dry_run: bool = False,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> SeedResult:
        """Inventory all remote paths and create SEEDED records for untracked files.

        Args:
            dry_run: Log what would be seeded without writing to the database.
            on_progress: Optional async callback(current, total, message) called
                after each batch commit.  Raising ``asyncio.CancelledError``
                inside the callback aborts the run.

        Returns:
            SeedResult with counts and per-status skip breakdown.
        """
        total_paths = len(self.remote_paths)
        paths_failed = 0
        files_found = 0
        files_seeded = 0
        files_skipped = 0
        skipped_by_status: dict[str, int] = {}

        # Collect all remote files across all paths first so we can report
        # accurate totals and do bulk existence checks.
        all_remote: list[tuple[str, str, int]] = []  # (name, path, size)

        for idx, remote_path in enumerate(self.remote_paths, 1):
            if on_progress:
                await on_progress(idx, total_paths, f"Listing {remote_path}")
            try:
                remote_files = await self.sftp.list_remote_files_recursive(remote_path)
            except Exception:
                logger.exception("Failed to list remote path %s; skipping", remote_path)
                paths_failed += 1
                continue

            for rf in remote_files:
                all_remote.append((rf.name, rf.path, rf.size))

        files_found = len(all_remote)

        if files_found == 0:
            logger.info(
                "Seed complete: no files found (paths_failed=%d, dry_run=%s)",
                paths_failed,
                dry_run,
            )
            return SeedResult(
                paths_scanned=total_paths,
                paths_failed=paths_failed,
                files_found=0,
                files_seeded=0,
                files_skipped=0,
                skipped_by_status={},
                dry_run=dry_run,
            )

        # Bulk existence check: chunk paths to avoid oversized IN() clauses.
        all_paths = [path for _, path, _ in all_remote]
        existing: dict[str, str] = {}  # remote_path → status
        for i in range(0, len(all_paths), _EXISTENCE_CHUNK):
            chunk = all_paths[i : i + _EXISTENCE_CHUNK]
            stmt = select(DownloadedFile.remote_path, DownloadedFile.status).where(
                DownloadedFile.remote_path.in_(chunk)
            )
            rows = (await self.session.execute(stmt)).all()
            for row in rows:
                existing[row.remote_path] = str(row.status)

        # Build the list of new records to insert.
        pending: list[tuple[str, str, int]] = []
        for name, path, size in all_remote:
            if path in existing:
                status_str = existing[path]
                files_skipped += 1
                skipped_by_status[status_str] = skipped_by_status.get(status_str, 0) + 1
                logger.debug("Skipping already-tracked file (status=%s): %s", status_str, path)
            else:
                pending.append((name, path, size))

        if dry_run:
            for _name, path, size in pending:
                logger.info("[DRY RUN] Would seed %s (%d bytes)", path, size)
            files_seeded = len(pending)
            logger.info(
                "Seed complete: %d/%d files would be seeded, %d skipped (dry_run=True)",
                files_seeded,
                files_found,
                files_skipped,
            )
            return SeedResult(
                paths_scanned=total_paths,
                paths_failed=paths_failed,
                files_found=files_found,
                files_seeded=files_seeded,
                files_skipped=files_skipped,
                skipped_by_status=skipped_by_status,
                dry_run=True,
            )

        # Insert in batches for bounded transactions and crash resumability.
        total_pending = len(pending)
        for batch_start in range(0, total_pending, self.batch_size):
            batch = pending[batch_start : batch_start + self.batch_size]
            for name, path, size in batch:
                try:
                    async with self.session.begin_nested():
                        self.session.add(
                            DownloadedFile(
                                original_filename=name,
                                remote_path=path,
                                file_size=size,
                                status=FileStatus.SEEDED,
                            )
                        )
                    files_seeded += 1
                except IntegrityError as exc:
                    orig = getattr(exc, "orig", None)
                    pgcode = getattr(orig, "pgcode", None)
                    if pgcode is not None and pgcode != "23505":
                        raise
                    # Concurrent scan won the race — counts as skipped.
                    logger.debug("Skipping duplicate (race): %s", path)
                    files_skipped += 1
                    skipped_by_status["discovered"] = skipped_by_status.get("discovered", 0) + 1

            await self.session.commit()

            progress_done = min(batch_start + self.batch_size, total_pending)
            if on_progress:
                await on_progress(
                    progress_done,
                    total_pending,
                    f"Seeded {progress_done}/{total_pending} files",
                )

        logger.info(
            "Seed complete: %d paths scanned (%d failed), %d/%d files seeded, "
            "%d skipped (dry_run=%s)",
            total_paths,
            paths_failed,
            files_seeded,
            files_found,
            files_skipped,
            dry_run,
        )
        return SeedResult(
            paths_scanned=total_paths,
            paths_failed=paths_failed,
            files_found=files_found,
            files_seeded=files_seeded,
            files_skipped=files_skipped,
            skipped_by_status=skipped_by_status,
            dry_run=dry_run,
        )
