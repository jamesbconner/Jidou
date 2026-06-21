"""Orchestrator for scanning all configured SFTP paths and creating DownloadedFile records."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result of a remote SFTP scan operation."""

    paths_scanned: int
    files_found: int
    files_created: int
    files_skipped: int


class ScanOrchestrator:
    """Scan all configured SFTP remote paths and create DownloadedFile records.

    Files are created with ``show_id=NULL`` and status ``DISCOVERED``; the
    parse phase later matches them to shows.  Duplicate detection uses
    ``remote_path`` alone (unique on the SFTP server regardless of show).

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
            on_progress: Optional async callback(current, total, message).

        Returns:
            ScanResult with counts.
        """
        total = len(self.remote_paths)
        files_found = 0
        files_created = 0
        files_skipped = 0

        for idx, remote_path in enumerate(self.remote_paths, 1):
            if on_progress:
                await on_progress(idx, total, f"Scanning {remote_path}")

            try:
                remote_files = await self.sftp.list_remote_files_recursive(remote_path)
            except Exception:
                logger.exception("Failed to list remote path %s; skipping", remote_path)
                continue

            files_found += len(remote_files)

            for rf in remote_files:
                file_stmt = select(DownloadedFile).where(DownloadedFile.remote_path == rf.path)
                existing = (await self.session.execute(file_stmt)).scalar_one_or_none()

                if existing is not None:
                    files_skipped += 1
                    continue

                if dry_run:
                    logger.info("[DRY RUN] Would create DownloadedFile for %s", rf.path)
                    files_created += 1
                else:
                    try:
                        async with self.session.begin_nested():
                            self.session.add(
                                DownloadedFile(
                                    show_id=None,
                                    original_filename=rf.name,
                                    remote_path=rf.path,
                                    file_size=rf.size,
                                    status=FileStatus.DISCOVERED,
                                )
                            )
                        files_created += 1
                    except IntegrityError as exc:
                        orig = getattr(exc, "orig", None)
                        pgcode = getattr(orig, "pgcode", None)
                        if pgcode is not None and pgcode != "23505":
                            raise
                        logger.debug("Skipping duplicate file (race): remote_path=%s", rf.path)
                        files_skipped += 1

        if not dry_run:
            await self.session.commit()

        logger.info(
            "Scan complete: %d paths, %d found, %d created, %d skipped (dry_run=%s)",
            total,
            files_found,
            files_created,
            files_skipped,
            dry_run,
        )
        return ScanResult(
            paths_scanned=total,
            files_found=files_found,
            files_created=files_created,
            files_skipped=files_skipped,
        )
