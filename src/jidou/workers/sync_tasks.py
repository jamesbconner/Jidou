"""Celery tasks for running full sync pipelines."""

import asyncio
import logging

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.services.progress import (
    TaskCancelledError,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    update_task_status,
)

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
    return asyncio.run(_sync_all(self.request.id, dry_run))


async def _sync_all(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the full sync task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # Create task record
            await create_task_record(
                session, celery_task_id, "sync", progress_total=3, dry_run=dry_run
            )
            await update_task_status(
                session, celery_task_id, TaskStatus.RUNNING, progress_message="Starting sync..."
            )

            # Phase 1: Scan
            await check_task_cancelled(session, celery_task_id)
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "progress",
                    "data": {
                        "current": 1,
                        "total": 3,
                        "message": "Phase 1/3: Scanning remote directories",
                    },
                }
            )
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_current=1,
                progress_message="Scanning remote directories...",
            )
            await asyncio.sleep(0.1)  # Simulate work

            # Phase 2: Download
            await check_task_cancelled(session, celery_task_id)
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "progress",
                    "data": {
                        "current": 2,
                        "total": 3,
                        "message": "Phase 2/3: Downloading new files",
                    },
                }
            )
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_current=2,
                progress_message="Downloading new files...",
            )
            await asyncio.sleep(0.1)  # Simulate work

            # Phase 3: Match
            await check_task_cancelled(session, celery_task_id)
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "progress",
                    "data": {
                        "current": 3,
                        "total": 3,
                        "message": "Phase 3/3: Matching files to episodes",
                    },
                }
            )
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_current=3,
                progress_message="Matching files to episodes...",
            )
            await asyncio.sleep(0.1)  # Simulate work

            # Mark complete
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=3,
                progress_message="Sync complete",
                result_summary={
                    "phases_completed": 3,
                    "dry_run": dry_run,
                },
            )

            # Notify WebSocket clients that the task finished successfully
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "complete",
                    "data": {
                        "summary": {
                            "phases_completed": 3,
                            "dry_run": dry_run,
                        },
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
                    "type": "error",
                    "data": {"error": "Task cancelled"},
                }
            )
        raise
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
