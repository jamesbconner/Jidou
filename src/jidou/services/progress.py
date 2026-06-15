"""Progress emission helper for Celery tasks."""

import json
import logging

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.models.task import BackgroundTask, TaskStatus

logger = logging.getLogger(__name__)

REDIS_CHANNEL = "task_progress"


async def emit_progress(message: dict[str, object]) -> None:
    """Publish a progress message to Redis PubSub.

    Args:
        message: Dictionary with at least ``celery_task_id`` and ``type``.
            Additional keys are forwarded as the payload.
    """
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.publish(REDIS_CHANNEL, json.dumps(message))
        logger.debug("Emitted progress: %s", message.get("celery_task_id"))
    except Exception as exc:
        logger.warning("Failed to emit progress: %s", exc)
    finally:
        await redis_client.close()


async def update_task_status(
    session: AsyncSession,
    celery_task_id: str,
    status: TaskStatus,
    progress_current: int | None = None,
    progress_total: int | None = None,
    progress_message: str | None = None,
    result_summary: dict[str, object] | None = None,
) -> BackgroundTask | None:
    """Update a BackgroundTask row.

    Args:
        session: Active database session.
        celery_task_id: The Celery task identifier.
        status: New status.
        progress_current: Current step count.
        progress_total: Total step count.
        progress_message: Human-readable message.
        result_summary: Arbitrary result dict.

    Returns:
        The updated BackgroundTask, or None if not found.
    """
    stmt = select(BackgroundTask).where(BackgroundTask.celery_task_id == celery_task_id)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        logger.warning("BackgroundTask not found for celery_task_id=%s", celery_task_id)
        return None

    if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        from datetime import UTC, datetime

        task.completed_at = datetime.now(UTC)

    task.status = status
    if progress_current is not None:
        task.progress_current = progress_current
    if progress_total is not None:
        task.progress_total = progress_total
    if progress_message is not None:
        task.progress_message = progress_message
    if result_summary is not None:
        task.result_summary = result_summary

    await session.flush()
    return task


async def create_task_record(
    session: AsyncSession,
    celery_task_id: str,
    task_type: str,
    progress_total: int = 0,
    dry_run: bool = False,
) -> BackgroundTask:
    """Create a new BackgroundTask row.

    Args:
        session: Active database session.
        celery_task_id: The Celery task identifier.
        task_type: Type label (e.g. ``"download"``, ``"scan"``).
        progress_total: Expected total steps.
        dry_run: Whether this is a dry-run.

    Returns:
        The newly created BackgroundTask.
    """
    task = BackgroundTask(
        celery_task_id=celery_task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        progress_total=progress_total,
        dry_run=dry_run,
    )
    session.add(task)
    await session.flush()
    return task
