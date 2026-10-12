"""Celery tasks for running full sync pipelines."""

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.sync_orchestrator import SyncOrchestrator
from jidou.services.llm_service import create_llm_service
from jidou.services.sftp_service import create_sftp_service
from jidou.services.tmdb import TMDBService
from jidou.workers._harness import (
    EventFn,
    ProgressFn,
    WorkflowResult,
    run_harnessed,
    run_task_workflow,
)
from jidou.workers.celery_app import LONG_TASK_LIMITS


@shared_task(bind=True, **LONG_TASK_LIMITS)  # type: ignore[untyped-decorator]
def sync_all_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Run full sync pipeline: scan, download, match.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually syncing.

    Returns:
        The celery task ID.
    """
    return run_harnessed(self.request.id, lambda: _sync_all(self.request.id, dry_run))


async def _sync_all(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the full sync task."""

    async def _work(
        session: AsyncSession, on_progress: ProgressFn, on_event: EventFn
    ) -> WorkflowResult:
        sftp = create_sftp_service(settings)
        tmdb_svc = TMDBService()
        llm = create_llm_service(settings)

        result = await SyncOrchestrator(
            session,
            sftp,
            tmdb_svc,
            llm,
            remote_paths=settings.sftp_remote_paths_list,
            noscan_paths=settings.sftp_noscan_paths_list,
            local_staging_path=settings.local_staging_path,
            local_tv_path=settings.local_tv_path,
            local_anime_path=settings.local_anime_path,
            local_movie_path=settings.local_movie_path,
        ).run(dry_run=dry_run, on_phase=on_progress, on_event=on_event)

        return WorkflowResult(
            progress_current=5,
            progress_total=5,
            message="Sync complete",
            result_summary={
                "episodes_upserted": result.tmdb.episodes_upserted,
                "files_created": result.scan.files_created,
                "files_downloaded": result.download.files_downloaded,
                "files_matched": result.parse.files_matched,
                "files_routed": result.route.files_routed,
                "dry_run": dry_run,
            },
            complete_summary={
                "files_matched": result.parse.files_matched,
                "files_routed": result.route.files_routed,
                "dry_run": dry_run,
            },
        )

    return await run_task_workflow(
        celery_task_id,
        "sync",
        _work,
        progress_total=5,
        dry_run=dry_run,
        running_message="Starting sync...",
    )
