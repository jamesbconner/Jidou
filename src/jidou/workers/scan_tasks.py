"""Celery tasks for scanning remote SFTP for new files."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.services.progress import (
    TaskCancelledError,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def scan_remote_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Scan the remote SFTP directory for new files.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually scanning.

    Returns:
        The celery task ID.
    """
    try:
        return asyncio.run(_scan_remote(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _scan_remote(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the scan task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # Create task record
            await create_task_record(
                session, celery_task_id, "scan", progress_total=0, dry_run=dry_run
            )
            await update_task_status(
                session, celery_task_id, TaskStatus.RUNNING, progress_message="Scanning remote..."
            )

            # TODO: Implement SFTP scan logic
            # For now, simulate progress
            total_dirs = 5  # Placeholder
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_total=total_dirs,
                progress_message="Scanning directories...",
            )

            for i in range(1, total_dirs + 1):
                # Check whether the task was cancelled
                await check_task_cancelled(session, celery_task_id)

                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "progress",
                        "data": {
                            "current": i,
                            "total": total_dirs,
                            "message": f"Scanning directory {i}/{total_dirs}",
                        },
                    }
                )

                await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.RUNNING,
                    progress_current=i,
                    progress_message=f"Scanned {i}/{total_dirs} directories",
                )

                # Simulate work
                await asyncio.sleep(0.1)

            # Mark complete
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=total_dirs,
                progress_message="Scan complete",
                result_summary={"directories_scanned": total_dirs, "dry_run": dry_run},
            )

            # Notify WebSocket clients that the task finished successfully
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "complete",
                    "data": {
                        "summary": {"directories_scanned": total_dirs, "dry_run": dry_run},
                    },
                }
            )

        return celery_task_id

    except TaskCancelledError:
        logger.info("Scan task cancelled")
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
        logger.exception("Scan task failed")
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
