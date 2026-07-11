"""Celery tasks for routing MATCHED files from staging to their final paths."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.orchestrators.route_orchestrator import RouteOrchestrator
from jidou.services.progress import mark_task_timed_out
from jidou.workers._harness import EventFn, ProgressFn, WorkflowResult, run_task_workflow

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def route_files_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Move all MATCHED files from staging to their final local paths.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually moving files.

    Returns:
        The celery task ID.
    """
    try:
        return asyncio.run(_route_files(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _route_files(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the route task."""

    async def _work(
        session: AsyncSession, on_progress: ProgressFn, on_event: EventFn
    ) -> WorkflowResult:
        result = await RouteOrchestrator(session).run(
            dry_run=dry_run,
            on_progress=on_progress,
            on_event=on_event,
        )

        total_processed = result.files_routed + result.files_failed
        return WorkflowResult(
            progress_current=total_processed,
            progress_total=total_processed,
            message=f"Route complete: {result.files_routed} files",
            result_summary={
                "files_routed": result.files_routed,
                "files_failed": result.files_failed,
                "dry_run": dry_run,
            },
            complete_summary={"files_routed": result.files_routed, "dry_run": dry_run},
        )

    return await run_task_workflow(
        celery_task_id,
        "route",
        _work,
        progress_total=0,
        dry_run=dry_run,
        running_message="Starting route...",
    )
