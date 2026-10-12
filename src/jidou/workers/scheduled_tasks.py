"""Beat-triggered wrapper tasks for scheduled sync and RSS import.

Each task acts as a guard layer: it atomically checks the database for an
already-active task of the same type and, if none is found, pre-creates a
pending BackgroundTask row before dispatching the real worker task.  Pre-creating
the row before ``apply_async`` closes the race window where a second beat fire
could see no active task and dispatch a duplicate.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

from celery import shared_task
from sqlalchemy import delete

from jidou.config import settings
from jidou.database import task_sessionmaker
from jidou.models.task import ACTIVE_TASK_STATUSES, BackgroundTask
from jidou.services.progress import create_task_record
from jidou.services.task_dispatch import get_active_task

logger = logging.getLogger(__name__)


async def _try_claim_task(task_type: str, task_id: str) -> bool:
    """Check for an active task and, if none, insert a pending row.

    Opens its own DB engine so it works outside a FastAPI request context.
    The check and insert are sequential within one session — the same
    trade-off the API route makes.

    Args:
        task_type: Task type string (e.g. ``"sync"``).
        task_id: Pre-generated Celery task ID for the new pending row.

    Returns:
        ``True`` if the task was claimed (pending row inserted) and dispatch
        should proceed.  ``False`` if an active task of the same type was
        already detected.
    """
    async with task_sessionmaker() as session_factory, session_factory() as session:
        if await get_active_task(session, task_type) is not None:
            return False
        await create_task_record(session, task_id, task_type, dry_run=False)
        return True


@shared_task  # type: ignore[untyped-decorator]
def scheduled_sync_task() -> str:
    """Beat-triggered full sync — skips if a sync task is already active.

    Returns:
        ``"skipped"`` when an overlap is detected, otherwise the dispatched
        Celery task ID.
    """
    return asyncio.run(_scheduled_sync())


@shared_task  # type: ignore[untyped-decorator]
def scheduled_rss_import_task() -> str:
    """Beat-triggered RSS import — skips if an rss_import task is already active.

    Returns:
        ``"skipped"`` when an overlap is detected, otherwise the dispatched
        Celery task ID.
    """
    return asyncio.run(_scheduled_rss_import())


async def _dispatch_scheduled(task_type: str, celery_task: Any, task_id: str) -> str:
    """Claim a pending slot then dispatch the Celery task.

    Deletes the pre-created pending row if ``apply_async`` fails, rather than
    marking it FAILED like ``services.task_dispatch.enqueue_task`` does for the
    HTTP-triggered routes. This is a deliberate exception: a beat-triggered
    dispatch has no request/response cycle and no caller waiting to inspect
    the task ID, so a FAILED row here would only be dead cron-failure clutter
    in the task history that no user asked for and nothing will ever surface
    to them. Deleting it also isn't load-bearing for the overlap guard in
    ``_try_claim_task`` either way, since FAILED (like a deleted row) is not
    in ``ACTIVE_TASK_STATUSES`` — this is purely about not polluting the UI.

    Args:
        task_type: Type label used in the overlap guard and log messages.
        celery_task: Celery task object exposing ``apply_async``.
        task_id: Pre-generated task ID (matches the pending row).

    Returns:
        The dispatched task ID.

    Raises:
        Exception: Re-raises any ``apply_async`` failure after cleanup.
    """
    try:
        celery_task.apply_async(args=[False], task_id=task_id)
    except Exception:
        logger.exception(
            "Scheduled %s dispatch failed; removing orphaned pending row task_id=%s",
            task_type,
            task_id,
        )
        await _delete_task_record(task_id)
        raise
    logger.info("Scheduled %s dispatched: task_id=%s", task_type, task_id)
    return task_id


async def _delete_task_record(celery_task_id: str) -> None:
    """Remove a BackgroundTask row by Celery task ID.

    Called only when dispatch fails after the pending row was already committed,
    to avoid permanently blocking the overlap guard.

    Args:
        celery_task_id: The Celery task identifier of the row to remove.
    """
    # Parity with the pre-refactor helper: engine creation happens inside the try
    # (a creation failure is logged, not raised) while disposal runs after it, so
    # a dispose failure still propagates. The ExitStack gives exactly that split.
    async with AsyncExitStack() as stack:
        try:
            session_factory = await stack.enter_async_context(task_sessionmaker())
            async with session_factory() as session:
                await session.execute(
                    delete(BackgroundTask).where(BackgroundTask.celery_task_id == celery_task_id)
                )
                await session.commit()
        except Exception:
            logger.exception(
                "Failed to remove orphaned pending row task_id=%s; manual cleanup may be required",
                celery_task_id,
            )


async def _run_scheduled(
    task_type: str,
    load_task: Callable[[], Any],
    *,
    claim_skipped_message: str,
    skip_reason: Callable[[], str | None] | None = None,
) -> str:
    """Run the shared beat flow: precondition, claim, lazy import, dispatch.

    Args:
        task_type: Type label used for the overlap guard and the pending row.
        load_task: Zero-argument callable that imports and returns the Celery task.
            Called only after the claim succeeds, so the worker module is imported
            lazily (it pulls in heavy dependencies and would be circular at import).
        claim_skipped_message: Info-level log line used when an active task of
            this type is already present.
        skip_reason: Optional precondition check. A returned message is logged as
            a warning and the run is skipped *before* any slot is claimed (for
            example ``RSS_CONFIG_REMOTE_PATH`` being unset).

    Returns:
        ``"skipped"`` when a precondition or the overlap guard stops the run,
        otherwise the dispatched Celery task ID.
    """
    if skip_reason is not None and (reason := skip_reason()):
        logger.warning(reason)
        return "skipped"

    task_id = str(uuid.uuid4())
    if not await _try_claim_task(task_type, task_id):
        logger.info(claim_skipped_message)
        return "skipped"

    return await _dispatch_scheduled(task_type, load_task(), task_id)


def _load_sync_task() -> Any:
    from jidou.workers.sync_tasks import sync_all_task

    return sync_all_task


def _load_rss_import_task() -> Any:
    from jidou.workers.rss_tasks import rss_import_task

    return rss_import_task


def _rss_skip_reason() -> str | None:
    """Return a skip message when the RSS config path is not configured."""
    if not settings.rss_config_remote_path:
        return "Scheduled RSS import skipped: RSS_CONFIG_REMOTE_PATH is not configured"
    return None


async def _scheduled_sync() -> str:
    return await _run_scheduled(
        "sync",
        _load_sync_task,
        claim_skipped_message="Scheduled sync skipped: a sync task is already active",
    )


async def _scheduled_rss_import() -> str:
    return await _run_scheduled(
        "rss_import",
        _load_rss_import_task,
        claim_skipped_message="Scheduled RSS import skipped: an rss_import task is already active",
        skip_reason=_rss_skip_reason,
    )
