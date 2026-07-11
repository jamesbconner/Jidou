"""Celery tasks for parsing downloaded filenames and matching them to shows."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator
from jidou.services.llm_service import create_llm_service
from jidou.services.progress import mark_task_timed_out
from jidou.workers._harness import EventFn, ProgressFn, WorkflowResult, run_task_workflow

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def match_files_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Parse DOWNLOADED filenames and match them to shows.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually updating the DB.

    Returns:
        The celery task ID.
    """
    try:
        return asyncio.run(_match_files(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _match_files(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the parse/match task."""

    async def _work(
        session: AsyncSession, on_progress: ProgressFn, on_event: EventFn
    ) -> WorkflowResult:
        llm = create_llm_service(settings)

        result = await ParseOrchestrator(
            session,
            llm,
            local_tv_path=settings.local_tv_path,
            local_anime_path=settings.local_anime_path,
            local_movie_path=settings.local_movie_path,
        ).run(dry_run=dry_run, on_progress=on_progress)

        total_processed = result.files_processed
        return WorkflowResult(
            progress_current=total_processed,
            progress_total=total_processed,
            message=f"Parse complete: {result.files_matched} matched",
            result_summary={
                "files_processed": result.files_processed,
                "files_matched": result.files_matched,
                "files_unmatched": result.files_unmatched,
                "files_failed": result.files_failed,
                "dry_run": dry_run,
            },
            complete_summary={"files_matched": result.files_matched, "dry_run": dry_run},
        )

    return await run_task_workflow(
        celery_task_id,
        "match",
        _work,
        progress_total=0,
        dry_run=dry_run,
        running_message="Parsing and matching files...",
    )
