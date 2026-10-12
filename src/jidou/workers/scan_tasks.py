"""Celery tasks for scanning remote SFTP for new files."""

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator
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
    return run_harnessed(self.request.id, lambda: _scan_remote(self.request.id, dry_run))


async def _scan_remote(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the scan task."""

    async def _work(
        session: AsyncSession,
        on_progress: ProgressFn,
        on_event: EventFn,
        set_total: SetTotalFn,
    ) -> WorkflowResult:
        sftp = create_sftp_service(settings)

        remote_paths = settings.sftp_remote_paths_list or ["/"]
        noscan_paths = settings.sftp_noscan_paths_list
        result = await ScanOrchestrator(session, sftp, remote_paths, noscan_paths).run(
            dry_run=dry_run, on_progress=on_progress, on_event=on_event
        )

        return WorkflowResult(
            progress_current=result.paths_scanned,
            progress_total=result.paths_scanned,
            message=(
                f"Scan complete: {result.files_created} new files found, "
                f"{result.files_skipped} already known, "
                f"{result.dirs_discovered} new directories discovered"
            ),
            result_summary=summarize(result, dry_run=dry_run),
            complete_summary={"files_created": result.files_created, "dry_run": dry_run},
        )

    return await run_task_workflow(
        celery_task_id,
        "scan",
        _work,
        dry_run=dry_run,
        running_message="Scanning remote directories...",
    )
