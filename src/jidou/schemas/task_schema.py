"""Pydantic schemas for background task state."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from jidou.models.task import TaskStatus


class TaskRead(BaseModel):
    """Full task state for GET /tasks/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    celery_task_id: str
    task_type: str
    status: TaskStatus
    progress_current: int
    progress_total: int
    progress_message: str | None
    result_summary: dict[str, object] | None
    dry_run: bool
    created_at: datetime
    completed_at: datetime | None


class TaskProgress(BaseModel):
    """Slim progress snapshot for WebSocket messages."""

    model_config = ConfigDict(from_attributes=True)

    celery_task_id: str
    status: TaskStatus
    progress_current: int
    progress_total: int
    progress_message: str | None


class TaskList(BaseModel):
    """List view with only essential fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_type: str
    status: TaskStatus
    progress_current: int
    progress_total: int
    progress_message: str | None
    created_at: datetime
    completed_at: datetime | None


class TaskTrigger(BaseModel):
    """Request body for triggering a background task."""

    task_type: str
    show_id: int | None = None
    dry_run: bool = False
