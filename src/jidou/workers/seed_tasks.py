"""Celery task for the one-time SFTP baseline seed operation."""

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.seed_orchestrator import SeedOrchestrator
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
def seed_remote_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Seed SEEDED records for all pre-existing SFTP files.

    Args:
        self: Celery request context.
        dry_run: Simulate without writing to the database.

    Returns:
        The Celery task ID.
    """
    return run_harnessed(self.request.id, lambda: _seed_remote(self.request.id, dry_run))


async def _seed_remote(celery_task_id: str, dry_run: bool = False) -> str:
    """Async implementation of the seed task."""

    async def _work(
        session: AsyncSession,
        on_progress: ProgressFn,
        on_event: EventFn,
        set_total: SetTotalFn,
    ) -> WorkflowResult:
        sftp = create_sftp_service(settings)

        remote_paths = settings.sftp_remote_paths_list or ["/"]
        result = await SeedOrchestrator(
            session,
            sftp,
            remote_paths,
        ).run(dry_run=dry_run, on_progress=on_progress)

        summary = summarize(result, dry_run=dry_run)

        return WorkflowResult(
            progress_current=result.files_found,
            progress_total=result.files_found,
            message=f"Seed complete: {result.files_seeded} files seeded",
            result_summary=summary,
        )

    return await run_task_workflow(
        celery_task_id,
        "seed",
        _work,
        dry_run=dry_run,
        running_message="Listing remote files…",
    )
