"""Celery tasks for downloading files from remote SFTP."""

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.download_orchestrator import DownloadOrchestrator
from jidou.services.sftp_service import create_sftp_service
from jidou.workers._harness import (
    EventFn,
    ProgressFn,
    SetTotalFn,
    WorkflowResult,
    run_harnessed,
    run_task_workflow,
    summarize,
)


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
    return run_harnessed(self.request.id, lambda: _download_files(self.request.id, dry_run))


async def _download_files(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the download task."""

    async def _work(
        session: AsyncSession,
        on_progress: ProgressFn,
        on_event: EventFn,
        set_total: SetTotalFn,
    ) -> WorkflowResult:
        sftp = create_sftp_service(settings)

        remote_paths = settings.sftp_remote_paths_list or ["/"]
        result = await DownloadOrchestrator(
            session, sftp, settings.local_staging_path, remote_paths
        ).run(
            dry_run=dry_run,
            max_workers=settings.sftp_max_workers,
            stale_downloading_seconds=settings.download_stale_downloading_seconds,
            on_progress=on_progress,
            on_event=on_event,
        )

        total_processed = result.files_downloaded + result.files_failed
        return WorkflowResult(
            progress_current=total_processed,
            progress_total=total_processed,
            message=f"Download complete: {result.files_downloaded} files",
            result_summary=summarize(result, dry_run=dry_run),
            complete_summary={"files_downloaded": result.files_downloaded, "dry_run": dry_run},
        )

    return await run_task_workflow(
        celery_task_id,
        "download",
        _work,
        dry_run=dry_run,
        running_message="Starting download...",
    )
