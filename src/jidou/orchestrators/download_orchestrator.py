"""Orchestrator for downloading PENDING files from SFTP to local paths."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.show import Show
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)


def _local_path_for(remote_path: str, show_remote_path: str | None, show_local_path: str) -> Path:
    """Return the local destination path, mirroring remote subdirectory structure.

    Season subdirectories (e.g. ``Season 01/ep01.mkv``) are preserved locally
    so files with identical basenames in different seasons never overwrite each
    other.

    Falls back to the bare filename when ``show_remote_path`` is ``None`` or
    empty (no show root configured) or when the remote path cannot be made
    relative to the show root.
    """
    if not show_remote_path:
        return Path(show_local_path) / Path(remote_path).name

    # rstrip("/") on a bare "/" yields ""; restore "/" so relative_to() works
    # when show_remote_path is the filesystem root rather than a show directory.
    remote_root = show_remote_path.rstrip("/") or "/"
    try:
        rel = Path(remote_path).relative_to(remote_root)
    except ValueError:
        rel = Path(Path(remote_path).name)
    return Path(show_local_path) / rel


@dataclass
class DownloadResult:
    """Result of a batch SFTP download operation."""

    files_downloaded: int
    bytes_downloaded: int
    files_skipped: int
    files_failed: int
    dry_run: bool


class DownloadOrchestrator:
    """Download PENDING DownloadedFile records from SFTP.

    Requires the file's associated Show to have local_path set.
    Files without a local_path are skipped.

    Args:
        session: Active async SQLAlchemy session (must be created with
            ``expire_on_commit=False`` so file objects remain usable after
            each intermediate commit).
        sftp: Configured SFTPService instance.
    """

    def __init__(self, session: AsyncSession, sftp: SFTPService) -> None:
        self.session = session
        self.sftp = sftp

    async def run(
        self,
        show_id: int | None = None,
        dry_run: bool = False,
        max_workers: int = 8,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        """Download all PENDING files, updating status to DOWNLOADED or ERROR.

        Files whose Show has no local_path are counted as skipped.

        In non-dry-run mode files are processed in batches of up to
        ``max_workers``.  Each batch is claimed atomically with
        ``SELECT … FOR UPDATE SKIP LOCKED``, marked DOWNLOADING, committed
        (locks released so other workers can proceed), then downloaded in
        parallel via ``asyncio.gather``.  DB status updates happen
        sequentially after the parallel transfers complete.

        Args:
            show_id: Limit to one show. None processes all shows.
            dry_run: Log what would be downloaded without performing transfers.
            max_workers: Maximum concurrent SFTP transfers per batch.
            on_progress: Optional async callback(current, total, message).
                Called sequentially after each batch; callers may raise
                TaskCancelledError inside the callback to abort the run.

        Returns:
            DownloadResult with counts.
        """
        files_downloaded = 0
        bytes_downloaded = 0
        files_skipped = 0
        files_failed = 0

        base_where = (DownloadedFile.status == FileStatus.PENDING) | (
            DownloadedFile.status == FileStatus.ERROR
        )

        if dry_run:
            stmt = (
                select(DownloadedFile, Show)
                .join(Show, DownloadedFile.show_id == Show.id)
                .where(base_where)
            )
            if show_id is not None:
                stmt = stmt.where(DownloadedFile.show_id == show_id)
            rows = list((await self.session.execute(stmt)).all())
            total = len(rows)

            for idx, (file, show) in enumerate(rows, 1):
                if on_progress:
                    await on_progress(idx, total, f"Downloading {file.original_filename}")
                if show.local_path is None:
                    logger.warning(
                        "Show id=%d has no local_path; skipping file id=%d",
                        show.id,
                        file.id,
                    )
                    files_skipped += 1
                    continue
                local_path = _local_path_for(file.remote_path, show.remote_path, show.local_path)
                logger.info("[DRY RUN] Would download %s → %s", file.remote_path, local_path)
                files_downloaded += 1

            logger.info(
                "Download complete: %d downloaded, %d failed, %d skipped, %d bytes (dry_run=%s)",
                files_downloaded,
                files_failed,
                files_skipped,
                bytes_downloaded,
                dry_run,
            )
            return DownloadResult(
                files_downloaded=files_downloaded,
                bytes_downloaded=bytes_downloaded,
                files_skipped=files_skipped,
                files_failed=files_failed,
                dry_run=dry_run,
            )

        # Count upfront for accurate progress reporting (no lock held).
        count_stmt = (
            select(func.count(DownloadedFile.id))
            .join(Show, DownloadedFile.show_id == Show.id)
            .where(base_where)
        )
        if show_id is not None:
            count_stmt = count_stmt.where(DownloadedFile.show_id == show_id)
        total = (await self.session.execute(count_stmt)).scalar_one()

        progress_idx = 0
        # IDs of files that cannot be processed this run (show has no local_path).
        # Excluded from subsequent batch queries to prevent infinite re-selection.
        skipped_ids: set[int] = set()

        while True:
            # Claim up to max_workers eligible rows; other workers skip locked rows.
            stmt = (
                select(DownloadedFile, Show)
                .join(Show, DownloadedFile.show_id == Show.id)
                .where(base_where)
                .with_for_update(skip_locked=True, of=DownloadedFile)
                .limit(max_workers)
            )
            if show_id is not None:
                stmt = stmt.where(DownloadedFile.show_id == show_id)
            if skipped_ids:
                stmt = stmt.where(DownloadedFile.id.notin_(skipped_ids))

            batch = list((await self.session.execute(stmt)).all())
            if not batch:
                break

            # Classify rows: mark eligible files as DOWNLOADING; record skipped.
            skipped_in_batch: list[DownloadedFile] = []
            pending: list[tuple[DownloadedFile, Path]] = []
            for file, show in batch:
                if show.local_path is None:
                    logger.warning(
                        "Show id=%d has no local_path; skipping file id=%d",
                        show.id,
                        file.id,
                    )
                    skipped_ids.add(file.id)
                    files_skipped += 1
                    skipped_in_batch.append(file)
                    continue
                local_path = _local_path_for(file.remote_path, show.remote_path, show.local_path)
                file.status = FileStatus.DOWNLOADING
                pending.append((file, local_path))

            # Flush DOWNLOADING status and commit to release FOR UPDATE locks.
            # Other workers can now claim new rows; DOWNLOADING prevents double-work.
            await self.session.flush()
            await self.session.commit()

            # Everything from here until the post-commit progress loop may raise
            # TaskCancelledError (via on_progress) or BaseException (outer cancel).
            # If that happens BEFORE the gather finishes, any files still in
            # DOWNLOADING must be reset to ERROR so they are not stuck permanently.
            gather_cleanup_done = False
            try:
                # Emit progress for skipped rows and check for cancellation before
                # starting transfers.  Raises TaskCancelledError if cancelled.
                if on_progress:
                    for file in skipped_in_batch:
                        progress_idx += 1
                        await on_progress(progress_idx, total, f"Skipped {file.original_filename}")
                    if pending:
                        await on_progress(progress_idx, total, f"Downloading {len(pending)} files")

                if not pending:
                    continue

                # Download all files in this batch concurrently.
                # Use Task objects so the interrupt handler can tell which
                # transfers already finished (and must not be reset to ERROR).
                tasks = [
                    asyncio.ensure_future(self.sftp.download_file(file.remote_path, local_path))
                    for file, local_path in pending
                ]

                try:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                except BaseException:
                    # Outer task cancelled while gather was in flight.
                    # Tasks that completed successfully must be credited, not reset.
                    for (file, local_path), task in zip(pending, tasks, strict=True):
                        if task.done() and not task.cancelled() and task.exception() is None:
                            r = task.result()
                            file.status = FileStatus.DOWNLOADED
                            file.local_path = str(local_path)
                            file.file_size = r.size
                            file.error_message = None
                            files_downloaded += 1
                            bytes_downloaded += r.size
                        elif file.status == FileStatus.DOWNLOADING:
                            file.status = FileStatus.ERROR
                            file.error_message = "Download interrupted"
                            files_failed += 1
                    try:
                        await self.session.flush()
                        await self.session.commit()
                    except Exception:
                        logger.warning(
                            "Could not persist interrupted statuses; "
                            "manual recovery via PATCH /files/<id> may be required"
                        )
                    gather_cleanup_done = True
                    raise

                # Update statuses sequentially — safe because all SFTP I/O is done.
                for (file, local_path), result in zip(pending, results, strict=True):
                    if isinstance(result, BaseException):
                        error_msg = (
                            "Download interrupted"
                            if isinstance(result, asyncio.CancelledError)
                            else str(result)
                        )
                        logger.error("Failed to download %s: %s", file.remote_path, result)
                        file.status = FileStatus.ERROR
                        file.error_message = error_msg
                        files_failed += 1
                    else:
                        file.status = FileStatus.DOWNLOADED
                        file.local_path = str(local_path)
                        file.file_size = result.size
                        file.error_message = None
                        files_downloaded += 1
                        bytes_downloaded += result.size

                await self.session.flush()
                await self.session.commit()

                # Emit progress after committing so the DB reflects final state.
                # on_progress may raise TaskCancelledError to abort between batches.
                if on_progress:
                    for file, _ in pending:
                        progress_idx += 1
                        msg = (
                            f"Downloaded {file.original_filename}"
                            if file.status == FileStatus.DOWNLOADED
                            else f"Failed {file.original_filename}"
                        )
                        await on_progress(progress_idx, total, msg)

            except BaseException:
                if not gather_cleanup_done:
                    # TaskCancelledError from on_progress before transfers started,
                    # or after gather committed.  Reset any DOWNLOADING files.
                    for file, _ in pending:
                        if file.status == FileStatus.DOWNLOADING:
                            file.status = FileStatus.ERROR
                            file.error_message = "Download interrupted"
                            files_failed += 1
                    try:
                        await self.session.flush()
                        await self.session.commit()
                    except Exception:
                        logger.warning(
                            "Could not persist interrupted statuses; "
                            "manual recovery via PATCH /files/<id> may be required"
                        )
                raise

        logger.info(
            "Download complete: %d downloaded, %d failed, %d skipped, %d bytes (dry_run=%s)",
            files_downloaded,
            files_failed,
            files_skipped,
            bytes_downloaded,
            dry_run,
        )
        return DownloadResult(
            files_downloaded=files_downloaded,
            bytes_downloaded=bytes_downloaded,
            files_skipped=files_skipped,
            files_failed=files_failed,
            dry_run=dry_run,
        )
