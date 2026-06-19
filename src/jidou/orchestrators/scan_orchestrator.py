"""Orchestrator for scanning SFTP and creating DownloadedFile records."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.show import Show
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result of a remote SFTP scan operation."""

    shows_scanned: int
    files_found: int
    files_created: int
    files_skipped: int


class ScanOrchestrator:
    """List remote SFTP files and create or update DownloadedFile records.

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
    ) -> ScanResult:
        """Scan remote directories and create DownloadedFile rows for new files.

        Resets files in ERROR status back to PENDING so they can be retried.
        Files already in PENDING, DOWNLOADING, DOWNLOADED, ROUTING, or ROUTED
        status are skipped.

        Args:
            show_id: Limit to one show. None scans all shows with remote_path set.
            dry_run: Log what would be created without writing to the DB.
            on_progress: Optional async callback(current, total, message).

        Returns:
            ScanResult with counts.
        """
        stmt = select(Show).where(Show.remote_path.isnot(None))
        if show_id is not None:
            stmt = stmt.where(Show.id == show_id)
        shows = list((await self.session.execute(stmt)).scalars().all())

        total = len(shows)
        files_found = 0
        files_created = 0
        files_skipped = 0

        for idx, show in enumerate(shows, 1):
            if on_progress:
                await on_progress(idx, total, f"Scanning {show.title}")

            try:
                remote_files = await self.sftp.list_remote_files(show.remote_path)
            except Exception:
                logger.exception(
                    "Failed to list remote path %s for show id=%d",
                    show.remote_path,
                    show.id,
                )
                continue

            files_found += len(remote_files)

            for rf in remote_files:
                file_stmt = select(DownloadedFile).where(DownloadedFile.remote_path == rf.path)
                existing = (await self.session.execute(file_stmt)).scalar_one_or_none()

                if existing is not None:
                    if existing.status == FileStatus.ERROR:
                        if not dry_run:
                            existing.status = FileStatus.PENDING
                            existing.error_message = None
                        files_created += 1
                    else:
                        files_skipped += 1
                    continue

                if dry_run:
                    logger.info("[DRY RUN] Would create DownloadedFile for %s", rf.path)
                else:
                    self.session.add(
                        DownloadedFile(
                            show_id=show.id,
                            original_filename=rf.name,
                            remote_path=rf.path,
                            file_size=rf.size,
                            status=FileStatus.PENDING,
                        )
                    )
                files_created += 1

        if not dry_run:
            await self.session.commit()

        logger.info(
            "Scan complete: %d shows, %d found, %d created, %d skipped (dry_run=%s)",
            total,
            files_found,
            files_created,
            files_skipped,
            dry_run,
        )
        return ScanResult(
            shows_scanned=total,
            files_found=files_found,
            files_created=files_created,
            files_skipped=files_skipped,
        )
