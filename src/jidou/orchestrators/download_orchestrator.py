"""Orchestrator for downloading DISCOVERED files from SFTP to the local staging area."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)


def _staging_path_for(remote_path: str, staging_root: str) -> Path:
    """Return the local staging destination, mirroring remote directory structure.

    For example: remote ``/downloads/shows/ShowName_S01E01.mkv`` under
    staging root ``/data/staging`` becomes
    ``/data/staging/downloads/shows/ShowName_S01E01.mkv``.

    Args:
        remote_path: Full path of the file on the remote SFTP server.
        staging_root: Local staging directory root.

    Returns:
        Absolute :class:`Path` for the staging destination.
    """
    # Strip leading slash so Path joining works correctly
    relative = remote_path.lstrip("/")
    return Path(staging_root) / relative


@dataclass
class DownloadResult:
    """Result of a batch SFTP download operation."""

    files_downloaded: int
    bytes_downloaded: int
    files_failed: int
    dry_run: bool


class DownloadOrchestrator:
    """Download DISCOVERED DownloadedFile records from SFTP to a local staging area.

    Files land under ``local_staging_path`` with their remote directory
    structure preserved.  ``show_id`` is still NULL at this stage; the parse
    phase links each file to a show after download.

    Args:
        session: Active async SQLAlchemy session (must be created with
            ``expire_on_commit=False`` so file objects remain usable after
            each intermediate commit).
        sftp: Configured SFTPService instance.
        local_staging_path: Root directory for staging downloads.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        local_staging_path: str,
    ) -> None:
        self.session = session
        self.sftp = sftp
        self.local_staging_path = local_staging_path

    async def run(
        self,
        dry_run: bool = False,
        max_workers: int = 8,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        """Download all DISCOVERED files, updating status to DOWNLOADED or ERROR.

        In non-dry-run mode files are processed in batches of up to
        ``max_workers``.  Each batch is claimed atomically with
        ``SELECT … FOR UPDATE SKIP LOCKED``, marked DOWNLOADING, committed
        (locks released so other workers can proceed), then downloaded in
        parallel via ``asyncio.gather``.  DB status updates happen
        sequentially after the parallel transfers complete.

        Args:
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
        files_failed = 0

        # Only retry ERROR files that never reached staging (local_path IS NULL).
        # Parse and route failures also land in ERROR but have a staging local_path;
        # re-downloading them would undo pipeline progress.
        base_where = (DownloadedFile.status == FileStatus.DISCOVERED) | (
            (DownloadedFile.status == FileStatus.ERROR) & (DownloadedFile.local_path.is_(None))
        )

        if dry_run:
            stmt = select(DownloadedFile).where(base_where)
            rows = list((await self.session.execute(stmt)).scalars().all())
            total = len(rows)

            for idx, file in enumerate(rows, 1):
                if on_progress:
                    await on_progress(idx, total, f"Downloading {file.original_filename}")
                local_path = _staging_path_for(file.remote_path, self.local_staging_path)
                logger.info("[DRY RUN] Would download %s → %s", file.remote_path, local_path)
                files_downloaded += 1

            logger.info(
                "Download complete: %d downloaded, %d failed, %d bytes (dry_run=%s)",
                files_downloaded,
                files_failed,
                bytes_downloaded,
                dry_run,
            )
            return DownloadResult(
                files_downloaded=files_downloaded,
                bytes_downloaded=bytes_downloaded,
                files_failed=files_failed,
                dry_run=dry_run,
            )

        # Count upfront for accurate progress reporting (no lock held).
        count_stmt = select(func.count(DownloadedFile.id)).where(base_where)
        total = (await self.session.execute(count_stmt)).scalar_one()

        progress_idx = 0

        while True:
            # Claim up to max_workers eligible rows; other workers skip locked rows.
            stmt = (
                select(DownloadedFile)
                .where(base_where)
                .with_for_update(skip_locked=True, of=DownloadedFile)
                .limit(max_workers)
            )

            batch = list((await self.session.execute(stmt)).scalars().all())
            if not batch:
                break

            # Mark all batch files DOWNLOADING before releases the locks.
            pending: list[tuple[DownloadedFile, Path]] = []
            for file in batch:
                local_path = _staging_path_for(file.remote_path, self.local_staging_path)
                file.status = FileStatus.DOWNLOADING
                pending.append((file, local_path))

            # Flush DOWNLOADING status and commit to release FOR UPDATE locks.
            await self.session.flush()
            await self.session.commit()

            gather_cleanup_done = False
            try:
                if on_progress and pending:
                    await on_progress(progress_idx, total, f"Downloading {len(pending)} files")

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
            "Download complete: %d downloaded, %d failed, %d bytes (dry_run=%s)",
            files_downloaded,
            files_failed,
            bytes_downloaded,
            dry_run,
        )
        return DownloadResult(
            files_downloaded=files_downloaded,
            bytes_downloaded=bytes_downloaded,
            files_failed=files_failed,
            dry_run=dry_run,
        )
