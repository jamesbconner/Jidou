"""Celery task for periodically refreshing TMDB metadata on existing shows."""

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.orchestrators.show_metadata_refresh_orchestrator import (
    ShowMetadataRefreshOrchestrator,
)
from jidou.services.tmdb import TMDBService
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
def refresh_show_metadata_task(self, dry_run: bool = False) -> str:  # type: ignore[no-untyped-def]
    """Refresh stale TMDB metadata (status, next/last episode, ratings) on a batch of shows.

    The batch is chosen and capped by the show metadata refresh policy
    (``SHOW_METADATA_REFRESH_LIMIT_PER_RUN`` shows per run).

    Args:
        self: Celery request context for retries.
        dry_run: Select and fetch without writing changes.

    Returns:
        The celery task ID.
    """
    return run_harnessed(self.request.id, lambda: _refresh(self.request.id, dry_run))


async def _refresh(celery_task_id: str, dry_run: bool = False) -> str:
    """Async implementation of the show metadata refresh task."""

    async def _work(
        session: AsyncSession,
        on_progress: ProgressFn,
        on_event: EventFn,
        set_total: SetTotalFn,
    ) -> WorkflowResult:
        tmdb_svc = TMDBService()
        result = await ShowMetadataRefreshOrchestrator(session, tmdb_svc).run(
            dry_run=dry_run, on_progress=on_progress
        )

        return WorkflowResult(
            progress_current=result.shows_checked,
            progress_total=result.shows_checked,
            message=f"Refreshed {result.shows_updated} show(s), {result.shows_failed} failed",
            result_summary=summarize(result, dry_run=dry_run),
        )

    return await run_task_workflow(
        celery_task_id,
        "refresh_show_metadata",
        _work,
        dry_run=dry_run,
        running_message="Selecting shows due for a metadata refresh...",
    )
