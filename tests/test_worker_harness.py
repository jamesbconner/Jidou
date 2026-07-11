"""Tests for jidou.workers._harness.run_task_workflow."""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.task import TaskStatus
from jidou.workers._harness import WorkflowResult, run_task_workflow


def _worker_session_mocks() -> tuple:
    """Return (mock_engine, mock_session, mock_factory) for harness async tests."""
    mock_engine = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)
    return mock_engine, mock_session, mock_factory


def _success_result(**overrides: object) -> WorkflowResult:
    defaults: dict[str, object] = {
        "progress_current": 3,
        "progress_total": 3,
        "message": "Done",
        "result_summary": {"count": 3},
    }
    defaults.update(overrides)
    return WorkflowResult(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_skips_redelivery_for_terminal_task() -> None:
    """A task row already in a terminal status must not be re-run."""
    mock_engine, _session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.FAILED.value)
    work = AsyncMock()

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch("jidou.workers._harness.update_task_status", new_callable=AsyncMock) as mock_update,
    ):
        result = await run_task_workflow("tid-1", "scan", work)

    assert result == "tid-1"
    mock_update.assert_not_called()
    work.assert_not_called()
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_happy_path_completes_and_emits_result_summary_when_no_complete_summary() -> None:
    """A successful work() marks COMPLETED and the WS payload defaults to result_summary."""
    mock_engine, _session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    work = AsyncMock(return_value=_success_result())

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers._harness.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        result = await run_task_workflow("tid-2", "scan", work, progress_total=0, dry_run=True)

    assert result == "tid-2"
    work.assert_awaited_once()
    complete_calls = [c for c in mock_emit.call_args_list if c.args[0]["type"] == "complete"]
    assert len(complete_calls) == 1
    assert complete_calls[0].args[0]["data"]["summary"] == {"count": 3}
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_happy_path_uses_complete_summary_override_for_ws_payload() -> None:
    """When complete_summary is set, the WS "complete" payload uses it instead of result_summary."""
    mock_engine, _session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    work = AsyncMock(
        return_value=_success_result(
            result_summary={"count": 3, "verbose": True},
            complete_summary={"count": 3},
        )
    )

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers._harness.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        await run_task_workflow("tid-3", "scan", work)

    complete_calls = [c for c in mock_emit.call_args_list if c.args[0]["type"] == "complete"]
    assert complete_calls[0].args[0]["data"]["summary"] == {"count": 3}


@pytest.mark.asyncio
async def test_complete_not_emitted_when_concurrently_cancelled() -> None:
    """A non-COMPLETED row back from update_task_status must not emit a "complete" event."""
    mock_engine, _session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    cancelled = MagicMock(status=TaskStatus.CANCELLED.value)
    work = AsyncMock(return_value=_success_result())

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers._harness.update_task_status",
            new_callable=AsyncMock,
            return_value=cancelled,
        ),
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        await run_task_workflow("tid-4", "scan", work)

    complete_calls = [c for c in mock_emit.call_args_list if c.args[0]["type"] == "complete"]
    assert complete_calls == []


@pytest.mark.asyncio
async def test_on_progress_checks_cancellation_updates_status_and_emits() -> None:
    """on_progress checks cancellation, updates RUNNING progress, and emits a WS event, in order."""
    mock_engine, _session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    calls: list[str] = []

    async def fake_check_cancelled(session: object, celery_task_id: str) -> None:
        calls.append("check_cancelled")

    async def fake_update_status(
        session: object, celery_task_id: str, status: object, **kwargs: object
    ) -> object:
        calls.append(f"update:{status}")
        return completed

    async def fake_emit(message: dict) -> None:
        calls.append(f"emit:{message['type']}")

    async def work(session: object, on_progress: object, on_event: object) -> WorkflowResult:
        await on_progress(1, 2, "halfway")  # type: ignore[operator]
        return _success_result()

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers._harness.update_task_status", side_effect=fake_update_status),
        patch("jidou.workers._harness.check_task_cancelled", side_effect=fake_check_cancelled),
        patch("jidou.workers._harness.emit_progress", side_effect=fake_emit),
    ):
        await run_task_workflow("tid-5", "scan", work)

    # Initial RUNNING transition, then on_progress: check_cancelled -> RUNNING
    # update -> progress emit, then the final COMPLETED update -> complete emit.
    assert calls == [
        f"update:{TaskStatus.RUNNING}",
        "check_cancelled",
        f"update:{TaskStatus.RUNNING}",
        "emit:progress",
        f"update:{TaskStatus.COMPLETED}",
        "emit:complete",
    ]


