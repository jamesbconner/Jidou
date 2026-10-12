"""Celery tasks for parsing downloaded filenames and matching them to shows."""

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator
from jidou.services.llm_service import create_llm_service
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
def match_files_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Parse DOWNLOADED/UNMATCHED filenames and match them to shows.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually updating the DB.

    Returns:
        The celery task ID.
    """
    return run_harnessed(self.request.id, lambda: _match_files(self.request.id, dry_run))


async def _match_files(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the parse/match task."""

    async def _work(
        session: AsyncSession,
        on_progress: ProgressFn,
        on_event: EventFn,
        set_total: SetTotalFn,
    ) -> WorkflowResult:
        llm = create_llm_service(settings)

        result = await ParseOrchestrator(
            session,
            llm,
            local_tv_path=settings.local_tv_path,
            local_anime_path=settings.local_anime_path,
            local_movie_path=settings.local_movie_path,
        ).run(dry_run=dry_run, on_progress=on_progress, on_event=on_event)

        total_processed = result.files_processed
        return WorkflowResult(
            progress_current=total_processed,
            progress_total=total_processed,
            message=f"Parse complete: {result.files_matched} matched",
            result_summary=summarize(result, dry_run=dry_run),
            complete_summary={"files_matched": result.files_matched, "dry_run": dry_run},
        )

    return await run_task_workflow(
        celery_task_id,
        "match",
        _work,
        dry_run=dry_run,
        running_message="Parsing and matching files...",
    )
