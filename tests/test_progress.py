"""Unit tests for progress service helpers."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.task import BackgroundTask, TaskStatus
from jidou.services.progress import (
    TaskCancelledError,
    check_task_cancelled,
    create_task_record,
    update_task_status,
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


# ---------------------------------------------------------------------------
# update_task_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_task_status_terminal_guard_blocks_regression() -> None:
    """No terminal task may transition to a non-terminal or different terminal state."""
    # Terminal → non-terminal must be blocked.
    for terminal_status in (TaskStatus.CANCELLED, TaskStatus.COMPLETED, TaskStatus.FAILED):
        task = MagicMock(spec=BackgroundTask)
        task.status = terminal_status.value

        session = _make_mock_session(task)
        result = await update_task_status(session, "tid", TaskStatus.RUNNING)

        assert result is task
        assert task.status == terminal_status.value
        session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_update_task_status_blocks_cross_terminal_transitions() -> None:
    """CANCELLED must not become COMPLETED or FAILED (race between cancel and worker finish)."""
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.CANCELLED.value

    for new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        session = _make_mock_session(task)
        result = await update_task_status(session, "tid", new_status)

        assert result is task
        assert task.status == TaskStatus.CANCELLED.value
        session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_update_task_status_terminal_allows_self_transition() -> None:
    """Idempotent self-transitions (CANCELLED→CANCELLED) must be allowed for worker cleanup."""
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.CANCELLED.value

    session = _make_mock_session(task)
    result = await update_task_status(session, "tid", TaskStatus.CANCELLED)

    assert result is task
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_task_status_sets_completed_at() -> None:
    """Terminal status transitions must populate completed_at."""
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.RUNNING.value
    task.completed_at = None

    session = _make_mock_session(task)
    before = datetime.now(UTC)
    await update_task_status(session, "tid", TaskStatus.COMPLETED)
    after = datetime.now(UTC)

    assert task.completed_at is not None
    assert before <= task.completed_at <= after


@pytest.mark.asyncio
async def test_update_task_status_repeat_terminal_update_does_not_bump_completed_at() -> None:
    """A repeat/retried terminal update must not overwrite the original completed_at.

    Regression test for #426: the terminal guard explicitly allows an
    idempotent self-transition (e.g. COMPLETED→COMPLETED) for worker cleanup
    paths, but completed_at was being reset unconditionally on every terminal
    update, silently bumping the original completion timestamp forward on a
    duplicate/retried update.
    """
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.COMPLETED.value
    original_completed_at = datetime(2026, 1, 1, tzinfo=UTC)
    task.completed_at = original_completed_at

    session = _make_mock_session(task)
    result = await update_task_status(session, "tid", TaskStatus.COMPLETED)

    assert result is task
    assert task.completed_at == original_completed_at
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_task_status_returns_none_when_not_found() -> None:
    """A missing task must return None without committing."""
    session = _make_mock_session(None)
    result = await update_task_status(session, "missing", TaskStatus.RUNNING)

    assert result is None
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_update_task_status_updates_progress_fields() -> None:
    """update_task_status must apply progress_current/total/message when supplied."""
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.RUNNING.value

    session = _make_mock_session(task)
    await update_task_status(
        session,
        "tid",
        TaskStatus.RUNNING,
        progress_current=3,
        progress_total=10,
        progress_message="Step 3",
        result_summary={"files": 3},
    )

    assert task.progress_current == 3
    assert task.progress_total == 10
    assert task.progress_message == "Step 3"
    assert task.result_summary == {"files": 3}
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_emit_progress_does_not_raise() -> None:
    """emit_progress must publish without raising when Redis is mocked."""
    from jidou.services.progress import emit_progress

    # conftest autouse fixture mocks redis.asyncio.from_url, so this should not
    # attempt a real connection.
    await emit_progress({"celery_task_id": "test-id", "type": "progress"})


@pytest.mark.asyncio
async def test_emit_progress_swallows_redis_error() -> None:
    """emit_progress must log and swallow Redis errors rather than raising."""
    from unittest.mock import patch as _patch

    from jidou.services.progress import emit_progress

    bad_redis = AsyncMock()
    bad_redis.publish = AsyncMock(side_effect=ConnectionRefusedError("redis down"))
    bad_redis.aclose = AsyncMock()

    with _patch("redis.asyncio.from_url", return_value=bad_redis):
        await emit_progress({"celery_task_id": "err-id", "type": "error"})
        # Must not raise; the warning is logged internally.


@pytest.mark.asyncio
async def test_create_task_record_updates_zero_progress_total() -> None:
    """Existing row with progress_total=0 must be updated to the supplied value."""
    existing = MagicMock(spec=BackgroundTask)
    existing.status = TaskStatus.PENDING.value
    existing.progress_total = 0

    session = _make_mock_session(existing)
    await create_task_record(session, "existing-id", "scan", progress_total=50)

    assert existing.progress_total == 50


# ---------------------------------------------------------------------------
# create_task_record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_record_inserts_when_absent() -> None:
    """A new task record must be added and committed."""
    # session.execute returns None from scalar_one_or_none → triggers INSERT path
    session = _make_mock_session(None)

    await create_task_record(session, "new-id", "download", dry_run=True)

    session.add.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_task_record_terminal_task_is_not_modified() -> None:
    """Terminal tasks (CANCELLED/COMPLETED/FAILED) must be returned untouched."""
    for terminal_status in (
        TaskStatus.CANCELLED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    ):
        existing = MagicMock(spec=BackgroundTask)
        existing.status = terminal_status.value
        existing.progress_total = 5
        existing.dry_run = False

        session = _make_mock_session(existing)
        result = await create_task_record(session, "existing-id", "download", dry_run=True)

        assert result.status == terminal_status.value
        session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_task_record_resets_running_on_re_queue() -> None:
    """A RUNNING task found by create_task_record must be reset to PENDING."""
    existing = MagicMock(spec=BackgroundTask)
    existing.status = TaskStatus.RUNNING.value
    existing.progress_total = 10

    session = _make_mock_session(existing)
    await create_task_record(session, "existing-id", "download", dry_run=False)

    assert existing.status == TaskStatus.PENDING.value
    assert existing.progress_current == 0


# ---------------------------------------------------------------------------
# check_task_cancelled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_task_cancelled_raises_when_cancelled() -> None:
    """check_task_cancelled must raise TaskCancelledError for cancelled tasks."""
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.CANCELLED.value

    session = _make_mock_session(task)
    with pytest.raises(TaskCancelledError, match="was cancelled"):
        await check_task_cancelled(session, "tid")


@pytest.mark.asyncio
async def test_check_task_cancelled_passes_for_running() -> None:
    """check_task_cancelled must not raise for running tasks."""
    task = MagicMock(spec=BackgroundTask)
    task.status = TaskStatus.RUNNING.value

    session = _make_mock_session(task)
    await check_task_cancelled(session, "tid")  # must not raise


@pytest.mark.asyncio
async def test_check_task_cancelled_passes_when_missing() -> None:
    """check_task_cancelled must not raise when no task row exists."""
    session = _make_mock_session(None)
    await check_task_cancelled(session, "nonexistent")  # must not raise


@pytest.mark.asyncio
async def test_emit_progress_publish_failure_still_closes_client() -> None:
    """A failed publish is swallowed and the Redis client is still closed exactly once."""
    from unittest.mock import patch

    from jidou.services.progress import emit_progress

    client = AsyncMock()
    client.publish = AsyncMock(side_effect=ConnectionError("down"))
    with patch("redis.asyncio.from_url", return_value=client):
        result = await emit_progress({"celery_task_id": "x", "type": "progress"})

    assert result is None
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_progress_publishes_json_on_task_progress_channel() -> None:
    """Pins the wire contract: channel name, JSON payload, decoded-response client."""
    import json
    from unittest.mock import patch

    from jidou.config import settings
    from jidou.services.progress import emit_progress

    client = AsyncMock()
    message = {"celery_task_id": "x", "type": "progress"}
    with patch("redis.asyncio.from_url", return_value=client) as from_url:
        await emit_progress(message)

    from_url.assert_called_once_with(settings.redis_url, decode_responses=True)
    client.publish.assert_awaited_once_with("task_progress", json.dumps(message))
