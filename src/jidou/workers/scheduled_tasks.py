"""Beat-triggered wrapper tasks for scheduled sync and RSS import.

Each task acts as a guard layer: it checks the database for an already-active
task of the same type before dispatching the real worker task.  This prevents
overlapping runs when a previous execution is still in progress.
"""

import asyncio
import logging
import uuid

from celery import shared_task
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import BackgroundTask, TaskStatus

logger = logging.getLogger(__name__)

# Statuses that indicate a task is still occupying the pipeline.
_ACTIVE_STATUSES = {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}


async def _is_task_active(task_type: str) -> bool:
    """Return True if any task of *task_type* is currently pending or running.

    Args:
        task_type: The task type string to check (e.g. ``"sync"``).

    Returns:
        True when an overlapping task is detected.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            stmt = select(func.count()).where(
                BackgroundTask.task_type == task_type,
                BackgroundTask.status.in_(_ACTIVE_STATUSES),
            )
            count: int = (await session.execute(stmt)).scalar_one()
            return count > 0
    finally:
        await engine.dispose()


@shared_task  # type: ignore[untyped-decorator]
def scheduled_sync_task() -> str:
    """Beat-triggered full sync — skips if a sync task is already active.

    Returns:
        ``"skipped"`` when an overlap is detected, otherwise the dispatched
        Celery task ID.
    """
    return asyncio.run(_scheduled_sync())


@shared_task  # type: ignore[untyped-decorator]
def scheduled_rss_import_task() -> str:
    """Beat-triggered RSS import — skips if an rss_import task is already active.

    Returns:
        ``"skipped"`` when an overlap is detected, otherwise the dispatched
        Celery task ID.
    """
    return asyncio.run(_scheduled_rss_import())


async def _scheduled_sync() -> str:
    if await _is_task_active("sync"):
        logger.info("Scheduled sync skipped: a sync task is already active")
        return "skipped"

    from jidou.workers.sync_tasks import sync_all_task

    task_id = str(uuid.uuid4())
    sync_all_task.apply_async(args=[False], task_id=task_id)
    logger.info("Scheduled sync dispatched: task_id=%s", task_id)
    return task_id


async def _scheduled_rss_import() -> str:
    if await _is_task_active("rss_import"):
        logger.info("Scheduled RSS import skipped: an rss_import task is already active")
        return "skipped"

    from jidou.workers.rss_tasks import rss_import_task

    task_id = str(uuid.uuid4())
    rss_import_task.apply_async(args=[False], task_id=task_id)
    logger.info("Scheduled RSS import dispatched: task_id=%s", task_id)
    return task_id
