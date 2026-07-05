"""Celery tasks for routing MATCHED files from staging to their final paths."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.orchestrators.route_orchestrator import RouteOrchestrator
from jidou.services.progress import (
    TaskCancelledError,
    append_task_event,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def route_files_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Move all MATCHED files from staging to their final local paths.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually moving files.

    Returns:
        The celery task ID.
    """
    try:
        return asyncio.run(_route_files(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _route_files(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the route task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            task = await create_task_record(
                session, celery_task_id, "route", progress_total=0, dry_run=dry_run
            )
            if task.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                logger.info("Task %s already %s; skipping redelivery", celery_task_id, task.status)
                return celery_task_id

            await update_task_status(
                session, celery_task_id, TaskStatus.RUNNING, progress_message="Starting route..."
            )

            async def on_progress(current: int, total: int, message: str) -> None:
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

            result = await RouteOrchestrator(session).run(
                dry_run=dry_run,
                on_progress=on_progress,
                on_event=on_event,
            )

            total_processed = result.files_routed + result.files_failed
            completed = await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=total_processed,
                progress_total=total_processed,
                progress_message=f"Route complete: {result.files_routed} files",
                result_summary={
                    "files_routed": result.files_routed,
                    "files_failed": result.files_failed,
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
                                "files_routed": result.files_routed,
                                "dry_run": dry_run,
                            }
                        },
                    }
                )

        return celery_task_id

    except TaskCancelledError:
        logger.info("Route task cancelled")
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
        logger.exception("Route task failed")
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
