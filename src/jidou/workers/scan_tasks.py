"""Celery tasks for scanning remote SFTP for new files."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator
from jidou.services.progress import mark_task_timed_out
from jidou.services.sftp_service import SFTPService
from jidou.workers._harness import EventFn, ProgressFn, WorkflowResult, run_task_workflow

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def scan_remote_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Scan the remote SFTP directory for new files.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually scanning.

    Returns:
        The celery task ID.
    """
    try:
        return asyncio.run(_scan_remote(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _scan_remote(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the scan task."""

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

        remote_paths = settings.sftp_remote_paths_list or ["/"]
        result = await ScanOrchestrator(session, sftp, remote_paths).run(
            dry_run=dry_run, on_progress=on_progress
        )

        return WorkflowResult(
            progress_current=result.paths_scanned,
            progress_total=result.paths_scanned,
            message=(
                f"Scan complete: {result.files_created} new files found, "
                f"{result.dirs_discovered} new directories discovered"
            ),
            result_summary={
                "paths_scanned": result.paths_scanned,
                "files_found": result.files_found,
                "files_created": result.files_created,
                "files_skipped": result.files_skipped,
                "dirs_discovered": result.dirs_discovered,
                "dry_run": dry_run,
            },
            complete_summary={"files_created": result.files_created, "dry_run": dry_run},
        )

    return await run_task_workflow(
        celery_task_id,
        "scan",
        _work,
        progress_total=0,
        dry_run=dry_run,
        running_message="Scanning remote directories...",
    )
