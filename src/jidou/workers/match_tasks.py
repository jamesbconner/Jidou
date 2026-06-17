"""Celery tasks for matching local files to episodes via TMDB."""

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
def match_files_task(  # type: ignore[no-untyped-def]
    self,
    show_id: int,
    dry_run: bool = False,
) -> str:
    """Match local files to episodes via TMDB API.

    Args:
        self: Celery request context for retries.
        show_id: Database ID of the show to match.
        dry_run: Simulate without actually matching.

    Returns:
        The celery task ID.
    """
    return asyncio.run(_match_files(self.request.id, show_id, dry_run))


async def _match_files(
    celery_task_id: str,
    show_id: int,
    dry_run: bool = False,
) -> str:
    """Async implementation of the match task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # Create task record
            await create_task_record(
                session, celery_task_id, "match", progress_total=0, dry_run=dry_run
            )
            await update_task_status(
                session, celery_task_id, TaskStatus.RUNNING, progress_message="Matching files..."
            )

            # TODO: Implement file matching logic
            # For now, simulate progress
            total_files = 8  # Placeholder
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_total=total_files,
                progress_message="Matching files to episodes...",
            )

            for i in range(1, total_files + 1):
                # Check whether the task was cancelled
                await check_task_cancelled(session, celery_task_id)

                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "progress",
                        "data": {
                            "current": i,
                            "total": total_files,
                            "message": f"Matching file {i}/{total_files}",
                        },
                    }
                )

                await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.RUNNING,
                    progress_current=i,
                    progress_message=f"Matched {i}/{total_files} files",
                )

                # Simulate work
                await asyncio.sleep(0.1)

            # Mark complete
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=total_files,
                progress_message="Matching complete",
                result_summary={"files_matched": total_files, "dry_run": dry_run},
            )

            # Notify WebSocket clients that the task finished successfully
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "complete",
                    "data": {
                        "summary": {"files_matched": total_files, "dry_run": dry_run},
                    },
                }
            )

        return celery_task_id

    except TaskCancelledError:
        logger.info("Match task cancelled")
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
        logger.exception("Match task failed")
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
