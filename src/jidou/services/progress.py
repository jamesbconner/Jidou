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

    # Guard: once a task reaches a terminal state it must not regress to a
    # non-terminal state.  A redelivered Celery message could otherwise drive
    # COMPLETED/FAILED back to RUNNING.  Terminal→terminal transitions (e.g.
    # CANCELLED→CANCELLED for worker cleanup) are still allowed.
    _terminal_values = {
        TaskStatus.CANCELLED.value,
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
    }
    if task.status in _terminal_values and status.value not in _terminal_values:
        logger.info("Refusing to update terminal task %s to %s", celery_task_id, status)
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

    Idempotent: the API creates a placeholder immediately, and the worker
    refreshes it when execution begins.  The existing ``status`` is preserved
    so that a task already advanced to ``RUNNING`` is not reset to ``PENDING``.

    Args:
        session: Active database session.
        celery_task_id: The Celery task identifier.
        task_type: Type label (e.g. ``"download"``, ``"scan"``).
        progress_total: Expected total steps.
        dry_run: Whether this is a dry-run.

    Returns:
        The BackgroundTask row.
    """
    stmt = select(BackgroundTask).where(BackgroundTask.celery_task_id == celery_task_id)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        task = BackgroundTask(
            celery_task_id=celery_task_id,
            task_type=task_type,
            status=TaskStatus.PENDING.value,
            progress_total=progress_total,
            dry_run=dry_run,
        )
        session.add(task)
    else:
        # Never re-open a terminal task: the API may have cancelled it before
        # the worker started, or a previous run completed/failed.
        terminal = {
            TaskStatus.CANCELLED.value,
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
        }
        if task.status in terminal:
            return task
        task.task_type = task_type
        # Preserve progress_total when the worker has already set a non-zero value.
        if task.progress_total <= 0:
            task.progress_total = progress_total
        task.dry_run = dry_run
        # A re-queued task (worker hard-killed) arrives with status=RUNNING.
        # Reset so the restarted worker goes through PENDING→RUNNING again.
        if task.status == TaskStatus.RUNNING.value:
            task.status = TaskStatus.PENDING.value
            task.progress_current = 0
            task.progress_message = "Restarting after worker failure"

    await session.commit()
    await session.refresh(task)
    return task


async def mark_task_timed_out(celery_task_id: str) -> None:
    """Mark a task FAILED after a Celery soft time limit fires.

    Called from the synchronous task wrapper (outside the main async coroutine)
    so it manages its own engine and session lifecycle.

    Args:
        celery_task_id: The Celery task identifier.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.FAILED,
                progress_message="Task exceeded soft time limit",
            )
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "error",
                    "data": {"error": "Soft time limit exceeded"},
                }
            )
    except Exception:
        logger.exception("Failed to mark timed-out task %s as FAILED", celery_task_id)
    finally:
        await engine.dispose()
