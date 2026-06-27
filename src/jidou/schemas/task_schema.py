"""Pydantic schemas for background task state."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from jidou.models.task import TaskStatus


def _coerce_task_status(value: object) -> TaskStatus:
    """Convert a raw DB string to TaskStatus, defaulting to PENDING on unknown values."""
    try:
        return TaskStatus(str(value))
    except ValueError:
        return TaskStatus.PENDING


class TaskProgress(BaseModel):
    """Slim progress snapshot for WebSocket messages."""

    model_config = ConfigDict(from_attributes=True)

    celery_task_id: str
    status: TaskStatus
    progress_current: int
    progress_total: int
    progress_message: str | None

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, value: object) -> TaskStatus:
        """Convert raw DB string to TaskStatus enum."""
        return _coerce_task_status(value)


class TaskList(BaseModel):
    """List view with fields sufficient to render outcome details in the UI."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_type: str
    status: TaskStatus
    progress_current: int
    progress_total: int
    progress_message: str | None
    result_summary: dict[str, object] | None
    dry_run: bool
    created_at: datetime
    completed_at: datetime | None

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, value: object) -> TaskStatus:
        """Convert raw DB string to TaskStatus enum."""
        return _coerce_task_status(value)


class TaskRead(TaskList):
    """Full task state for GET /tasks/{id} — extends TaskList with celery_task_id."""

    celery_task_id: str


class TaskTrigger(BaseModel):
    """Request body for triggering a background task."""

    task_type: str
    dry_run: bool = False

    model_config = ConfigDict(validate_assignment=True)
