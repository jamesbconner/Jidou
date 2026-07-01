"""Tests for rss_tasks — RSS import and publish Celery workers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from jidou.models.task import TaskStatus
from jidou.orchestrators.rss_import_orchestrator import RssImportResult
from jidou.orchestrators.rss_publish_orchestrator import RssPublishResult


def _worker_session_mocks() -> tuple:
    """Return (mock_engine, mock_session, mock_factory) for async worker tests."""
    mock_engine = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)
    return mock_engine, mock_session, mock_factory


def _pending() -> MagicMock:
    return MagicMock(status=TaskStatus.PENDING.value)


def _completed() -> MagicMock:
    return MagicMock(status=TaskStatus.COMPLETED.value)


# ---------------------------------------------------------------------------
# rss_import_task (sync wrapper) — soft timeout
# ---------------------------------------------------------------------------


def test_rss_import_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in rss_import_task must call mark_task_timed_out."""
    from jidou.workers.rss_tasks import rss_import_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.rss_tasks._rss_import",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.rss_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        rss_import_task(dry_run=False)

    assert len(mark_calls) == 1


# ---------------------------------------------------------------------------
# _rss_import — redelivery skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_import_skips_redelivery() -> None:
    """_rss_import exits early when task is already terminal."""
    from jidou.workers.rss_tasks import _rss_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.COMPLETED.value)

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch("jidou.workers.rss_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
    ):
        result = await _rss_import("tid-ri1", dry_run=False)

    assert result == "tid-ri1"
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# _rss_import — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_import_success_path() -> None:
    """_rss_import runs RssImportOrchestrator and marks task COMPLETED."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult
    from jidou.workers.rss_tasks import _rss_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    final_task = _completed()
    import_result = RssImportResult(
        feeds_created=2,
        feeds_updated=0,
        subscriptions_created=5,
        subscriptions_updated=1,
        subscriptions_remote_deleted=0,
        shows_linked=3,
        snapshot_id=42,
        errors=[],
        dry_run=False,
    )

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch(
            "jidou.workers.rss_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=final_task,
        ),
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=import_result,
        ),
    ):
        result = await _rss_import("tid-ri2", dry_run=False)

    assert result == "tid-ri2"
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# _rss_import — orchestrator reports errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_import_error_result_marks_failed_and_raises() -> None:
    """When RssImportOrchestrator returns errors, task is FAILED and RuntimeError raised."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult
    from jidou.workers.rss_tasks import _rss_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    error_result = RssImportResult(errors=["config not found"])

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch("jidou.workers.rss_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=error_result,
        ),
        pytest.raises(RuntimeError, match="Import failed"),
    ):
        await _rss_import("tid-ri3", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# _rss_import — on_event closure invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_import_on_event_closure_is_invoked() -> None:
    """The on_event closure body executes when the orchestrator calls it."""
    from jidou.workers.rss_tasks import _rss_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    final_task = _completed()
    import_result = RssImportResult(errors=[])

    class FakeImportOrchestrator:
        def __init__(self, *args: object, on_event: object = None, **kwargs: object) -> None:
            self._on_event = on_event

        async def run(self) -> RssImportResult:
            if callable(self._on_event):
                await self._on_event("info", "Processing feed", None)  # type: ignore[operator]
            return import_result

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch(
            "jidou.workers.rss_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=final_task,
        ),
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock) as mock_event,
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch("jidou.workers.rss_tasks.RssImportOrchestrator", FakeImportOrchestrator),
    ):
        result = await _rss_import("tid-rie1", dry_run=False)

    assert result == "tid-rie1"
    mock_event.assert_called()


# ---------------------------------------------------------------------------
# _rss_import — cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_import_cancellation_handled_gracefully() -> None:
    """TaskCancelledError in _rss_import is caught and swallowed."""
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.rss_tasks import _rss_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch("jidou.workers.rss_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _rss_import("tid-ric1", dry_run=False)

    # TaskCancelledError is swallowed in _rss_import
    assert result == "tid-ric1"


# ---------------------------------------------------------------------------
# _rss_import — completed is None (False branch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_import_skips_emit_when_task_is_none() -> None:
    """No emit_progress 'complete' event when update_task_status returns None."""
    from jidou.workers.rss_tasks import _rss_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    import_result = RssImportResult(errors=[])

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch(
            "jidou.workers.rss_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=None,  # triggers the False branch at line 144
        ),
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock) as mock_emit,
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=import_result,
        ),
    ):
        result = await _rss_import("tid-rin1", dry_run=False)

    assert result == "tid-rin1"
    complete_calls = [c for c in mock_emit.call_args_list if c[0][0].get("type") == "complete"]
    assert len(complete_calls) == 0


