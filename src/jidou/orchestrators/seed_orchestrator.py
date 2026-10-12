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
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.scanned_directory import ScannedDirectory
from jidou.orchestrators._bulk_existence import (
    chunked_existing_paths,
    chunked_existing_statuses,
    insert_or_skip_duplicate,
)
from jidou.orchestrators._remote_inventory import WalkOutcome, list_roots, walk_directories
from jidou.services.callbacks import OnProgress
from jidou.services.sftp_service import RemoteFile, SFTPService

logger = logging.getLogger(__name__)


async def _log_listing(idx: int, total: int, remote_path: str) -> None:
    """Log that the shallow listing of *remote_path* is about to start.

    Args:
        idx: 1-based position of *remote_path* among the configured paths.
        total: Number of configured paths.
        remote_path: The path about to be listed.
    """
    logger.info("Listing remote path %d/%d: %s", idx, total, remote_path)


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
        on_progress: OnProgress | None = None,
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

        # Phase 1: shallow-list every configured remote path, collecting
        # top-level files directly and top-level directories to deep-walk.
        listing = await list_roots(self.sftp, self.remote_paths, before_each=_log_listing)

        # Phase 2: deep-walk every top-level directory found across ALL remote
        # paths, concurrently in one batch (bounded by sftp.max_workers).
        walk = await walk_directories(self.sftp, [d.path for d in listing.dirs])
        all_remote, eligible_dirs = self._collect_walked(listing.files, walk)

        files_seeded, files_skipped, skipped_by_status = await self._seed_files(
            all_remote, dry_run, on_progress
        )

        # Directory marking always happens last, strictly after every file
        # batch above has been committed (or, if there were no files, there was
        # nothing to seed first) — never before, so a crash never leaves a
        # directory marked known before its files exist. Runs independent of
        # the file count, since a directory with zero eligible media files is
        # exactly the case eligible_dirs exists to cover.
        await self._mark_directories(eligible_dirs, dry_run)

        files_found = len(all_remote)
        logger.info(
            "Seed complete: %d paths scanned (%d failed), %d/%d files seeded, "
            "%d skipped (dry_run=%s)",
            total_paths,
            listing.failed_roots,
            files_seeded,
            files_found,
            files_skipped,
            dry_run,
        )
        return SeedResult(
            paths_scanned=total_paths,
            paths_failed=listing.failed_roots,
            files_found=files_found,
            files_seeded=files_seeded,
            files_skipped=files_skipped,
            skipped_by_status=skipped_by_status,
            dry_run=dry_run,
        )

    @staticmethod
    def _collect_walked(
        top_level_files: list[RemoteFile], walk: WalkOutcome
    ) -> tuple[list[RemoteFile], set[str]]:
        """Gather every file to consider and the directories safe to mark known.

        Args:
            top_level_files: Files found directly under the configured roots.
            walk: Outcome of deep-walking the top-level directories.

        Returns:
            ``(all_files, eligible_dirs)``: the top-level files followed by every
            walked file, and the directories whose walk completed cleanly.
        """
        for dir_path, error in walk.failures:
            logger.warning("Failed to deep-walk directory %s: %s", dir_path, error)
        all_files = list(top_level_files)
        eligible_dirs: set[str] = set()
        for dir_path, outcome in walk.walked:
            all_files.extend(outcome.files)
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
        return all_files, eligible_dirs

    async def _seed_files(
        self, all_files: list[RemoteFile], dry_run: bool, on_progress: OnProgress | None
    ) -> tuple[int, int, dict[str, int]]:
        """Seed the untracked *all_files*, counting the tracked ones by status.

        Args:
            all_files: Every file found by the inventory.
            dry_run: When True, log what would be seeded without writing.
            on_progress: Optional progress callback, called after each batch commit.

        Returns:
            ``(seeded, skipped, skipped_by_status)``.
        """
        files_skipped = 0
        skipped_by_status: dict[str, int] = {}
        if not all_files:
            return 0, files_skipped, skipped_by_status

        # Bulk existence check: chunk paths to avoid oversized IN() clauses.
        existing = await chunked_existing_statuses(self.session, [f.path for f in all_files])
        pending: list[RemoteFile] = []
        for rf in all_files:
            if rf.path in existing:
                status_str = existing[rf.path]
                files_skipped += 1
                skipped_by_status[status_str] = skipped_by_status.get(status_str, 0) + 1
                logger.debug("Skipping already-tracked file (status=%s): %s", status_str, rf.path)
            else:
                pending.append(rf)

        if dry_run:
            for rf in pending:
                logger.info("[DRY RUN] Would seed %s (%d bytes)", rf.path, rf.size)
            return len(pending), files_skipped, skipped_by_status

        files_seeded, race_lost = await self._insert_seeded_batches(pending, on_progress)
        if race_lost:
            # Concurrent scan won the race — counts as skipped.
            files_skipped += race_lost
            skipped_by_status["discovered"] = skipped_by_status.get("discovered", 0) + race_lost
        return files_seeded, files_skipped, skipped_by_status

    async def _insert_seeded_batches(
        self, pending: list[RemoteFile], on_progress: OnProgress | None
    ) -> tuple[int, int]:
        """Insert SEEDED rows for *pending* in committed batches.

        Insert in batches for bounded transactions and crash resumability.
        Directory marking only happens after this fully completes, so a crash
        here never leaves a directory marked known with unseeded files.

        Args:
            pending: Untracked files to seed.
            on_progress: Optional progress callback, called after each batch commit.

        Returns:
            ``(seeded, race_lost)``: rows inserted, and rows a concurrent writer
            created first.
        """
        seeded = 0
        race_lost = 0
        total_pending = len(pending)
        for batch_start in range(0, total_pending, self.batch_size):
            for rf in pending[batch_start : batch_start + self.batch_size]:
                new_file = DownloadedFile.new_from_remote(
                    name=rf.name, remote_path=rf.path, size=rf.size, status=FileStatus.SEEDED
                )
                if await insert_or_skip_duplicate(self.session, new_file):
                    seeded += 1
                else:
                    race_lost += 1

            await self.session.commit()

            progress_done = min(batch_start + self.batch_size, total_pending)
            if on_progress:
                await on_progress(
                    progress_done,
                    total_pending,
                    f"Seeded {progress_done}/{total_pending} files",
                )
        return seeded, race_lost

    async def _mark_directories(self, eligible_dirs: set[str], dry_run: bool) -> None:
        """Mark the cleanly walked, not-yet-known directories as known.

        Args:
            eligible_dirs: Directories whose deep walk completed without gaps.
            dry_run: When True, log what would be marked without writing.
        """
        if not eligible_dirs:
            return
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
