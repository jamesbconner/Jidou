"""Dispatch Celery-backed background tasks behind a pre-created BackgroundTask row.

Centralizes the "pre-generate task id -> create row -> apply_async -> mark FAILED
on broker error" sequence that every task-triggering route used to repeat, and
the registry of task types that ``POST /api/tasks/trigger`` accepts.
"""

import importlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.task import BackgroundTask
from jidou.services import progress

logger = logging.getLogger(__name__)


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

    task = await progress.enqueue_task(session, task_id, task_type, _dispatch, dry_run=dry_run)
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
        active = await progress.get_active_task(session, task_type)
        if active is not None:
            logger.info("Reusing active task type=%s id=%s", task_type, active.celery_task_id)
            return active
    return await enqueue_celery_task(
        session, task_type, registered.ref, args=[dry_run], dry_run=dry_run
    )
