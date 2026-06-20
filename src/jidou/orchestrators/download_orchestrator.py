"""Orchestrator for downloading PENDING files from SFTP to local paths."""

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

        In non-dry-run mode each file is processed with a LIMIT 1
        SELECT … FOR UPDATE SKIP LOCKED query so the row lock is held only
        for the brief claim step (PENDING → DOWNLOADING + commit), not for
        the entire SFTP transfer.  DOWNLOADING status then prevents other
        workers from re-selecting the same file without needing a long-lived
        lock.

        Args:
            show_id: Limit to one show. None processes all shows.
            dry_run: Log what would be downloaded without performing transfers.
            on_progress: Optional async callback(current, total, message).
                Callers may raise TaskCancelledError inside this callback;
                the exception propagates out of run() uncaught.

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
                local_path = Path(show.local_path) / file.original_filename
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

        idx = 0
        while True:
            # Lock exactly one eligible row; other workers skip locked rows.
            stmt = (
                select(DownloadedFile, Show)
                .join(Show, DownloadedFile.show_id == Show.id)
                .where(base_where)
                .with_for_update(skip_locked=True, of=DownloadedFile)
                .limit(1)
            )
            if show_id is not None:
                stmt = stmt.where(DownloadedFile.show_id == show_id)

            row = (await self.session.execute(stmt)).first()
            if row is None:
                break

            idx += 1
            file, show = row

            if on_progress:
                await on_progress(idx, total, f"Downloading {file.original_filename}")

            if show.local_path is None:
                logger.warning(
                    "Show id=%d has no local_path; skipping file id=%d",
                    show.id,
                    file.id,
                )
                files_skipped += 1
                await self.session.commit()  # release FOR UPDATE lock
                continue

            local_path = Path(show.local_path) / file.original_filename

            # Claim the file: transition to DOWNLOADING and commit to release the
            # FOR UPDATE lock before the slow SFTP transfer begins.
            file.status = FileStatus.DOWNLOADING
            await self.session.flush()
            await self.session.commit()  # lock released; DOWNLOADING visible to other workers

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
            await self.session.commit()  # persist DOWNLOADED or ERROR

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