# ---------------------------------------------------------------------------
# _rss_import — unexpected exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_import_exception_marks_failed_and_raises() -> None:
    """Unexpected exception in _rss_import marks FAILED and re-raises."""
    from jidou.workers.rss_tasks import _rss_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch("jidou.workers.rss_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("sftp timeout"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _rss_import("tid-ri4", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# rss_publish_task (sync wrapper) — soft timeout
# ---------------------------------------------------------------------------


def test_rss_publish_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in rss_publish_task must call mark_task_timed_out."""
    from jidou.workers.rss_tasks import rss_publish_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.rss_tasks._rss_publish",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.rss_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        rss_publish_task(dry_run=False)

    assert len(mark_calls) == 1


# ---------------------------------------------------------------------------
# _rss_publish — redelivery skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_publish_skips_redelivery() -> None:
    """_rss_publish exits early when task is already terminal."""
    from jidou.workers.rss_tasks import _rss_publish

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.FAILED.value)

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch("jidou.workers.rss_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
    ):
        result = await _rss_publish("tid-rp1", dry_run=False)

    assert result == "tid-rp1"
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# _rss_publish — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_publish_success_path() -> None:
    """_rss_publish runs RssPublishOrchestrator and marks task COMPLETED."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishResult
    from jidou.workers.rss_tasks import _rss_publish

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    final_task = _completed()
    publish_result = RssPublishResult(
        feeds_published=3,
        subscriptions_published=10,
        new_keys_assigned=2,
        snapshot_id=7,
        backup_path="/tmp/backup.xml",
        errors=[],
    )

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch(
            "jidou.workers.rss_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=final_task,
        ),
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssPublishOrchestrator.run",
            new_callable=AsyncMock,
            return_value=publish_result,
        ),
    ):
        result = await _rss_publish("tid-rp2", dry_run=False)

    assert result == "tid-rp2"
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# _rss_publish — orchestrator reports errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_publish_error_result_marks_failed_and_raises() -> None:
    """When RssPublishOrchestrator returns errors, task FAILED and RuntimeError raised."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishResult
    from jidou.workers.rss_tasks import _rss_publish

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    error_result = RssPublishResult(errors=["upload failed"])

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch("jidou.workers.rss_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssPublishOrchestrator.run",
            new_callable=AsyncMock,
            return_value=error_result,
        ),
        pytest.raises(RuntimeError, match="Publish failed"),
    ):
        await _rss_publish("tid-rp3", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# _rss_publish — on_event closure invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_publish_on_event_closure_is_invoked() -> None:
    """The on_event closure body executes when the orchestrator calls it."""
    from jidou.workers.rss_tasks import _rss_publish

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    final_task = _completed()
    publish_result = RssPublishResult(errors=[])

    class FakePublishOrchestrator:
        def __init__(self, *args: object, on_event: object = None, **kwargs: object) -> None:
            self._on_event = on_event

        async def run(self) -> RssPublishResult:
            if callable(self._on_event):
                await self._on_event("info", "Publishing feed", None)  # type: ignore[operator]
            return publish_result

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch(
            "jidou.workers.rss_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=final_task,
        ),
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock) as mock_event,
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch("jidou.workers.rss_tasks.RssPublishOrchestrator", FakePublishOrchestrator),
    ):
        result = await _rss_publish("tid-rpe1", dry_run=False)

    assert result == "tid-rpe1"
    mock_event.assert_called()


# ---------------------------------------------------------------------------
# _rss_publish — cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_publish_cancellation_handled_gracefully() -> None:
    """TaskCancelledError in _rss_publish is caught and swallowed."""
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.rss_tasks import _rss_publish

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch("jidou.workers.rss_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssPublishOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _rss_publish("tid-rpc1", dry_run=False)

    # TaskCancelledError is swallowed in _rss_publish
    assert result == "tid-rpc1"


# ---------------------------------------------------------------------------
# _rss_publish — completed is None (False branch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_publish_skips_emit_when_task_is_none() -> None:
    """No emit_progress 'complete' event when update_task_status returns None."""
    from jidou.workers.rss_tasks import _rss_publish

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    publish_result = RssPublishResult(errors=[])

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch(
            "jidou.workers.rss_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=None,  # triggers the False branch at line 281
        ),
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock) as mock_emit,
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssPublishOrchestrator.run",
            new_callable=AsyncMock,
            return_value=publish_result,
        ),
    ):
        result = await _rss_publish("tid-rpn1", dry_run=False)

    assert result == "tid-rpn1"
    complete_calls = [c for c in mock_emit.call_args_list if c[0][0].get("type") == "complete"]
    assert len(complete_calls) == 0


# ---------------------------------------------------------------------------
# _rss_publish — unexpected exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_publish_exception_marks_failed_and_raises() -> None:
    """Unexpected exception in _rss_publish marks FAILED and re-raises."""
    from jidou.workers.rss_tasks import _rss_publish

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.rss_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending(),
        ),
        patch("jidou.workers.rss_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.rss_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssPublishOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=ConnectionError("remote down"),
        ),
        pytest.raises(ConnectionError),
    ):
        await _rss_publish("tid-rp4", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1
