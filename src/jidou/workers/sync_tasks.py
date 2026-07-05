"""Celery tasks for running full sync pipelines."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.orchestrators.sync_orchestrator import SyncOrchestrator
from jidou.services.llm_service import create_llm_service
from jidou.services.progress import (
    TaskCancelledError,
    append_task_event,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)
from jidou.services.sftp_service import SFTPService
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
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
    try:
        return asyncio.run(_sync_all(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _sync_all(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the full sync task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            task = await create_task_record(
                session, celery_task_id, "sync", progress_total=5, dry_run=dry_run
            )
            # Redelivered Celery messages must not rerun finished work.
            if task.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                logger.info("Task %s already %s; skipping redelivery", celery_task_id, task.status)
                return celery_task_id
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
            tmdb_svc = TMDBService()
            llm = create_llm_service(settings)

            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_total=5,
                progress_message="Starting sync...",
            )

            async def on_phase(current: int, total: int, message: str) -> None:
                await check_task_cancelled(session, celery_task_id)
                await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.RUNNING,
                    progress_current=current,
                    progress_total=total,
                    progress_message=message,
                )
                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "progress",
                        "data": {"current": current, "total": total, "message": message},
                    }
                )

            async def on_event(
                level: str, msg: str, ctx: dict[str, object] | None = None
            ) -> None:
                async with session_factory() as event_session:
                    await append_task_event(event_session, celery_task_id, level, msg, ctx)

            result = await SyncOrchestrator(
                session,
                sftp,
                tmdb_svc,
                llm,
                remote_paths=settings.sftp_remote_paths_list,
                local_staging_path=settings.local_staging_path,
                local_tv_path=settings.local_tv_path,
                local_anime_path=settings.local_anime_path,
                local_movie_path=settings.local_movie_path,
            ).run(dry_run=dry_run, on_phase=on_phase, on_event=on_event)

            # Mark complete — gate the WebSocket event on the DB update landing.
            completed = await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=5,
                progress_total=5,
                progress_message="Sync complete",
                result_summary={
                    "episodes_upserted": result.tmdb.episodes_upserted,
                    "files_created": result.scan.files_created,
                    "files_downloaded": result.download.files_downloaded,
                    "files_matched": result.parse.files_matched,
                    "files_routed": result.route.files_routed,
                    "dry_run": dry_run,
                },
            )
            if completed is not None and completed.status == TaskStatus.COMPLETED.value:
                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "complete",
                        "data": {
                            "summary": {
                                "files_matched": result.parse.files_matched,
                                "files_routed": result.route.files_routed,
                                "dry_run": dry_run,
                            }
                        },
                    }
                )

        return celery_task_id

    except TaskCancelledError:
        logger.info("Sync task cancelled")
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.CANCELLED,
                progress_message="Task cancelled",
            )
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "cancelled",
                    "data": {},
                }
            )
        return celery_task_id
    except Exception as exc:
        logger.exception("Sync task failed")
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.FAILED,
                progress_message=str(exc),
            )
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "error",
                    "data": {"error": str(exc)},
                }
            )
        raise
    finally:
        await engine.dispose()
