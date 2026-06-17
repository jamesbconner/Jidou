"""API routes for background task management."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.task import BackgroundTask, TaskStatus
from jidou.schemas.task_schema import TaskTrigger
from jidou.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=None)
async def list_tasks(
    limit: int = 20,
    offset: int = 0,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[BackgroundTask]:
    """List background tasks."""
    stmt = (
        select(BackgroundTask)
        .order_by(BackgroundTask.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


@router.get("/tasks/{task_id}", response_model=None)
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


@router.post("/tasks/{task_id}/cancel", response_model=None)
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
            "type": "status",
            "data": {
                "status": TaskStatus.CANCELLED.value,
                "message": "Cancelled by user",
            },
        }
    )

    return task


@router.post("/tasks/trigger", response_model=None)
async def trigger_task(
    payload: TaskTrigger,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Trigger a new background task.

    Supported task types: ``download``, ``scan``, ``match``, ``sync``.
    """
    if payload.task_type not in {"download", "scan", "match", "sync"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task type: {payload.task_type}",
        )

    # Delayed import to avoid circular reference with Celery
    from jidou.workers.download_tasks import download_files_task
    from jidou.workers.match_tasks import match_files_task
    from jidou.workers.scan_tasks import scan_remote_task
    from jidou.workers.sync_tasks import sync_all_task

    # Dispatch based on task type
    if payload.task_type == "download":
        result = download_files_task.delay(payload.show_id, payload.dry_run)
    elif payload.task_type == "scan":
        result = scan_remote_task.delay(payload.dry_run)
    elif payload.task_type == "match":
        result = match_files_task.delay(payload.show_id, payload.dry_run)
    elif payload.task_type == "sync":
        result = sync_all_task.delay(payload.dry_run)
    else:
        raise HTTPException(status_code=400, detail="Task dispatch not implemented")

    # Create a placeholder record; the worker will upsert when it starts.
    from jidou.services.progress import create_task_record

    new_task = await create_task_record(
        db_session,
        result.id,
        payload.task_type,
        dry_run=payload.dry_run,
    )
    await db_session.commit()

    return new_task
