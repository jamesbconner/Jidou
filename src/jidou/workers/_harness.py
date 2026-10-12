"""Shared harness for Celery worker background-task lifecycle boilerplate."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import task_sessionmaker
from jidou.models.task import TERMINAL_TASK_STATUSES, TaskStatus
from jidou.services.callbacks import OnEvent, OnProgress
from jidou.services.progress import (
    TaskCancelledError,
    append_task_event,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    update_task_status,
)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

logger = logging.getLogger(__name__)

# The callback vocabulary lives in services/callbacks; these aliases keep the
# worker modules' existing names pointing at the single definition.
ProgressFn = OnProgress
EventFn = OnEvent


@dataclass
class WorkflowResult:
    """What a worker's `work` callback returns to run_task_workflow.

    Args:
        progress_current: Final progress numerator for the COMPLETED update.
        progress_total: Final progress denominator for the COMPLETED update.
        message: Human-readable completion (or business-failure) message.
        result_summary: Full summary persisted to BackgroundTask.result_summary.
        complete_summary: Smaller summary broadcast in the "complete" WS event.
            Defaults to result_summary when not given.
        errors: Non-exception ("soft") failure signal -- e.g. RssImportOrchestrator
            returning `.errors` instead of raising. When non-empty, the workflow
            is marked FAILED with result_summary and a RuntimeError is raised
            after the session closes, mirroring an orchestrator-raised failure.
    """

    progress_current: int
    progress_total: int
    message: str
    result_summary: dict[str, object]
    complete_summary: dict[str, object] | None = None
    errors: list[str] = field(default_factory=list)


def summarize(result: "DataclassInstance", *, dry_run: bool) -> dict[str, object]:
    """Build a ``result_summary`` from an orchestrator's result dataclass.

    Kept at module level so ``asdict`` recurses into nested dataclasses (e.g.
    ``PathImportResult.show_results``). The explicit *dry_run* wins over any
    ``dry_run`` field the result itself carries.

    Args:
        result: The orchestrator's result dataclass instance.
        dry_run: Whether the task ran in dry-run mode.

    Returns:
        The result's fields as a dict plus a ``dry_run`` key.
    """
    return {**asdict(result), "dry_run": dry_run}


WorkFn = Callable[[AsyncSession, ProgressFn, EventFn], Awaitable[WorkflowResult]]


async def run_task_workflow(
    celery_task_id: str,
    task_type: str,
    work: WorkFn,
    *,
    progress_total: int = 0,
    dry_run: bool = False,
    running_message: str = "Starting...",
) -> str:
    """Run a background task's full lifecycle: create, RUNNING, work, terminal state.

    Args:
        celery_task_id: The Celery task ID (also the BackgroundTask row's key).
        task_type: Type label (e.g. ``"scan"``, ``"rss_import"``).
        work: Async callable performing the actual orchestrator work. Receives
            ``(session, on_progress, on_event)`` and returns a WorkflowResult.
        progress_total: Initial progress_total for the task record.
        dry_run: Whether this is a dry-run.
        running_message: Message set when the task first transitions to RUNNING.

    Returns:
        The Celery task ID.

    Raises:
        Exception: Whatever *work* raised, after marking the row FAILED.
        RuntimeError: If *work* returns a WorkflowResult with non-empty
            ``errors``, after marking the row FAILED (mirrors the RSS
            import/publish tasks' original behavior of raising after the
            session block closes).
    """
    soft_failure: str | None = None

    async with task_sessionmaker() as session_factory:
        try:
            async with session_factory() as session:
                task = await create_task_record(
                    session,
                    celery_task_id,
                    task_type,
                    progress_total=progress_total,
                    dry_run=dry_run,
                )
                # Redelivered Celery messages must not rerun finished work.
                if task.status in TERMINAL_TASK_STATUSES:
                    logger.info(
                        "Task %s already %s; skipping redelivery", celery_task_id, task.status
                    )
                    return celery_task_id

                await update_task_status(
                    session, celery_task_id, TaskStatus.RUNNING, progress_message=running_message
                )

                async def on_progress(current: int, total: int, message: str) -> None:
                    await check_task_cancelled(session, celery_task_id)
                    await update_task_status(
                        session,
                        celery_task_id,
                        TaskStatus.RUNNING,
                        progress_current=current,
                        progress_total=total,
                        progress_message=message,
                    )
                    await emit_progress(
                        {
                            "celery_task_id": celery_task_id,
                            "type": "progress",
                            "data": {"current": current, "total": total, "message": message},
                        }
                    )

                async def on_event(
                    level: str, msg: str, ctx: dict[str, object] | None = None
                ) -> None:
                    # Separate session per call so the event commit does not flush
                    # pending orchestrator state early (route/sync bugfix ee1cfd5/5ef3c77).
                    async with session_factory() as event_session:
                        await append_task_event(event_session, celery_task_id, level, msg, ctx)

                result = await work(session, on_progress, on_event)

                if result.errors:
                    await update_task_status(
                        session,
                        celery_task_id,
                        TaskStatus.FAILED,
                        progress_message=result.message,
                        result_summary=result.result_summary,
                    )
                    await emit_progress(
                        {
                            "celery_task_id": celery_task_id,
                            "type": "error",
                            "data": {"error": result.message},
                        }
                    )
                    # Use the caller's own message (e.g. "Import failed: ...") for
                    # the raised exception, not a re-derived "; ".join(errors) --
                    # that would drop the prefix callers already composed.
                    soft_failure = result.message
                else:
                    completed = await update_task_status(
                        session,
                        celery_task_id,
                        TaskStatus.COMPLETED,
                        progress_current=result.progress_current,
                        progress_total=result.progress_total,
                        progress_message=result.message,
                        result_summary=result.result_summary,
                    )
                    if completed is not None and completed.status == TaskStatus.COMPLETED:
                        await emit_progress(
                            {
                                "celery_task_id": celery_task_id,
                                "type": "complete",
                                "data": {
                                    "summary": result.complete_summary or result.result_summary
                                },
                            }
                        )

        except TaskCancelledError:
            logger.info("Task %s (%s) cancelled", celery_task_id, task_type)
            async with session_factory() as session:
                await update_task_status(
                    session, celery_task_id, TaskStatus.CANCELLED, progress_message="Task cancelled"
                )
            await emit_progress({"celery_task_id": celery_task_id, "type": "cancelled", "data": {}})
            return celery_task_id
        except Exception as exc:
            logger.exception("Task %s (%s) failed", celery_task_id, task_type)
            error_msg = str(exc) or type(exc).__name__
            async with session_factory() as session:
                await append_task_event(
                    session, celery_task_id, "error", f"Task failed: {error_msg}"
                )
                await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.FAILED,
                    progress_message=f"Failed: {error_msg}",
                )
            await emit_progress(
                {"celery_task_id": celery_task_id, "type": "error", "data": {"error": error_msg}}
            )
            raise

    if soft_failure is not None:
        raise RuntimeError(soft_failure)

    return celery_task_id


async def mark_task_timed_out(celery_task_id: str) -> None:
    """Mark a task FAILED after a Celery soft time limit fires.

    Called from the synchronous task wrapper (outside the main async coroutine)
    so it manages its own engine and session lifecycle.

    Args:
        celery_task_id: The Celery task identifier.
    """
    # Engine create/dispose sit outside the try so their failures propagate, as
    # they did when this function managed the engine itself.
    async with task_sessionmaker() as session_factory:
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


def run_harnessed[T](celery_task_id: str, coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run a task coroutine to completion, marking the row FAILED on a soft time limit.

    Every Celery entrypoint wraps its async implementation in this helper so the
    ``SoftTimeLimitExceeded`` handling exists in one place. A factory (not a
    coroutine object) is taken so no coroutine is created, and left un-awaited,
    if the caller never reaches ``asyncio.run``.

    Args:
        celery_task_id: The Celery task ID (also the BackgroundTask row's key).
        coro_factory: Zero-argument callable returning the coroutine to run.

    Returns:
        Whatever the coroutine returned.

    Raises:
        SoftTimeLimitExceeded: After the row has been marked FAILED.
        Exception: Anything else the coroutine raised, unchanged.
    """
    try:
        return asyncio.run(coro_factory())
    except SoftTimeLimitExceeded:
        # The first event loop is already closed by the time the soft limit
        # propagates here, so marking the row needs a fresh asyncio.run.
        asyncio.run(mark_task_timed_out(celery_task_id))
        raise
