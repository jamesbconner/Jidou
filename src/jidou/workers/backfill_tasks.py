"""Celery task for backfilling incomplete TMDB metadata on existing shows."""

import logging

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.orchestrators.show_metadata_backfill_orchestrator import (
    ShowMetadataBackfillOrchestrator,
)
from jidou.services.tmdb import TMDBService
from jidou.workers._harness import (
    EventFn,
    ProgressFn,
    WorkflowResult,
    run_harnessed,
    run_task_workflow,
    summarize,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def backfill_show_metadata_task(self, dry_run: bool = False) -> str:  # type: ignore[no-untyped-def]
    """Backfill missing TMDB metadata (genres, external_ids, etc.) on existing shows.

    Args:
        self: Celery request context for retries.
        dry_run: Identify affected shows without writing changes.

    Returns:
        The celery task ID.
    """
    return run_harnessed(self.request.id, lambda: _backfill(self.request.id, dry_run))


async def _backfill(celery_task_id: str, dry_run: bool = False) -> str:
    """Async implementation of the metadata backfill task."""

    async def _work(
        session: AsyncSession, on_progress: ProgressFn, on_event: EventFn
    ) -> WorkflowResult:
        tmdb_svc = TMDBService()
        result = await ShowMetadataBackfillOrchestrator(session, tmdb_svc).run(
            dry_run=dry_run, on_progress=on_progress
        )

        return WorkflowResult(
            progress_current=result.shows_checked,
            progress_total=result.shows_checked,
            message=f"Backfilled {result.shows_updated} show(s), {result.shows_failed} failed",
            result_summary=summarize(result, dry_run=dry_run),
        )

    return await run_task_workflow(
        celery_task_id,
        "backfill_show_metadata",
        _work,
        progress_total=0,
        dry_run=dry_run,
        running_message="Scanning shows for missing metadata...",
    )
