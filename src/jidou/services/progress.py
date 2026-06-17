"""Progress emission helper for Celery tasks."""

import json
import logging

import redis.asyncio as aioredis
from sqlalchemy import insert, select
from sqlalchemy.sql.dml import excluded
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
        await redis_client.aclose()


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
        The updated BackgroundTask, or None if not found or cancelled.
    """
    # Expire to force a fresh read — the cancel endpoint updates the row via
    # a different connection and the identity map would otherwise return stale
    # data still marked "running".
    session.expire_all()

    stmt = select(BackgroundTask).where(BackgroundTask.celery_task_id == celery_task_id)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        logger.warning("BackgroundTask not found for celery_task_id=%s", celery_task_id)
        return None

    # Guard: refuse to update a cancelled task (unless we're reporting failure
    # after the worker itself detected the cancellation).
    if task.status == TaskStatus.CANCELLED.value and status != TaskStatus.CANCELLED:
        logger.info("Refusing to update cancelled task %s to %s", celery_task_id, status)
        return task

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

    await session.commit()
    return task


async def check_task_cancelled(
    session: AsyncSession,
    celery_task_id: str,
) -> None:
    """Raise if the task has been cancelled.

    Call this check at each iteration of a long-running worker loop so the
    worker can stop early when the user cancels.

    Args:
        session: Active database session.
        celery_task_id: Celery task identifier.

    Raises:
        TaskCancelledError: When the task status is ``CANCELLED``.
    """
    # Expire to force a fresh read — the cancel endpoint updates the row via
    # a different connection.
    session.expire_all()

    stmt = select(BackgroundTask).where(BackgroundTask.celery_task_id == celery_task_id)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        return

    if task.status == TaskStatus.CANCELLED.value:
        raise TaskCancelledError(f"Task {celery_task_id} was cancelled")


class TaskCancelledError(Exception):
    """Raised when a running task detects that it has been cancelled."""


async def create_task_record(
    session: AsyncSession,
    celery_task_id: str,
    task_type: str,
    progress_total: int = 0,
    dry_run: bool = False,
) -> BackgroundTask:
    """Create or refresh a BackgroundTask row.

    Uses upsert on ``celery_task_id`` so that calls from both the API trigger
    and the worker are idempotent — the API creates a placeholder immediately,
    and the worker refreshes it when execution begins.

    The upsert preserves the existing ``status`` value so that if the API has
    already advanced the task to ``RUNNING``, the worker's upsert will not
    reset it back to ``PENDING``.

    Args:
        session: Active database session.
        celery_task_id: The Celery task identifier.
        task_type: Type label (e.g. ``"download"``, ``"scan"``).
        progress_total: Expected total steps.
        dry_run: Whether this is a dry-run.

    Returns:
        The BackgroundTask row.
    """
    from sqlalchemy import case

    ins_stmt = insert(BackgroundTask).values(
        celery_task_id=celery_task_id,
        task_type=task_type,
        status=TaskStatus.PENDING.value,
        progress_total=progress_total,
        dry_run=dry_run,
    )
    # On conflict, keep the existing status so that RUNNING is not overwritten
    # by PENDING when the worker upserts after the API already started the task.
    # Also preserve progress_total when the worker has already set a non-zero value.
    stmt = ins_stmt.on_conflict_do_update(  # type: ignore[attr-defined]
        index_elements=["celery_task_id"],
        set_={
            "task_type": task_type,
            "status": BackgroundTask.status,  # keep existing status
            "progress_total": case(
                (BackgroundTask.progress_total > 0, BackgroundTask.progress_total),
                else_=excluded(BackgroundTask.progress_total),
            ),
            "dry_run": dry_run,
        },
    )
    await session.execute(stmt)
    await session.commit()

    # Fetch the row to return
    result = await session.execute(
        select(BackgroundTask).where(BackgroundTask.celery_task_id == celery_task_id)
    )
    return result.scalar_one()
