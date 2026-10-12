"""Orchestrator for scanning configured SFTP paths and creating DownloadedFile records.

Scans shallowly: only the immediate children of each configured remote path
are listed on every run. A full recursive walk only ever happens once per
top-level directory, the first time it's seen — Jidou's SFTP sources
(seedbox/torrent-client download folders) are wide, flat, and single-use,
so a directory known once is treated as permanently immutable and is never
walked again. See ``ScannedDirectory``.
"""

import logging
from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus, IgnoredReason
from jidou.models.scanned_directory import ScannedDirectory
from jidou.orchestrators._bulk_existence import chunked_existing_paths, insert_or_skip_duplicate
from jidou.orchestrators._events import EventSink
from jidou.orchestrators._remote_inventory import list_roots, walk_directories
from jidou.services.callbacks import OnEvent, OnProgress
from jidou.services.file_filters import find_noscan_scan_overlaps, is_under_any_path
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


@dataclass
class _WalkTotals:
    """Counts from deep-walking the newly discovered directories."""

    files_found: int = 0
    files_created: int = 0
    files_skipped: int = 0
    dirs_discovered: int = 0


async def _report_scanning(on_progress: OnProgress, idx: int, total: int, remote_path: str) -> None:
    """Report that the shallow listing of *remote_path* is about to start.

    Args:
        on_progress: The caller's progress callback.
        idx: 1-based position of *remote_path* among the configured paths.
        total: Number of configured paths.
        remote_path: The path about to be listed.
    """
    await on_progress(idx, total, f"Scanning {remote_path}")


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
        noscan_paths: Remote paths (or subdirectories of a scanned path)
            whose files are still discovered and downloaded but never
            parsed, matched, or routed — see ``IgnoredReason.NOSCAN_PATH``.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        remote_paths: list[str],
        noscan_paths: list[str] | None = None,
    ) -> None:
        self.session = session
        self.sftp = sftp
        self.remote_paths = remote_paths
        self.noscan_paths = noscan_paths or []

        overlaps = find_noscan_scan_overlaps(self.remote_paths, self.noscan_paths)
        for scan_path, noscan_path in overlaps:
            logger.warning(
                "Noscan path %r is an ancestor of (or identical to) scan path %r — "
                "every file under %r will be excluded from matching, likely "
                "unintentionally. Check SFTP_NOSCAN_PATHS.",
                noscan_path,
                scan_path,
                scan_path,
            )

    async def run(
        self,
        dry_run: bool = False,
        on_progress: OnProgress | None = None,
        on_event: OnEvent | None = None,
    ) -> ScanResult:
        """Scan every remote path and create DISCOVERED records for new files.

        Already-tracked files (any status) are skipped to preserve their
        current pipeline state.

        Args:
            dry_run: Log what would be created without writing to the DB.
            on_progress: Optional async callback(current, total, message),
                called once per configured remote path during the initial
                shallow-listing phase.
            on_event: Optional async callback(level, message, ctx) for
                structured per-item event log entries. Fired only for newly
                discovered files, directory walk outcomes, and errors —
                already-known files are silently counted into
                ``files_skipped`` rather than emitted one at a time, since a
                library scan can skip thousands of them per run.

        Returns:
            ScanResult with counts. ``files_found``/``files_skipped`` reflect
            only files discovered this run (top-level files plus any newly
            deep-walked directories) — a known, skipped directory contributes
            nothing to these counts, unlike a full rescan. ``dirs_discovered``
            counts only directories actually marked known this run, not
            merely seen as new.
        """

        emit = EventSink(on_event, swallow_errors=True)
        total = len(self.remote_paths)

        # Phase 1: shallow-list every configured remote path.
        listing = await list_roots(
            self.sftp,
            self.remote_paths,
            before_each=partial(_report_scanning, on_progress) if on_progress else None,
            on_error=partial(self._report_list_failure, emit),
        )

        # Phase 2: one combined existence check for top-level files across ALL paths.
        existing_file_paths = await chunked_existing_paths(
            self.session, DownloadedFile.remote_path, [f.path for f in listing.files]
        )
        files_created, files_skipped = await self._record_new_files(
            listing.files, existing_file_paths, dry_run, emit
        )
        files_found = len(listing.files)

        # Phase 3: one combined existence check for top-level directories across ALL paths.
        existing_dir_paths = await chunked_existing_paths(
            self.session, ScannedDirectory.remote_path, [d.path for d in listing.dirs]
        )
        # Known directories are filtered out *before* walking: they are never re-walked.
        new_dirs = [d for d in listing.dirs if d.path not in existing_dir_paths]

        # Phases 4-5: deep-walk the new directories and record what they contain.
        walked = await self._scan_new_directories(new_dirs, dry_run, emit)
        files_found += walked.files_found
        files_created += walked.files_created
        files_skipped += walked.files_skipped

        if not dry_run:
            await self.session.commit()

        logger.info(
            "Scan complete: %d paths, %d found, %d created, %d skipped, "
            "%d new directories discovered (dry_run=%s)",
            total,
            files_found,
            files_created,
            files_skipped,
            walked.dirs_discovered,
            dry_run,
        )
        return ScanResult(
            paths_scanned=total,
            files_found=files_found,
            files_created=files_created,
            files_skipped=files_skipped,
            dirs_discovered=walked.dirs_discovered,
        )

    @staticmethod
    async def _report_list_failure(emit: EventSink, root: str, exc: Exception) -> None:
        """Emit the error event for a remote path whose shallow listing failed.

        Args:
            emit: Event sink for the current run.
            root: The remote path that could not be listed.
            exc: The listing failure.
        """
        await emit(
            "error",
            f"Failed to list {root!r}: {exc}",
            {"remote_path": root, "error": str(exc)},
        )

    async def _scan_new_directories(
        self, new_dirs: list[RemoteFile], dry_run: bool, emit: EventSink
    ) -> _WalkTotals:
        """Deep-walk *new_dirs* together, record the files found, and mark clean directories.

        Args:
            new_dirs: Top-level directories not yet recorded as known.
            dry_run: When True, record nothing.
            emit: Event sink for the current run.

        Returns:
            Counts for the files found inside the walked directories and the number
            of directories marked known. All zero when *new_dirs* is empty.
        """
        if not new_dirs:
            return _WalkTotals()

        # SFTP I/O only — no session access — so every directory walks concurrently,
        # across every configured remote path together.
        walk = await walk_directories(self.sftp, [d.path for d in new_dirs])
        for dir_path, error in walk.failures:
            logger.warning("Failed to deep-walk new directory %s: %s", dir_path, error)
            await emit(
                "error",
                f"Failed to walk directory {dir_path!r}: {error}",
                {"remote_path": dir_path, "error": str(error)},
            )

        all_new_files = [f for _, outcome in walk.walked for f in outcome.files]
        # Phase 5: one combined existence check for files across ALL newly-walked directories.
        new_dir_existing = await chunked_existing_paths(
            self.session, DownloadedFile.remote_path, [f.path for f in all_new_files]
        )
        created, skipped = await self._record_new_files(
            all_new_files, new_dir_existing, dry_run, emit
        )
        dirs_discovered = await self._mark_walked_directories(walk.walked, dry_run, emit)
        return _WalkTotals(
            files_found=len(all_new_files),
            files_created=created,
            files_skipped=skipped,
            dirs_discovered=dirs_discovered,
        )

    async def _record_new_files(
        self, files: list[RemoteFile], existing: set[str], dry_run: bool, emit: EventSink
    ) -> tuple[int, int]:
        """Create DISCOVERED rows for the *files* not in *existing*, emitting one event each.

        Args:
            files: Candidate files, in discovery order.
            existing: Remote paths that are already tracked.
            dry_run: When True, count what would be created without writing.
            emit: Event sink for the current run.

        Returns:
            ``(created, skipped)``. Already-tracked files are skipped silently; a file
            lost to a concurrent scan is skipped with an event.
        """
        created = 0
        skipped = 0
        for rf in files:
            if rf.path in existing:
                # Not emitted per-file: a library scan can skip thousands of
                # already-known files, which would drown the new/interesting
                # events below. The aggregate count is reported in the
                # phase-summary event the caller (SyncOrchestrator) emits.
                skipped += 1
            elif await self._create_discovered_file(rf, dry_run):
                created += 1
                await emit(
                    "info", f"Discovered {rf.name!r}", {"remote_path": rf.path, "size": rf.size}
                )
            else:
                skipped += 1
                await emit(
                    "info",
                    f"Skipped {rf.name!r}: concurrent scan already created it",
                    {"remote_path": rf.path},
                )
        return created, skipped

    async def _mark_walked_directories(
        self,
        walked: list[tuple[str, RecursiveListResult]],
        dry_run: bool,
        emit: EventSink,
    ) -> int:
        """Mark each fully walked directory known; report the ones that must be retried.

        Args:
            walked: ``(directory, walk result)`` for each walk that returned.
            dry_run: When True, report what would be marked without writing.
            emit: Event sink for the current run.

        Returns:
            Number of directories marked known (or that would be, under dry_run).
        """
        marked = 0
        for dir_path, outcome in walked:
            if not outcome.fully_walked:
                logger.info(
                    "Directory %s not fully walked (io_failures=%d, "
                    "recently_modified_skipped=%d, directories_deferred=%d) "
                    "— will retry on next scan",
                    dir_path,
                    outcome.io_failures,
                    outcome.recently_modified_skipped,
                    outcome.directories_deferred,
                )
                await emit(
                    "warn",
                    f"Directory {dir_path!r} not fully walked "
                    f"(io_failures={outcome.io_failures}, "
                    f"recently_modified_skipped={outcome.recently_modified_skipped}, "
                    f"directories_deferred={outcome.directories_deferred}) "
                    "— will retry on next scan",
                    {"remote_path": dir_path},
                )
            elif dry_run:
                logger.info("[DRY RUN] Would mark directory as known: %s", dir_path)
                await emit(
                    "info",
                    f"[Dry run] Would mark directory known: {dir_path!r}",
                    {"remote_path": dir_path},
                )
                marked += 1
            else:
                await self._mark_scanned_directory(dir_path)
                await emit(
                    "info",
                    f"Directory fully walked and marked known: {dir_path!r}",
                    {"remote_path": dir_path},
                )
                marked += 1
        return marked

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
        ignored_reason = (
            IgnoredReason.NOSCAN_PATH if is_under_any_path(rf.path, self.noscan_paths) else None
        )
        row = DownloadedFile.new_from_remote(
            name=rf.name,
            remote_path=rf.path,
            size=rf.size,
            status=FileStatus.DISCOVERED,
            ignored_reason=ignored_reason,
        )
        return await insert_or_skip_duplicate(self.session, row)

    async def _mark_scanned_directory(self, remote_path: str) -> None:
        """Insert a ScannedDirectory row marking *remote_path* as permanently known.

        Args:
            remote_path: Full remote path of the directory to mark.
        """
        await insert_or_skip_duplicate(self.session, ScannedDirectory(remote_path=remote_path))
