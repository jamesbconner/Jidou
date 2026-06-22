"""API routes for background task management."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.task import BackgroundTask, TaskStatus
from jidou.schemas.task_schema import TaskList, TaskRead, TaskTrigger
from jidou.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


@router.get("/tasks/count")
async def count_tasks(
    task_type: str | None = Query(default=None),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, int]:
    """Return total number of tasks, optionally filtered by task_type."""
    stmt = select(func.count()).select_from(BackgroundTask)
    if task_type is not None:
        stmt = stmt.where(BackgroundTask.task_type == task_type)
    total = (await db_session.execute(stmt)).scalar_one()
    return {"total": total}


@router.get("/tasks", response_model=list[TaskList])
async def list_tasks(
    limit: int = 20,
    offset: int = 0,
    task_type: str | None = Query(default=None),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[BackgroundTask]:
    """List background tasks, optionally filtered by task_type."""
    stmt = select(BackgroundTask).order_by(BackgroundTask.created_at.desc())
    if task_type is not None:
        stmt = stmt.where(BackgroundTask.task_type == task_type)
    stmt = stmt.offset(offset).limit(limit)
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


@router.get("/tasks/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Get a single background task by ID."""
    stmt = select(BackgroundTask).where(BackgroundTask.id == task_id)
    result = await db_session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(
    task_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Cancel a running background task."""
    stmt = select(BackgroundTask).where(BackgroundTask.id == task_id)
    result = await db_session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value):
        raise HTTPException(status_code=400, detail="Task is not running")

    # Revoke the Celery task
    celery_app.control.revoke(task.celery_task_id, terminate=True)

    from datetime import UTC, datetime

    task.status = TaskStatus.CANCELLED.value
    task.progress_message = "Cancelled by user"
    task.completed_at = datetime.now(UTC)
    await db_session.commit()

    # Notify WebSocket clients about the cancellation
    from jidou.services.progress import emit_progress

    await emit_progress(
        {
            "celery_task_id": task.celery_task_id,
            "type": "cancelled",
            "data": {},
        }
    )

    return task


@router.post("/tasks/trigger", response_model=TaskRead)
async def trigger_task(
    payload: TaskTrigger,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Trigger a new background task.

    Supported task types: ``download``, ``scan``, ``match``, ``route``, ``sync``.
    """
    if payload.task_type not in {"download", "scan", "match", "route", "sync"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task type: {payload.task_type}",
        )

    # Delayed import to avoid circular reference with Celery
    from jidou.services.progress import create_task_record, update_task_status
    from jidou.workers.download_tasks import download_files_task
    from jidou.workers.match_tasks import match_files_task
    from jidou.workers.route_tasks import route_files_task
    from jidou.workers.scan_tasks import scan_remote_task
    from jidou.workers.sync_tasks import sync_all_task

    # Pre-generate task ID so the DB row exists before the worker can start.
    # Workers call create_task_record too (idempotent upsert), so they will
    # find the row already present and skip the INSERT.
    task_id = str(uuid.uuid4())
    new_task = await create_task_record(
        db_session,
        task_id,
        payload.task_type,
        dry_run=payload.dry_run,
    )

    # Dispatch with the pre-generated ID — eliminates the race condition.
    # If the broker is unreachable, mark the row FAILED immediately so it does
    # not stay PENDING with no Celery job to ever advance it.
    try:
        if payload.task_type == "download":
            download_files_task.apply_async(args=[payload.dry_run], task_id=task_id)
        elif payload.task_type == "scan":
            scan_remote_task.apply_async(args=[payload.dry_run], task_id=task_id)
        elif payload.task_type == "match":
            match_files_task.apply_async(args=[payload.dry_run], task_id=task_id)
        elif payload.task_type == "route":
            route_files_task.apply_async(args=[payload.dry_run], task_id=task_id)
        elif payload.task_type == "sync":
            sync_all_task.apply_async(args=[payload.dry_run], task_id=task_id)
    except Exception as exc:
        logger.exception("Broker dispatch failed for task %s", task_id)
        await update_task_status(
            db_session,
            task_id,
            TaskStatus.FAILED,
            progress_message=f"Broker dispatch failed: {exc}",
        )
        raise HTTPException(status_code=503, detail="Failed to dispatch task to broker") from exc

    return new_task
