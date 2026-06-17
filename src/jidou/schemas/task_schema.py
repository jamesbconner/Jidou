"""Pydantic schemas for background task state."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from jidou.models.task import TaskStatus


def _coerce_task_status(value: object) -> TaskStatus:
    """Convert a raw DB string to TaskStatus, defaulting to PENDING on unknown values."""
    try:
        return TaskStatus(str(value))
    except ValueError:
        return TaskStatus.PENDING


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

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, value: object) -> TaskStatus:
        """Convert raw DB string to TaskStatus enum."""
        return _coerce_task_status(value)


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

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, value: object) -> TaskStatus:
        """Convert raw DB string to TaskStatus enum."""
        return _coerce_task_status(value)


class TaskTrigger(BaseModel):
    """Request body for triggering a background task."""

    task_type: str
    show_id: int | None = None
    dry_run: bool = False

    model_config = ConfigDict(validate_assignment=True)

    @model_validator(mode="after")
    def _validate_show_id(self) -> "TaskTrigger":
        """Ensure show_id is present when task_type requires it."""
        if self.task_type in ("download", "match") and self.show_id is None:
            raise ValueError(f"show_id is required for task_type '{self.task_type}'")
        return self
