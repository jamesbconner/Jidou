"""Orchestrator for seeding pre-existing SFTP files as SEEDED records.

Run once before enabling the download schedule when taking over from a legacy
service (e.g. Sync2NAS).  Creates a DownloadedFile record with status SEEDED
for every remote file that is not already tracked, preventing the normal scan →
download pipeline from re-downloading files that already exist on the SFTP server.

Also backfills ScannedDirectory rows for every top-level directory under each
configured remote path, so ScanOrchestrator's shallow-scan-plus-lazy-deep-walk
design doesn't treat an already-seeded library as entirely new on its first
regular scan.

Mirrors ScanOrchestrator's shape: shallow-list each configured remote path,
then deep-walk each top-level directory found there *individually* (batched
concurrently across every remote path at once via
``SFTPService.list_remote_files_recursive_batch``) rather than doing one
giant recursive walk of each whole configured root. This matters for two
reasons beyond matching ScanOrchestrator's algorithm:

- Per-directory (not per-configured-root) ``fully_walked`` granularity — one
  in-flight file in a single show no longer blocks marking every other,
  unrelated, fully-settled show under the same root as known.
- No separate, later, non-atomic shallow listing call to discover directory
  names for marking (the old design's TOCTOU window, where a directory
  appearing between the recursive walk and a follow-up shallow listing could
  be marked known without its files ever having been walked) — the shallow
  listing IS the first call, used consistently for both file collection and
  directory discovery.

Directory-marking (the ScannedDirectory inserts) happens strictly *after* all
DownloadedFile rows have been committed, never before, so a crash mid-run
can at worst cause redundant re-discovery on a later run — never permanent
data loss.

The operation is idempotent: re-running skips any remote_path already in the
database regardless of its current status and never mutates existing rows.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.scanned_directory import ScannedDirectory
from jidou.orchestrators._bulk_existence import (
    EXISTENCE_CHUNK,
    chunked_existing_paths,
    insert_or_skip_duplicate,
)
from jidou.services.sftp_service import RemoteFile, SFTPService

logger = logging.getLogger(__name__)


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


class SeedOrchestrator:
    """Seed SEEDED DownloadedFile records for all pre-existing SFTP files.

    Uses the same shallow-list-then-deep-walk pattern as ``ScanOrchestrator``,
    so the same ``file_filters`` rules apply (media files only; excludes
    .nfo, .jpg, sample dirs, etc.) and the same directory-completeness rules
    apply (a directory is only marked known once its own walk has no I/O
    failures, in-flight-upload skips, or deferred-too-fresh subdirectories).

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
            dry_run: Log what would be seeded/marked without writing to the database.
            on_progress: Optional async callback(current, total, message) called
                after each file-insert batch commit.  Raising
                ``asyncio.CancelledError`` inside the callback aborts the run.

        Returns:
            SeedResult with counts and per-status skip breakdown.
        """
        total_paths = len(self.remote_paths)
        paths_failed = 0
        all_remote: list[tuple[str, str, int]] = []  # (name, path, size)
        all_top_level_dirs: list[RemoteFile] = []

        # Phase 1: shallow-list every configured remote path, collecting
        # top-level files directly and top-level directories to deep-walk.
        for idx, remote_path in enumerate(self.remote_paths, 1):
            logger.info("Listing remote path %d/%d: %s", idx, total_paths, remote_path)
            try:
                children = await self.sftp.list_remote_children(remote_path)
            except Exception:
                logger.exception("Failed to list remote path %s; skipping", remote_path)
                paths_failed += 1
                continue

            for f in children:
                if not f.is_dir:
                    all_remote.append((f.name, f.path, f.size))
            all_top_level_dirs.extend(d for d in children if d.is_dir)

        # Phase 2: deep-walk every top-level directory found across ALL remote
        # paths, concurrently in one batch (bounded by sftp.max_workers).
        eligible_dirs: set[str] = set()
        if all_top_level_dirs:
            outcomes = await self.sftp.list_remote_files_recursive_batch(
                [d.path for d in all_top_level_dirs]
            )
            for dir_path, outcome in outcomes:
                if isinstance(outcome, BaseException):
                    logger.warning("Failed to deep-walk directory %s: %s", dir_path, outcome)
                    continue
                for rf in outcome.files:
                    all_remote.append((rf.name, rf.path, rf.size))
                if outcome.fully_walked:
                    eligible_dirs.add(dir_path)
                else:
                    logger.info(
                        "Directory %s not fully walked (io_failures=%d, "
                        "recently_modified_skipped=%d, directories_deferred=%d) "
                        "— will retry on next seed run",
                        dir_path,
                        outcome.io_failures,
                        outcome.recently_modified_skipped,
                        outcome.directories_deferred,
                    )

        files_found = len(all_remote)
        files_seeded = 0
        files_skipped = 0
        skipped_by_status: dict[str, int] = {}

        if files_found > 0:
            # Bulk existence check: chunk paths to avoid oversized IN() clauses.
            # Needs the status per path (for skipped_by_status), not just a
            # bare existence set, so this stays a direct query rather than
            # routing through chunked_existing_paths (which only returns a
            # set[str]) — but reuses its chunk-size constant.
            all_paths = [path for _, path, _ in all_remote]
            existing: dict[str, str] = {}  # remote_path → status
            for i in range(0, len(all_paths), EXISTENCE_CHUNK):
                chunk = all_paths[i : i + EXISTENCE_CHUNK]
                stmt = select(DownloadedFile.remote_path, DownloadedFile.status).where(
                    DownloadedFile.remote_path.in_(chunk)
                )
                rows = (await self.session.execute(stmt)).all()
                for row in rows:
                    existing[row.remote_path] = str(row.status)

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
            else:
                # Insert in batches for bounded transactions and crash
                # resumability. Directory-marking (below) only happens after
                # this loop fully completes, so a crash here never leaves a
                # directory marked known with unseeded files.
                total_pending = len(pending)
                for batch_start in range(0, total_pending, self.batch_size):
                    batch = pending[batch_start : batch_start + self.batch_size]
                    for name, path, size in batch:
                        new_file = DownloadedFile.new_from_remote(
                            name=name, remote_path=path, size=size, status=FileStatus.SEEDED
                        )
                        if await insert_or_skip_duplicate(self.session, new_file):
                            files_seeded += 1
                        else:
                            # Concurrent scan won the race — counts as skipped.
                            files_skipped += 1
                            skipped_by_status["discovered"] = (
                                skipped_by_status.get("discovered", 0) + 1
                            )

                    await self.session.commit()

                    progress_done = min(batch_start + self.batch_size, total_pending)
                    if on_progress:
                        await on_progress(
                            progress_done,
                            total_pending,
                            f"Seeded {progress_done}/{total_pending} files",
                        )

        # Directory marking always happens last, strictly after every file
        # batch above has been committed (or, if files_found == 0, there was
        # nothing to seed first) — never before, so a crash never leaves a
        # directory marked known before its files exist. Runs independent of
        # files_found, since a directory with zero eligible media files is
        # exactly the case eligible_dirs exists to cover.
        if eligible_dirs:
            existing_dirs = await chunked_existing_paths(
                self.session, ScannedDirectory.remote_path, sorted(eligible_dirs)
            )
            new_dirs = sorted(eligible_dirs - existing_dirs)
            if dry_run:
                for d in new_dirs:
                    logger.info("[DRY RUN] Would mark directory as known: %s", d)
            elif new_dirs:
                for d in new_dirs:
                    await insert_or_skip_duplicate(self.session, ScannedDirectory(remote_path=d))
                await self.session.commit()

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
