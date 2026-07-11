"""Celery task for the one-time SFTP baseline seed operation."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.seed_orchestrator import SeedOrchestrator
from jidou.services.progress import mark_task_timed_out
from jidou.services.sftp_service import SFTPService
from jidou.workers._harness import EventFn, ProgressFn, WorkflowResult, run_task_workflow

logger = logging.getLogger(__name__)


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
    try:
        return asyncio.run(_seed_remote(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _seed_remote(celery_task_id: str, dry_run: bool = False) -> str:
    """Async implementation of the seed task."""

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
        result = await SeedOrchestrator(
            session,
            sftp,
            remote_paths,
        ).run(dry_run=dry_run, on_progress=on_progress)

        summary: dict[str, object] = {
            "paths_scanned": result.paths_scanned,
            "paths_failed": result.paths_failed,
            "files_found": result.files_found,
            "files_seeded": result.files_seeded,
            "files_skipped": result.files_skipped,
            "skipped_by_status": result.skipped_by_status,
            "dry_run": dry_run,
        }

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
        progress_total=0,
        dry_run=dry_run,
        running_message="Listing remote files…",
    )
