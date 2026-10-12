"""API routes for background task management."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.task import ACTIVE_TASK_STATUSES, BackgroundTask, TaskStatus
from jidou.schemas.task_schema import TaskList, TaskRead, TaskTrigger
from jidou.services.task_dispatch import (
    BROKER_UNAVAILABLE_DETAIL,
    TaskDispatchError,
    UnknownTaskTypeError,
    dispatch_registered_task,
)
from jidou.workers.celery_app import celery_app

router = APIRouter(tags=["tasks"])


@router.get("/tasks/count")
async def count_tasks(
    task_type: str | None = Query(default=None),
    active_only: bool = False,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, int]:
    """Return total number of tasks, optionally filtered by task_type or active status."""
    stmt = select(func.count()).select_from(BackgroundTask)
    if task_type is not None:
        stmt = stmt.where(BackgroundTask.task_type == task_type)
    if active_only:
        stmt = stmt.where(BackgroundTask.status.in_(ACTIVE_TASK_STATUSES))
    total = (await db_session.execute(stmt)).scalar_one()
    return {"total": total}


@router.get("/tasks", response_model=list[TaskList])
async def list_tasks(
    limit: int = 20,
    offset: int = 0,
    task_type: str | None = Query(default=None),
    active_only: bool = False,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[BackgroundTask]:
    """List background tasks, optionally filtered by task_type or active status."""
    stmt = select(BackgroundTask).order_by(BackgroundTask.created_at.desc())
    if task_type is not None:
        stmt = stmt.where(BackgroundTask.task_type == task_type)
    if active_only:
        stmt = stmt.where(BackgroundTask.status.in_(ACTIVE_TASK_STATUSES))
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

    if task.status not in ACTIVE_TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Task is not running")

    # Revoke the Celery task
    celery_app.control.revoke(task.celery_task_id, terminate=True)

    from datetime import UTC, datetime

    task.status = TaskStatus.CANCELLED
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


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Delete a background task record.

    Active tasks (pending or running) must be cancelled via
    ``POST /tasks/{task_id}/cancel`` before they can be deleted.
    """
    stmt = select(BackgroundTask).where(BackgroundTask.id == task_id)
    result = await db_session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in ACTIVE_TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Cannot delete an active task; cancel it first")

    await db_session.delete(task)
    await db_session.commit()


@router.post("/tasks/trigger", response_model=TaskRead)
async def trigger_task(
    payload: TaskTrigger,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Trigger a new background task.

    Supported task types: ``download``, ``scan``, ``match``, ``route``, ``sync``,
    ``seed``, ``backfill_show_metadata``.
    """
    try:
        return await dispatch_registered_task(
            db_session, payload.task_type, dry_run=payload.dry_run
        )
    except UnknownTaskTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail=BROKER_UNAVAILABLE_DETAIL) from exc
