"""Dispatch Celery-backed background tasks behind a pre-created BackgroundTask row.

Centralizes the "pre-generate task id -> create row -> apply_async -> mark FAILED
on broker error" sequence that every task-triggering route used to repeat, and
the registry of task types that ``POST /api/tasks/trigger`` accepts.
"""

import importlib
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.task import ACTIVE_TASK_STATUSES, BackgroundTask, TaskStatus
from jidou.services.progress import create_task_record, update_task_status

logger = logging.getLogger(__name__)

# The single 503 ``detail`` every route returns when a broker dispatch fails, so
# clients can match one string regardless of which route triggered the task.
BROKER_UNAVAILABLE_DETAIL: Final = "Task broker unavailable"


class TaskDispatchError(Exception):
    """Raised when enqueue_task's dispatch() callable fails to reach the broker.

    Deliberately distinct from whatever ``create_task_record`` might raise
    (a DB error), so callers can translate only a genuine broker failure to a
    503 without also catching and mislabeling database errors that way.
    """


async def get_active_task(session: AsyncSession, task_type: str) -> BackgroundTask | None:
    """Return the currently PENDING/RUNNING BackgroundTask of this type, if any.

    Used to avoid dispatching a duplicate concurrent run of a task type whose
    orchestrator selects an overlapping pool of DB rows upfront without
    per-row claiming. ``RouteOrchestrator.run()`` is the motivating case: it
    selects all MATCHED/ROUTING files in one batch, then commits each file's
    status transition individually inside the loop -- so two overlapping
    ``route`` dispatches (e.g. RematchModal firing one per fix, in quick
    succession) can each see the same still-MATCHED file in their initial
    SELECT and both route it, producing duplicate copies at the destination.

    Args:
        session: Active database session.
        task_type: Type label (e.g. ``"route"``).

    Returns:
        The active BackgroundTask row, or None if no task of this type is
        currently active.
    """
    stmt = (
        select(BackgroundTask)
        .where(
            BackgroundTask.task_type == task_type, BackgroundTask.status.in_(ACTIVE_TASK_STATUSES)
        )
        .order_by(BackgroundTask.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def enqueue_task(
    session: AsyncSession,
    celery_task_id: str,
    task_type: str,
    dispatch: Callable[[], object],
    *,
    dry_run: bool = False,
) -> BackgroundTask:
    """Create a BackgroundTask row and dispatch it to Celery.

    Pre-generating the task ID and creating the row before dispatch means the
    DB row exists even if the worker starts before this call returns. If the
    broker is unreachable, the row is marked FAILED with a consistent message
    so it does not stay PENDING with no Celery job to ever advance it, and a
    ``TaskDispatchError`` is raised for the caller to translate into its own
    HTTP response. A failure in ``create_task_record`` itself is not caught
    here and propagates as-is — it is a database problem, not a broker one.

    Args:
        session: Active database session.
        celery_task_id: Pre-generated Celery task ID.
        task_type: Type label (e.g. ``"download"``, ``"rss_import"``).
        dispatch: Zero-arg callable that performs the ``apply_async`` call.
        dry_run: Whether this is a dry-run.

    Returns:
        The created BackgroundTask row.

    Raises:
        TaskDispatchError: If *dispatch* raised, after marking the row FAILED.
    """
    new_task = await create_task_record(session, celery_task_id, task_type, dry_run=dry_run)
    try:
        dispatch()
    except Exception as exc:
        logger.exception("Broker dispatch failed for task %s", celery_task_id)
        await update_task_status(
            session,
            celery_task_id,
            TaskStatus.FAILED,
            progress_message=f"Failed to enqueue task: {exc}",
        )
        raise TaskDispatchError(str(exc)) from exc
    return new_task


@dataclass(frozen=True, slots=True)
class CeleryTaskRef:
    """Lazy reference to a Celery task by module path and attribute name.

    Resolution happens inside the dispatch callable, so importing this module
    never imports the Celery app (avoiding circular imports), and an
    ImportError in a worker module goes through ``enqueue_task``'s failure
    handling (row marked FAILED, ``TaskDispatchError`` raised).

    Attributes:
        module: Dotted module path, e.g. ``"jidou.workers.scan_tasks"``.
        attr: Task attribute name within that module.
    """

    module: str
    attr: str

    def resolve(self) -> Any:
        """Import the module and return the task object.

        Returns:
            The Celery task (anything exposing ``apply_async``).
        """
        # Module strings are compile-time constants from TASK_REGISTRY or route
        # literals, never user input.
        return getattr(importlib.import_module(self.module), self.attr)


@dataclass(frozen=True, slots=True)
class RegisteredTask:
    """A task type accepted by ``POST /api/tasks/trigger``.

    Attributes:
        ref: The Celery task to dispatch with ``args=[dry_run]``.
        reuse_active: Return the currently PENDING/RUNNING task of this type
            instead of dispatching a second, overlapping run.
    """

    ref: CeleryTaskRef
    reuse_active: bool = False


TASK_REGISTRY: Final[dict[str, RegisteredTask]] = {
    "download": RegisteredTask(
        CeleryTaskRef("jidou.workers.download_tasks", "download_files_task")
    ),
    "scan": RegisteredTask(CeleryTaskRef("jidou.workers.scan_tasks", "scan_remote_task")),
    "match": RegisteredTask(CeleryTaskRef("jidou.workers.match_tasks", "match_files_task")),
    # RouteOrchestrator selects all MATCHED/ROUTING files upfront and commits each
    # file's transition individually, without per-row claiming, so two overlapping
    # route runs can both route the same file (duplicate copies at the destination).
    # RematchModal triggers a route after every fix, so overlaps are common; reuse
    # the active run, which already covers every currently-MATCHED file.
    "route": RegisteredTask(
        CeleryTaskRef("jidou.workers.route_tasks", "route_files_task"), reuse_active=True
    ),
    "sync": RegisteredTask(CeleryTaskRef("jidou.workers.sync_tasks", "sync_all_task")),
    "seed": RegisteredTask(CeleryTaskRef("jidou.workers.seed_tasks", "seed_remote_task")),
    "backfill_show_metadata": RegisteredTask(
        CeleryTaskRef("jidou.workers.backfill_tasks", "backfill_show_metadata_task")
    ),
}


class UnknownTaskTypeError(ValueError):
    """Raised when a task type is not present in :data:`TASK_REGISTRY`."""


async def enqueue_celery_task(
    session: AsyncSession,
    task_type: str,
    ref: CeleryTaskRef,
    *,
    args: Sequence[Any],
    dry_run: bool,
) -> BackgroundTask:
    """Create the BackgroundTask row, then dispatch *ref* with a pre-generated id.

    Args:
        session: Active async DB session.
        task_type: Type label stored on the row (e.g. ``"rss_import"``).
        ref: The Celery task to dispatch.
        args: Positional arguments for ``apply_async``.
        dry_run: Stored on the row.

    Returns:
        The created BackgroundTask row.

    Raises:
        TaskDispatchError: If resolving or dispatching the task failed; the
            row has already been marked FAILED.
    """
    # Pre-generate the id so the DB row exists before the worker can start.
    task_id = str(uuid.uuid4())
    task_args = list(args)

    def _dispatch() -> None:
        ref.resolve().apply_async(args=task_args, task_id=task_id)

    task = await enqueue_task(session, task_id, task_type, _dispatch, dry_run=dry_run)
    logger.info("Enqueued task type=%s id=%s dry_run=%s", task_type, task_id, dry_run)
    return task


async def dispatch_registered_task(
    session: AsyncSession, task_type: str, *, dry_run: bool
) -> BackgroundTask:
    """Dispatch a task type from :data:`TASK_REGISTRY` with ``args=[dry_run]``.

    Args:
        session: Active async DB session.
        task_type: A key of :data:`TASK_REGISTRY`.
        dry_run: Passed to the task and stored on the row.

    Returns:
        The new BackgroundTask row, or the already-active row for task types
        with ``reuse_active``.

    Raises:
        UnknownTaskTypeError: *task_type* is not registered.
        TaskDispatchError: The broker dispatch failed.
    """
    registered = TASK_REGISTRY.get(task_type)
    if registered is None:
        raise UnknownTaskTypeError(f"Unknown task type: {task_type}")
    if registered.reuse_active:
        active = await get_active_task(session, task_type)
        if active is not None:
            logger.info("Reusing active task type=%s id=%s", task_type, active.celery_task_id)
            return active
    return await enqueue_celery_task(
        session, task_type, registered.ref, args=[dry_run], dry_run=dry_run
    )
