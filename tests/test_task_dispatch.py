"""Unit tests for jidou.services.task_dispatch."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.task import BackgroundTask, TaskStatus
from jidou.services.task_dispatch import (
    TASK_REGISTRY,
    CeleryTaskRef,
    TaskDispatchError,
    UnknownTaskTypeError,
    dispatch_registered_task,
    enqueue_celery_task,
    enqueue_task,
    get_active_task,
)


def _make_mock_session(task: BackgroundTask | None) -> AsyncMock:
    """Return a mock AsyncSession that returns *task* from execute()."""

    async def _execute(stmt: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = task
        return result

    session = AsyncMock()
    session.expire_all = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


def test_registry_lists_exactly_the_supported_task_types() -> None:
    assert set(TASK_REGISTRY) == {
        "download",
        "scan",
        "match",
        "route",
        "sync",
        "seed",
        "backfill_show_metadata",
    }


def test_only_route_reuses_an_active_task() -> None:
    assert {k for k, v in TASK_REGISTRY.items() if v.reuse_active} == {"route"}


def test_every_registry_ref_resolves_to_an_object_with_apply_async() -> None:
    assert len(TASK_REGISTRY) >= 7
    for task_type, registered in TASK_REGISTRY.items():
        assert hasattr(registered.ref.resolve(), "apply_async"), task_type


def test_unknown_task_type_raises() -> None:
    with pytest.raises(UnknownTaskTypeError, match="Unknown task type: nope"):
        asyncio.run(dispatch_registered_task(AsyncMock(), "nope", dry_run=False))


def test_route_returns_active_task_without_enqueueing() -> None:
    active = MagicMock()
    with (
        patch(
            "jidou.services.task_dispatch.get_active_task",
            new_callable=AsyncMock,
            return_value=active,
        ),
        patch("jidou.services.task_dispatch.enqueue_task", new_callable=AsyncMock) as enqueue,
    ):
        result = asyncio.run(dispatch_registered_task(AsyncMock(), "route", dry_run=False))
    assert result is active
    enqueue.assert_not_awaited()


def test_enqueue_celery_task_resolves_lazily_and_passes_args() -> None:
    """The task object is looked up at dispatch time, so module-level patches apply."""
    created = MagicMock()
    mock_celery = MagicMock()

    async def fake_create(session, task_id, task_type, **kwargs):  # type: ignore[no-untyped-def]
        return created

    with (
        patch("jidou.services.task_dispatch.create_task_record", side_effect=fake_create),
        patch("jidou.workers.scan_tasks.scan_remote_task", mock_celery),
    ):
        result = asyncio.run(
            enqueue_celery_task(
                AsyncMock(),
                "scan",
                CeleryTaskRef("jidou.workers.scan_tasks", "scan_remote_task"),
                args=[True],
                dry_run=True,
            )
        )
    assert result is created
    call = mock_celery.apply_async.call_args
    assert call.kwargs["args"] == [True]
    assert isinstance(call.kwargs["task_id"], str)


def test_enqueue_celery_task_import_failure_marks_failed() -> None:
    """A broken worker module is a dispatch failure: row FAILED + TaskDispatchError."""

    async def fake_create(session, task_id, task_type, **kwargs):  # type: ignore[no-untyped-def]
        return MagicMock()

    with (
        patch("jidou.services.task_dispatch.create_task_record", side_effect=fake_create),
        patch("jidou.services.task_dispatch.update_task_status", new_callable=AsyncMock) as upd,
        pytest.raises(TaskDispatchError),
    ):
        asyncio.run(
            enqueue_celery_task(
                AsyncMock(),
                "scan",
                CeleryTaskRef("jidou.workers.does_not_exist", "nope"),
                args=[],
                dry_run=False,
            )
        )
    upd.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_active_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_task_returns_task_when_one_is_active() -> None:
    """A PENDING/RUNNING task of the given type is returned."""
    task = MagicMock(spec=BackgroundTask)
    task.task_type = "route"
    task.status = TaskStatus.RUNNING.value

    session = _make_mock_session(task)

    result = await get_active_task(session, "route")

    assert result is task


@pytest.mark.asyncio
async def test_get_active_task_returns_none_when_no_task_is_active() -> None:
    """No PENDING/RUNNING task of the given type returns None."""
    session = _make_mock_session(None)

    result = await get_active_task(session, "route")

    assert result is None


# ---------------------------------------------------------------------------
# enqueue_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_task_happy_path_creates_and_dispatches() -> None:
    """On success, the row is created, dispatch() is called, and the row is returned."""
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.PENDING.value
    task.progress_total = 0

    session = _make_mock_session(task)
    dispatch = MagicMock()

    result = await enqueue_task(session, "task-id", "scan", dispatch, dry_run=True)

    dispatch.assert_called_once()
    assert result is task
    assert task.status == TaskStatus.PENDING.value


@pytest.mark.asyncio
async def test_enqueue_task_broker_failure_marks_failed_and_reraises() -> None:
    """A dispatch() failure marks the row FAILED with a consistent message and re-raises.

    Raises TaskDispatchError specifically (not the original ConnectionError)
    so callers can distinguish a genuine broker failure from a
    create_task_record failure, which is a different (database) problem and
    must not be caught by the same except clause.
    """
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.PENDING.value
    task.progress_total = 0

    session = _make_mock_session(task)
    dispatch = MagicMock(side_effect=ConnectionError("broker unreachable"))

    with pytest.raises(TaskDispatchError, match="broker unreachable"):
        await enqueue_task(session, "task-id", "scan", dispatch)

    dispatch.assert_called_once()
    assert task.status == TaskStatus.FAILED
    assert task.progress_message == "Failed to enqueue task: broker unreachable"
    assert task.completed_at is not None