@pytest.mark.asyncio
async def test_on_event_uses_a_separate_session_per_call() -> None:
    """on_event must open a fresh session per call, not reuse the main work session."""
    mock_engine, _session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)

    async def work(session: object, on_progress: object, on_event: object) -> WorkflowResult:
        await on_event("info", "did a thing", {"k": "v"})  # type: ignore[operator]
        return _success_result()

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers._harness.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers._harness.append_task_event", new_callable=AsyncMock) as mock_append,
    ):
        await run_task_workflow("tid-6", "route", work)

    # session_factory: 1 for the outer `async with`, 1 more for the on_event call.
    assert mock_factory.call_count == 2
    mock_append.assert_awaited_once()
    assert mock_append.await_args.args[1] == "tid-6"
    assert mock_append.await_args.args[2] == "info"
    assert mock_append.await_args.args[3] == "did a thing"
    assert mock_append.await_args.args[4] == {"k": "v"}


@pytest.mark.asyncio
async def test_cancelled_error_marks_cancelled_and_emits_and_disposes() -> None:
    """TaskCancelledError from work() marks CANCELLED, emits, and still disposes the engine."""
    from jidou.services.progress import TaskCancelledError

    mock_engine, _session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    work = AsyncMock(side_effect=TaskCancelledError("cancelled"))

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers._harness.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        result = await run_task_workflow("tid-7", "scan", work)

    assert result == "tid-7"
    cancelled_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.CANCELLED]
    assert len(cancelled_calls) == 1
    cancelled_events = [c for c in mock_emit.call_args_list if c.args[0]["type"] == "cancelled"]
    assert len(cancelled_events) == 1
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_exception_appends_error_event_marks_failed_emits_and_reraises() -> None:
    """A generic Exception from work() logs an error event, marks FAILED, emits, and re-raises."""
    mock_engine, _session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    work = AsyncMock(side_effect=RuntimeError("disk full"))

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers._harness.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
        patch("jidou.workers._harness.append_task_event", new_callable=AsyncMock) as mock_append,
        pytest.raises(RuntimeError, match="disk full"),
    ):
        await run_task_workflow("tid-8", "scan", work)

    mock_append.assert_awaited_once()
    assert mock_append.await_args.args[2] == "error"
    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) == 1
    error_events = [c for c in mock_emit.call_args_list if c.args[0]["type"] == "error"]
    assert len(error_events) == 1
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_soft_failure_marks_failed_no_complete_event_and_raises_after_session_closes() -> (
    None
):
    """Non-empty errors mark FAILED, skip "complete", and raise after the session closes."""
    mock_engine, _session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    work = AsyncMock(
        return_value=WorkflowResult(
            progress_current=0,
            progress_total=0,
            message="Import failed: bad config",
            result_summary={"errors": ["bad config"], "dry_run": False},
            errors=["bad config"],
        )
    )

    with (
        patch("jidou.workers._harness.create_async_engine", return_value=mock_engine),
        patch("jidou.workers._harness.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers._harness.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers._harness.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
        pytest.raises(RuntimeError, match=f"^{re.escape('Import failed: bad config')}$"),
    ):
        # The raised exception must carry the caller's own composed message
        # (with its "Import failed: " prefix), not a bare re-join of `errors`.
        await run_task_workflow("tid-9", "rss_import", work)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs["result_summary"] == {"errors": ["bad config"], "dry_run": False}
    complete_events = [c for c in mock_emit.call_args_list if c.args[0]["type"] == "complete"]
    assert complete_events == []
    mock_engine.dispose.assert_called_once()
