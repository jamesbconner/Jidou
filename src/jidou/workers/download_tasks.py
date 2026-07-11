"""Celery tasks for downloading files from remote SFTP."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.download_orchestrator import DownloadOrchestrator
from jidou.services.progress import mark_task_timed_out
from jidou.services.sftp_service import SFTPService
from jidou.workers._harness import EventFn, ProgressFn, WorkflowResult, run_task_workflow

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def download_files_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Download all DISCOVERED files from remote SFTP to local staging.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually downloading.

    Returns:
        The celery task ID.
    """
    try:
        return asyncio.run(_download_files(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _download_files(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the download task."""

    async def _work(
        session: AsyncSession, on_progress: ProgressFn, on_event: EventFn
    ) -> WorkflowResult:
        sftp = SFTPService(
            host=settings.sftp_host or "",
            port=settings.sftp_port,
            username=settings.sftp_username,
            password=settings.sftp_password,
            key_path=settings.sftp_key_path,
            known_hosts=None,
            max_workers=settings.sftp_max_workers,
            max_retries=settings.sftp_max_retries,
            retry_delay=settings.sftp_retry_delay,
        )

        result = await DownloadOrchestrator(session, sftp, settings.local_staging_path).run(
            dry_run=dry_run,
            max_workers=settings.sftp_max_workers,
            on_progress=on_progress,
        )

        total_processed = result.files_downloaded + result.files_failed
        return WorkflowResult(
            progress_current=total_processed,
            progress_total=total_processed,
            message=f"Download complete: {result.files_downloaded} files",
            result_summary={
                "files_downloaded": result.files_downloaded,
                "bytes_downloaded": result.bytes_downloaded,
                "files_failed": result.files_failed,
                "dry_run": dry_run,
            },
            complete_summary={"files_downloaded": result.files_downloaded, "dry_run": dry_run},
        )

    return await run_task_workflow(
        celery_task_id,
        "download",
        _work,
        progress_total=0,
        dry_run=dry_run,
        running_message="Starting download...",
    )
