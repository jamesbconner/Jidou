"""Orchestrator for downloading PENDING files from SFTP to local paths."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.show import Show
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)


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
        session: Active async SQLAlchemy session.
        sftp: Configured SFTPService instance.
    """

    def __init__(self, session: AsyncSession, sftp: SFTPService) -> None:
        self.session = session
        self.sftp = sftp

    async def run(
        self,
        show_id: int | None = None,
        dry_run: bool = False,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        """Download all PENDING files, updating status to DOWNLOADED or ERROR.

        Files whose Show has no local_path are counted as skipped.

        Args:
            show_id: Limit to one show. None processes all shows.
            dry_run: Log what would be downloaded without performing transfers.
            on_progress: Optional async callback(current, total, message).
                Callers may raise TaskCancelledError inside this callback;
                the exception propagates out of run() uncaught.

        Returns:
            DownloadResult with counts.
        """
        # SKIP LOCKED lets concurrent workers claim disjoint sets of rows —
        # worker B skips any rows already locked by worker A rather than blocking.
        stmt = (
            select(DownloadedFile, Show)
            .join(Show, DownloadedFile.show_id == Show.id)
            .where(
                (DownloadedFile.status == FileStatus.PENDING)
                | (DownloadedFile.status == FileStatus.ERROR)
            )
            .with_for_update(skip_locked=True, of=DownloadedFile)
        )
        if show_id is not None:
            stmt = stmt.where(DownloadedFile.show_id == show_id)

        rows = list((await self.session.execute(stmt)).all())
        total = len(rows)
        files_downloaded = 0
        bytes_downloaded = 0
        files_skipped = 0
        files_failed = 0

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

            local_path = Path(show.local_path) / file.original_filename

            if dry_run:
                logger.info("[DRY RUN] Would download %s → %s", file.remote_path, local_path)
                files_downloaded += 1
                continue

            file.status = FileStatus.DOWNLOADING
            await self.session.flush()

            try:
                result = await self.sftp.download_file(file.remote_path, local_path)
                file.status = FileStatus.DOWNLOADED
                file.local_path = str(local_path)
                file.file_size = result.size
                file.error_message = None
                files_downloaded += 1
                bytes_downloaded += result.size
            except Exception as exc:
                logger.error("Failed to download %s: %s", file.remote_path, exc)
                file.status = FileStatus.ERROR
                file.error_message = str(exc)
                files_failed += 1

            await self.session.flush()

        await self.session.commit()

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
