"""Unit tests for jidou.services.task_dispatch."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.progress import TaskDispatchError
from jidou.services.task_dispatch import (
    TASK_REGISTRY,
    CeleryTaskRef,
    UnknownTaskTypeError,
    dispatch_registered_task,
    enqueue_celery_task,
)


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
            "jidou.services.progress.get_active_task",
            new_callable=AsyncMock,
            return_value=active,
        ),
        patch("jidou.services.progress.enqueue_task", new_callable=AsyncMock) as enqueue,
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
        patch("jidou.services.progress.create_task_record", side_effect=fake_create),
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
        patch("jidou.services.progress.create_task_record", side_effect=fake_create),
        patch("jidou.services.progress.update_task_status", new_callable=AsyncMock) as upd,
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
