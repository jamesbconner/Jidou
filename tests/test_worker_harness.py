"""Tests for the jidou.workers._harness entrypoint and lifecycle helpers."""

import re
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from jidou.models.task import TaskStatus
from jidou.workers._harness import (
    WorkflowResult,
    _finish,
    mark_task_timed_out,
    run_harnessed,
    run_task_workflow,
    summarize,
)


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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
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
    error_events = [c for c in mock_emit.call_args_list if c.args[0]["type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0].args[0]["data"]["error"] == "Import failed: bad config"
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# run_harnessed
# ---------------------------------------------------------------------------


def test_run_harnessed_returns_value() -> None:
    """The coroutine's result is returned and no timeout marking happens."""

    async def _ok() -> str:
        return "tid-1"

    with patch("jidou.workers._harness.mark_task_timed_out", new_callable=AsyncMock) as mock_mark:
        assert run_harnessed("tid-1", _ok) == "tid-1"

    mock_mark.assert_not_called()


def test_run_harnessed_marks_timeout_and_reraises() -> None:
    """SoftTimeLimitExceeded marks the row timed out (awaited with the id) and propagates."""

    async def _boom() -> str:
        raise SoftTimeLimitExceeded

    with (
        patch("jidou.workers._harness.mark_task_timed_out", new_callable=AsyncMock) as mock_mark,
        pytest.raises(SoftTimeLimitExceeded),
    ):
        run_harnessed("tid-2", _boom)

    mock_mark.assert_awaited_once_with("tid-2")


def test_run_harnessed_other_exceptions_do_not_mark_timeout() -> None:
    """Non-timeout errors propagate untouched; only soft limits trigger the marking."""

    async def _boom() -> str:
        raise ValueError("nope")

    with (
        patch("jidou.workers._harness.mark_task_timed_out", new_callable=AsyncMock) as mock_mark,
        pytest.raises(ValueError, match="nope"),
    ):
        run_harnessed("tid-3", _boom)

    mock_mark.assert_not_called()


# ---------------------------------------------------------------------------
# mark_task_timed_out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_task_timed_out_swallows_inner_exception() -> None:
    """mark_task_timed_out must not propagate exceptions from update_task_status."""
    mock_engine, _session, mock_factory = _worker_session_mocks()

    with (
        patch(
            "jidou.workers._harness.update_task_status",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db exploded"),
        ),
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
    ):
        await mark_task_timed_out("task-err")  # must not raise

    mock_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_task_timed_out_calls_update_and_emit() -> None:
    """mark_task_timed_out must set FAILED status and publish a progress event."""
    mock_engine, _session, mock_factory = _worker_session_mocks()

    with (
        patch("jidou.workers._harness.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
    ):
        await mark_task_timed_out("task-123")

    mock_update.assert_called_once()
    assert mock_update.call_args.args[2] == TaskStatus.FAILED

    mock_emit.assert_called_once()
    emitted = mock_emit.call_args.args[0]
    assert emitted["type"] == "error"
    assert emitted["celery_task_id"] == "task-123"


@pytest.mark.asyncio
async def test_mark_task_timed_out_propagates_engine_creation_failure() -> None:
    """Engine lifecycle errors are not swallowed; only the DB-write work is guarded."""
    with (
        patch("jidou.database.create_async_engine", side_effect=OSError("no engine")),
        pytest.raises(OSError, match="no engine"),
    ):
        await mark_task_timed_out("task-eng")


@pytest.mark.asyncio
async def test_mark_task_timed_out_message_and_ws_error_text() -> None:
    """The persisted progress_message and the WS error text are part of the contract."""
    mock_engine, _session, mock_factory = _worker_session_mocks()

    with (
        patch("jidou.workers._harness.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        patch("jidou.database.async_sessionmaker", return_value=mock_factory),
    ):
        await mark_task_timed_out("task-msg")

    assert mock_update.call_args.kwargs["progress_message"] == "Task exceeded soft time limit"
    assert mock_emit.call_args.args[0]["data"] == {"error": "Soft time limit exceeded"}


@dataclass
class _Inner:
    name: str
    count: int = 0


@dataclass
class _Outer:
    total: int
    items: list[_Inner] = field(default_factory=list)
    dry_run: bool = False


def test_summarize_adds_dry_run_and_recurses() -> None:
    """Fields become dict keys, nested dataclasses recurse, and dry_run is the argument."""
    result = _Outer(total=2, items=[_Inner("a", 1), _Inner("b")])

    assert summarize(result, dry_run=True) == {
        "total": 2,
        "items": [{"name": "a", "count": 1}, {"name": "b", "count": 0}],
        "dry_run": True,
    }


def test_summarize_argument_overrides_result_dry_run_field() -> None:
    """A result's own dry_run field never wins over the explicit argument."""
    assert summarize(_Outer(total=1, dry_run=True), dry_run=False)["dry_run"] is False


# ---------------------------------------------------------------------------
# _finish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finish_soft_failure_returns_message_and_marks_failed() -> None:
    """Non-empty errors mark FAILED with the summary, emit "error", and return the message."""
    session = AsyncMock()
    result = _success_result(
        message="Import failed: bad config",
        result_summary={"errors": ["bad config"]},
        errors=["bad config"],
    )

    with (
        patch("jidou.workers._harness.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        message = await _finish(session, "tid-f1", result)

    assert message == "Import failed: bad config"
    mock_update.assert_awaited_once_with(
        session,
        "tid-f1",
        TaskStatus.FAILED,
        progress_message="Import failed: bad config",
        result_summary={"errors": ["bad config"]},
    )
    mock_emit.assert_awaited_once_with(
        {
            "celery_task_id": "tid-f1",
            "type": "error",
            "data": {"error": "Import failed: bad config"},
        }
    )


@pytest.mark.asyncio
async def test_finish_success_emits_complete_only_when_still_completed() -> None:
    """A row cancelled concurrently (non-COMPLETED status) suppresses the "complete" event."""
    session = AsyncMock()
    cancelled = MagicMock(status=TaskStatus.CANCELLED.value)

    with (
        patch(
            "jidou.workers._harness.update_task_status",
            new_callable=AsyncMock,
            return_value=cancelled,
        ),
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        message = await _finish(session, "tid-f2", _success_result())

    assert message is None
    mock_emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_finish_success_emits_complete_with_summary_when_completed() -> None:
    session = AsyncMock()
    completed = MagicMock(status=TaskStatus.COMPLETED.value)

    with (
        patch(
            "jidou.workers._harness.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers._harness.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        message = await _finish(session, "tid-f3", _success_result(complete_summary={"n": 1}))

    assert message is None
    mock_emit.assert_awaited_once_with(
        {"celery_task_id": "tid-f3", "type": "complete", "data": {"summary": {"n": 1}}}
    )
