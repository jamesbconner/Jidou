"""Beat-triggered wrapper tasks for scheduled sync and RSS import.

Each task acts as a guard layer: it atomically checks the database for an
already-active task of the same type and, if none is found, pre-creates a
pending BackgroundTask row before dispatching the real worker task.  Pre-creating
the row before ``apply_async`` closes the race window where a second beat fire
could see no active task and dispatch a duplicate.
"""

import asyncio
import logging
import uuid

from celery import shared_task
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import BackgroundTask, TaskStatus
from jidou.services.progress import create_task_record

logger = logging.getLogger(__name__)

# Statuses that indicate a task is still occupying the pipeline.
_ACTIVE_STATUSES = {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}


async def _try_claim_task(task_type: str, task_id: str) -> bool:
    """Check for an active task and, if none, insert a pending row.

    Opens its own DB engine so it works outside a FastAPI request context.
    The check and insert are sequential within one session — the same
    trade-off the API route makes.

    Args:
        task_type: Task type string (e.g. ``"sync"``).
        task_id: Pre-generated Celery task ID for the new pending row.

    Returns:
        ``True`` if the task was claimed (pending row inserted) and dispatch
        should proceed.  ``False`` if an active task of the same type was
        already detected.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            count: int = (
                await session.execute(
                    select(func.count()).where(
                        BackgroundTask.task_type == task_type,
                        BackgroundTask.status.in_(_ACTIVE_STATUSES),
                    )
                )
            ).scalar_one()
            if count > 0:
                return False
            await create_task_record(session, task_id, task_type, dry_run=False)
            return True
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
    task_id = str(uuid.uuid4())
    if not await _try_claim_task("sync", task_id):
        logger.info("Scheduled sync skipped: a sync task is already active")
        return "skipped"

    from jidou.workers.sync_tasks import sync_all_task

    sync_all_task.apply_async(args=[False], task_id=task_id)
    logger.info("Scheduled sync dispatched: task_id=%s", task_id)
    return task_id


async def _scheduled_rss_import() -> str:
    task_id = str(uuid.uuid4())
    if not await _try_claim_task("rss_import", task_id):
        logger.info("Scheduled RSS import skipped: an rss_import task is already active")
        return "skipped"

    from jidou.workers.rss_tasks import rss_import_task

    rss_import_task.apply_async(args=[False], task_id=task_id)
    logger.info("Scheduled RSS import dispatched: task_id=%s", task_id)
    return task_id
