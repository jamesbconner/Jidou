"""Pydantic schemas for background task state."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from jidou.models.task import TaskStatus

# Every task_type string a worker actually creates a BackgroundTask row under
# (see the run_task_workflow(celery_task_id, "<type>", ...) call in each
# src/jidou/workers/*.py file). Response-only -- see TaskTrigger below for why
# its own task_type field stays a plain str rather than the narrower subset
# of these that /tasks/trigger actually accepts.
TaskType = Literal[
    "download",
    "scan",
    "match",
    "route",
    "sync",
    "seed",
    "import",
    "db_import",
    "rss_import",
    "rss_publish",
]


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
    task_type: TaskType
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
    """Full task state for GET /tasks/{id} — extends TaskList with celery_task_id and event_log."""

    celery_task_id: str
    event_log: list[dict[str, object]] = []


class TaskTrigger(BaseModel):
    """Request body for triggering a background task.

    task_type stays a plain str (not the narrower Literal subset of TaskType
    that POST /tasks/trigger actually accepts) so the route's own explicit
    400 "Unknown task type" check keeps running -- typing this as a Literal
    would make Pydantic reject bad values at validation time with a generic
    422 before the route body ever runs, changing the endpoint's existing
    error-response contract for no gain (there's no OpenAPI consumer this
    would help; see PR-17 of the sequenced refactoring plan).
    """

    task_type: str
    dry_run: bool = False

    model_config = ConfigDict(validate_assignment=True)
