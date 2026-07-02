"""Background task model for tracking Celery task progress."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class TaskStatus(StrEnum):
    """Lifecycle states for a background Celery task.

    State machine::

        pending ──► running ──► completed
                       │
                       ├──► failed
                       │
                       └──► cancelled

    Transitions:
        pending   → running     Celery worker picks up the task.
        running   → completed   Task finishes without error.
        running   → failed      An unhandled exception is raised inside the task.
        running   → cancelled   User calls ``DELETE /api/tasks/{id}`` while the task is running.

    Note:
        ``failed`` and ``cancelled`` are terminal states — they do not retry
        automatically.  Trigger a new task via ``POST /api/tasks/trigger`` to
        re-run the operation.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackgroundTask(TimestampMixin, Base):
    """Tracks a long-running Celery task with progress updates."""

    __tablename__ = "background_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    celery_task_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    task_type: Mapped[str] = mapped_column(String(100))  # "download", "scan", "match", "sync"
    status: Mapped[str] = mapped_column(
        String(50),
        default=TaskStatus.PENDING.value,
    )
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[dict[str, object] | None] = mapped_column(JSON)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_log: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )

    def __repr__(self) -> str:
        """Return a concise representation of the BackgroundTask."""
        return (
            f"<BackgroundTask(id={self.id}, type={self.task_type!r}, "
            f"status={self.status}, progress={self.progress_current}/{self.progress_total})>"
        )
