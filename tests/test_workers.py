"""Tests for Celery worker and background tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from jidou.workers.celery_app import celery_app
from jidou.workers.tasks import fetch_trending_shows_task


class TestCeleryApp:
    """Test Celery application configuration."""

    def test_celery_app_configured(self) -> None:
        """Test that Celery app is created with correct broker."""
        assert celery_app is not None
        config = celery_app.conf
        assert config.broker_url.startswith("redis://")

    def test_celery_autodiscover(self) -> None:
        """Test that tasks are auto-discovered."""
        registered = celery_app.tasks
        assert any("fetch_trending" in name for name in registered)


def test_fetch_trending_shows_task() -> None:
    """Test that the trending task calls TMDB and returns count."""
    # fetch_trending_shows_task is a sync Celery task that uses asyncio.run()
    # internally, so we patch the async helper it calls.
    with patch(
        "jidou.workers.tasks._fetch_trending",
        new_callable=AsyncMock,
        return_value=42,
    ) as mock_fetch:
        result = fetch_trending_shows_task()

        # asyncio.run() wraps the async call; verify the helper was invoked
        mock_fetch.assert_called_once()
        assert result == 42


def test_download_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in download_files_task must call mark_task_timed_out."""
    from jidou.workers.download_tasks import download_files_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.download_tasks._download_files",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.download_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        # Celery bind=True tasks auto-inject self; do not pass mock as first arg.
        download_files_task(dry_run=False)

    assert len(mark_calls) == 1, "mark_task_timed_out must be called exactly once"


@pytest.mark.asyncio
async def test_download_files_skips_redelivery_for_terminal_task() -> None:
    """_download_files must exit early without re-running when the task row is terminal."""
    from jidou.models.task import BackgroundTask, TaskStatus
    from jidou.workers.download_tasks import _download_files

    terminal_task = MagicMock(spec=BackgroundTask)
    terminal_task.status = TaskStatus.COMPLETED.value
    terminal_task.celery_task_id = "redelivered-123"

    mock_engine = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = False
    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine),
        patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.download_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal_task,
        ),
        patch(
            "jidou.workers.download_tasks.update_task_status",
            new_callable=AsyncMock,
        ) as mock_update,
    ):
        result = await _download_files("redelivered-123", dry_run=False)

    mock_update.assert_not_called()
    assert result == "redelivered-123"


def test_scan_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in scan_remote_task must call mark_task_timed_out."""
    from jidou.workers.scan_tasks import scan_remote_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.scan_tasks._scan_remote",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.scan_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        scan_remote_task(dry_run=False)

    assert len(mark_calls) == 1, "mark_task_timed_out must be called exactly once"


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _worker_session_mocks() -> tuple:
    """Return (mock_engine, mock_session, mock_factory) for worker async tests."""
    mock_engine = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)
    return mock_engine, mock_session, mock_factory


# ---------------------------------------------------------------------------
# route_tasks
# ---------------------------------------------------------------------------


def test_route_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in route_files_task must call mark_task_timed_out."""
    from jidou.workers.route_tasks import route_files_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.route_tasks._route_files",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.route_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        route_files_task(dry_run=False)

    assert len(mark_calls) == 1


@pytest.mark.asyncio
async def test_route_files_skips_redelivery() -> None:
    """_route_files exits early when task is already terminal."""
    from jidou.models.task import TaskStatus
    from jidou.workers.route_tasks import _route_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.FAILED.value)

    with (
        patch("jidou.workers.route_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.route_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.route_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch(
            "jidou.workers.route_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
    ):
        result = await _route_files("tid-r1", dry_run=False)

    assert result == "tid-r1"
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_route_files_success_path() -> None:
    """_route_files runs the orchestrator and marks task COMPLETED."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.route_orchestrator import RouteResult
    from jidou.workers.route_tasks import _route_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    route_result = RouteResult(files_routed=3, files_failed=0, dry_run=False)

    with (
        patch("jidou.workers.route_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.route_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.route_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.route_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.route_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.route_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch(
            "jidou.workers.route_tasks.RouteOrchestrator.run",
            new_callable=AsyncMock,
            return_value=route_result,
        ),
    ):
        result = await _route_files("tid-r2", dry_run=False)

    assert result == "tid-r2"
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_route_files_cancellation_marks_cancelled() -> None:
    """TaskCancelledError in _route_files updates status to CANCELLED."""
    from jidou.models.task import TaskStatus
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.route_tasks import _route_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.route_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.route_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.route_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.route_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.route_tasks.emit_progress", new_callable=AsyncMock),
        patch(
            "jidou.workers.route_tasks.RouteOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _route_files("tid-rc1", dry_run=False)

    assert result == "tid-rc1"
    cancelled_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.CANCELLED]
    assert len(cancelled_calls) >= 1


@pytest.mark.asyncio
async def test_route_files_exception_marks_failed() -> None:
    """Unexpected exception in _route_files marks task FAILED and re-raises."""
    from jidou.models.task import TaskStatus
    from jidou.workers.route_tasks import _route_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.route_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.route_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.route_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.route_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.route_tasks.emit_progress", new_callable=AsyncMock),
        patch(
            "jidou.workers.route_tasks.RouteOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("disk full"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _route_files("tid-r3", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# match_tasks
# ---------------------------------------------------------------------------


def test_match_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in match_files_task must call mark_task_timed_out."""
    from jidou.workers.match_tasks import match_files_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.match_tasks._match_files",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.match_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        match_files_task(dry_run=False)

    assert len(mark_calls) == 1


@pytest.mark.asyncio
async def test_match_files_skips_redelivery() -> None:
    """_match_files exits early when task is already terminal."""
    from jidou.models.task import TaskStatus
    from jidou.workers.match_tasks import _match_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.CANCELLED.value)

    with (
        patch("jidou.workers.match_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.match_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.match_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch(
            "jidou.workers.match_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
    ):
        result = await _match_files("tid-m1", dry_run=False)

    assert result == "tid-m1"
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_match_files_cancellation_marks_cancelled() -> None:
    """TaskCancelledError in _match_files updates status to CANCELLED."""
    from jidou.models.task import TaskStatus
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.match_tasks import _match_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.match_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.match_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.match_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.match_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.match_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.match_tasks.create_llm_service"),
        patch(
            "jidou.workers.match_tasks.ParseOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _match_files("tid-mc1", dry_run=False)

    assert result == "tid-mc1"
    cancelled_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.CANCELLED]
    assert len(cancelled_calls) >= 1


@pytest.mark.asyncio
async def test_match_files_exception_marks_failed() -> None:
    """Unexpected exception in _match_files marks task FAILED and re-raises."""
    from jidou.models.task import TaskStatus
    from jidou.workers.match_tasks import _match_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.match_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.match_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.match_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.match_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.match_tasks.emit_progress", new_callable=AsyncMock),
        patch(
            "jidou.workers.match_tasks.ParseOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("llm failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _match_files("tid-m2", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# sync_tasks
# ---------------------------------------------------------------------------


def test_sync_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in sync_all_task must call mark_task_timed_out."""
    from jidou.workers.sync_tasks import sync_all_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.sync_tasks._sync_all",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.sync_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        sync_all_task(dry_run=False)

    assert len(mark_calls) == 1


@pytest.mark.asyncio
async def test_sync_all_skips_redelivery() -> None:
    """_sync_all exits early when task is already terminal."""
    from jidou.models.task import TaskStatus
    from jidou.workers.sync_tasks import _sync_all

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.COMPLETED.value)

    with (
        patch("jidou.workers.sync_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.sync_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.sync_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch("jidou.workers.sync_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
    ):
        result = await _sync_all("tid-s1", dry_run=False)

    assert result == "tid-s1"
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_sync_all_cancellation_marks_cancelled() -> None:
    """TaskCancelledError in _sync_all updates status to CANCELLED."""
    from jidou.models.task import TaskStatus
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.sync_tasks import _sync_all

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.sync_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.sync_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.sync_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.sync_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.sync_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.sync_tasks.SFTPService"),
        patch("jidou.workers.sync_tasks.TMDBService"),
        patch("jidou.workers.sync_tasks.create_llm_service"),
        patch(
            "jidou.workers.sync_tasks.SyncOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _sync_all("tid-sc1", dry_run=False)

    assert result == "tid-sc1"
    cancelled_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.CANCELLED]
    assert len(cancelled_calls) >= 1


@pytest.mark.asyncio
async def test_sync_all_exception_marks_failed() -> None:
    """Unexpected exception in _sync_all marks task FAILED and re-raises."""
    from jidou.models.task import TaskStatus
    from jidou.workers.sync_tasks import _sync_all

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.sync_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.sync_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.sync_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.sync_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.sync_tasks.emit_progress", new_callable=AsyncMock),
        patch(
            "jidou.workers.sync_tasks.SyncOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _sync_all("tid-s2", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# import_tasks (path_import_task)
# ---------------------------------------------------------------------------


def test_path_import_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in path_import_task must call mark_task_timed_out."""
    from jidou.workers.import_tasks import path_import_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.import_tasks._path_import",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.import_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        path_import_task(file_content="/data/show/S01E01.mkv\n")

    assert len(mark_calls) == 1


@pytest.mark.asyncio
async def test_path_import_skips_redelivery() -> None:
    """_path_import exits early when task is already terminal."""
    from jidou.models.task import TaskStatus
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.FAILED.value)

    with (
        patch("jidou.workers.import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch(
            "jidou.workers.import_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
    ):
        result = await _path_import("tid-i1", "/data/show/ep.mkv\n", "anime", False)

    assert result == "tid-i1"
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# route_tasks — _route_files on_progress invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_files_on_progress_is_invoked() -> None:
    """The on_progress closure body executes when the orchestrator calls it."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.route_orchestrator import RouteResult
    from jidou.workers.route_tasks import _route_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    route_result = RouteResult(files_routed=1, files_failed=0, dry_run=False)

    async def fake_run(*args: object, **kwargs: object) -> RouteResult:
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            await on_progress(1, 1, "routing file")  # type: ignore[operator]
        return route_result

    with (
        patch("jidou.workers.route_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.route_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.route_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.route_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.route_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.route_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.route_tasks.RouteOrchestrator.run", side_effect=fake_run),
    ):
        result = await _route_files("tid-rop1", dry_run=False)

    assert result == "tid-rop1"


# ---------------------------------------------------------------------------
# scan_tasks — _scan_remote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_remote_on_progress_is_invoked() -> None:
    """The on_progress closure body in _scan_remote executes when the orchestrator calls it."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.scan_orchestrator import ScanResult
    from jidou.workers.scan_tasks import _scan_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    scan_result = ScanResult(paths_scanned=1, files_found=1, files_created=1, files_skipped=0)

    async def fake_run(*args: object, **kwargs: object) -> ScanResult:
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            await on_progress(1, 1, "scanning")  # type: ignore[operator]
        return scan_result

    with (
        patch("jidou.workers.scan_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.scan_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.scan_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.scan_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.scan_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.scan_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.scan_tasks.SFTPService"),
        patch("jidou.workers.scan_tasks.ScanOrchestrator.run", side_effect=fake_run),
    ):
        result = await _scan_remote("tid-sop1", dry_run=False)

    assert result == "tid-sop1"


@pytest.mark.asyncio
async def test_scan_remote_skips_redelivery() -> None:
    """_scan_remote exits early when task is already terminal."""
    from jidou.models.task import TaskStatus
    from jidou.workers.scan_tasks import _scan_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.COMPLETED.value)

    with (
        patch("jidou.workers.scan_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.scan_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.scan_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch("jidou.workers.scan_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
    ):
        result = await _scan_remote("tid-sc1", dry_run=False)

    assert result == "tid-sc1"
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_scan_remote_success_path() -> None:
    """_scan_remote runs ScanOrchestrator and marks task COMPLETED."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.scan_orchestrator import ScanResult
    from jidou.workers.scan_tasks import _scan_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    scan_result = ScanResult(paths_scanned=5, files_found=10, files_created=3, files_skipped=7)

    with (
        patch("jidou.workers.scan_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.scan_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.scan_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.scan_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.scan_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.scan_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.scan_tasks.SFTPService"),
        patch(
            "jidou.workers.scan_tasks.ScanOrchestrator.run",
            new_callable=AsyncMock,
            return_value=scan_result,
        ),
    ):
        result = await _scan_remote("tid-sc2", dry_run=False)

    assert result == "tid-sc2"
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_scan_remote_cancellation_marks_cancelled() -> None:
    """TaskCancelledError in _scan_remote updates status to CANCELLED."""
    from jidou.models.task import TaskStatus
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.scan_tasks import _scan_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.scan_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.scan_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.scan_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.scan_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.scan_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.scan_tasks.SFTPService"),
        patch(
            "jidou.workers.scan_tasks.ScanOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _scan_remote("tid-sc3", dry_run=False)

    assert result == "tid-sc3"
    cancelled_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.CANCELLED]
    assert len(cancelled_calls) >= 1


@pytest.mark.asyncio
async def test_scan_remote_exception_marks_failed() -> None:
    """Exception in _scan_remote marks task FAILED and re-raises."""
    from jidou.models.task import TaskStatus
    from jidou.workers.scan_tasks import _scan_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.scan_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.scan_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.scan_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.scan_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.scan_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.scan_tasks.SFTPService"),
        patch(
            "jidou.workers.scan_tasks.ScanOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("sftp error"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _scan_remote("tid-sc4", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# download_tasks — _download_files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_files_on_progress_is_invoked() -> None:
    """The on_progress closure body in _download_files executes when the orchestrator calls it."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.download_orchestrator import DownloadResult
    from jidou.workers.download_tasks import _download_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    dl_result = DownloadResult(
        files_downloaded=1, bytes_downloaded=512, files_failed=0, dry_run=False
    )

    async def fake_run(*args: object, **kwargs: object) -> DownloadResult:
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            await on_progress(1, 1, "downloading")  # type: ignore[operator]
        return dl_result

    with (
        patch("jidou.workers.download_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.download_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.download_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.download_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.download_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.download_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.download_tasks.SFTPService"),
        patch("jidou.workers.download_tasks.DownloadOrchestrator.run", side_effect=fake_run),
    ):
        result = await _download_files("tid-dop1", dry_run=False)

    assert result == "tid-dop1"


@pytest.mark.asyncio
async def test_download_files_success_path() -> None:
    """_download_files runs DownloadOrchestrator and marks task COMPLETED."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.download_orchestrator import DownloadResult
    from jidou.workers.download_tasks import _download_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    dl_result = DownloadResult(
        files_downloaded=4, bytes_downloaded=1024, files_failed=0, dry_run=False
    )

    with (
        patch("jidou.workers.download_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.download_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.download_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.download_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.download_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.download_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.download_tasks.SFTPService"),
        patch(
            "jidou.workers.download_tasks.DownloadOrchestrator.run",
            new_callable=AsyncMock,
            return_value=dl_result,
        ),
    ):
        result = await _download_files("tid-dl1", dry_run=False)

    assert result == "tid-dl1"
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_download_files_cancellation_marks_cancelled() -> None:
    """TaskCancelledError in _download_files updates status to CANCELLED."""
    from jidou.models.task import TaskStatus
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.download_tasks import _download_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.download_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.download_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.download_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.download_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.download_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.download_tasks.SFTPService"),
        patch(
            "jidou.workers.download_tasks.DownloadOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _download_files("tid-dl2", dry_run=False)

    assert result == "tid-dl2"
    cancelled_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.CANCELLED]
    assert len(cancelled_calls) >= 1


@pytest.mark.asyncio
async def test_download_files_exception_marks_failed() -> None:
    """Exception in _download_files marks task FAILED and re-raises."""
    from jidou.models.task import TaskStatus
    from jidou.workers.download_tasks import _download_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.download_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.download_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.download_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.download_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.download_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.download_tasks.SFTPService"),
        patch(
            "jidou.workers.download_tasks.DownloadOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("sftp disconnected"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _download_files("tid-dl3", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# match_tasks — _match_files (success path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_files_on_progress_is_invoked() -> None:
    """The on_progress closure body in _match_files executes when the orchestrator calls it."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.parse_orchestrator import ParseResult
    from jidou.workers.match_tasks import _match_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    parse_result = ParseResult(
        files_processed=1, files_matched=1, files_unmatched=0, files_failed=0, dry_run=False
    )

    async def fake_run(*args: object, **kwargs: object) -> ParseResult:
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            await on_progress(1, 1, "matching")  # type: ignore[operator]
        return parse_result

    with (
        patch("jidou.workers.match_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.match_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.match_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.match_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.match_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.match_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.match_tasks.create_llm_service"),
        patch("jidou.workers.match_tasks.ParseOrchestrator.run", side_effect=fake_run),
    ):
        result = await _match_files("tid-mop1", dry_run=False)

    assert result == "tid-mop1"


@pytest.mark.asyncio
async def test_match_files_success_path() -> None:
    """_match_files runs ParseOrchestrator and marks task COMPLETED."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.parse_orchestrator import ParseResult
    from jidou.workers.match_tasks import _match_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    parse_result = ParseResult(
        files_processed=5, files_matched=4, files_unmatched=1, files_failed=0, dry_run=False
    )

    with (
        patch("jidou.workers.match_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.match_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.match_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.match_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.match_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.match_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.match_tasks.create_llm_service"),
        patch(
            "jidou.workers.match_tasks.ParseOrchestrator.run",
            new_callable=AsyncMock,
            return_value=parse_result,
        ),
    ):
        result = await _match_files("tid-mf1", dry_run=False)

    assert result == "tid-mf1"
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# sync_tasks — _sync_all (success path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_all_on_progress_is_invoked() -> None:
    """The on_progress closure body in _sync_all executes when the orchestrator calls it."""
    from jidou.models.task import TaskStatus
    from jidou.workers.sync_tasks import _sync_all

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    sync_result = MagicMock()
    sync_result.scan.files_created = 1
    sync_result.download.files_downloaded = 1
    sync_result.match = MagicMock(files_matched=1, files_unmatched=0)

    async def fake_run(*args: object, **kwargs: object) -> object:
        on_phase = kwargs.get("on_phase")  # sync_tasks uses on_phase, not on_progress
        if callable(on_phase):
            await on_phase(1, 5, "syncing")  # type: ignore[operator]
        return sync_result

    with (
        patch("jidou.workers.sync_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.sync_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.sync_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.sync_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.sync_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.sync_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.sync_tasks.SFTPService"),
        patch("jidou.workers.sync_tasks.TMDBService"),
        patch("jidou.workers.sync_tasks.create_llm_service"),
        patch("jidou.workers.sync_tasks.SyncOrchestrator.run", side_effect=fake_run),
    ):
        result = await _sync_all("tid-sap1", dry_run=False)

    assert result == "tid-sap1"


@pytest.mark.asyncio
async def test_sync_all_success_path() -> None:
    """_sync_all runs SyncOrchestrator and marks task COMPLETED."""
    from jidou.models.task import TaskStatus
    from jidou.workers.sync_tasks import _sync_all

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    sync_result = MagicMock()
    sync_result.scan.files_created = 2
    sync_result.download.files_downloaded = 1
    sync_result.match = MagicMock(files_matched=1, files_unmatched=0)

    with (
        patch("jidou.workers.sync_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.sync_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.sync_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.sync_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.sync_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.sync_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.sync_tasks.SFTPService"),
        patch("jidou.workers.sync_tasks.TMDBService"),
        patch("jidou.workers.sync_tasks.create_llm_service"),
        patch(
            "jidou.workers.sync_tasks.SyncOrchestrator.run",
            new_callable=AsyncMock,
            return_value=sync_result,
        ),
    ):
        result = await _sync_all("tid-sa1", dry_run=False)

    assert result == "tid-sa1"
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# import_tasks — _path_import (success + exception)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_import_on_progress_and_on_event_invoked() -> None:
    """_path_import on_progress and on_event closure bodies execute when called."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    import_result = PathImportResult(show_results=[])

    async def fake_run(*args: object, **kwargs: object) -> PathImportResult:
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            await on_progress(1, 1, "processing")  # type: ignore[operator]
        return import_result

    with (
        patch("jidou.workers.import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch("jidou.workers.import_tasks.PathImportOrchestrator.run", side_effect=fake_run),
    ):
        result = await _path_import("tid-iop1", "/show/ep.mkv\n", "anime", False)

    assert result == "tid-iop1"


@pytest.mark.asyncio
async def test_path_import_success_path() -> None:
    """_path_import runs PathImportOrchestrator and marks task COMPLETED."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    import_result = PathImportResult(
        shows_processed=2,
        shows_created=1,
        shows_found=1,
        shows_not_found=0,
        episodes_tracked=5,
        episodes_unmatched=0,
        show_results=[],
    )

    with (
        patch("jidou.workers.import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch(
            "jidou.workers.import_tasks.PathImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=import_result,
        ),
    ):
        result = await _path_import("tid-pi1", "/show/S01E01.mkv\n", "anime", False)

    assert result == "tid-pi1"
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_path_import_exception_marks_failed() -> None:
    """Exception in _path_import marks task FAILED and re-raises."""
    from jidou.models.task import TaskStatus
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.import_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch(
            "jidou.workers.import_tasks.PathImportOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("tmdb timeout"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _path_import("tid-pi2", "/show/S01E01.mkv\n", "anime", False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# import_tasks — on_event closure, cancellation, None task branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_import_on_event_closure_invoked() -> None:
    """on_event closure body executes when PathImportOrchestrator calls it."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    import_result = PathImportResult(show_results=[])

    class FakePathOrchestrator:
        def __init__(self, *args: object, on_event: object = None, **kwargs: object) -> None:
            self._on_event = on_event

        async def run(self, *args: object, **kwargs: object) -> PathImportResult:
            if callable(self._on_event):
                await self._on_event("info", "Importing show", None)  # type: ignore[operator]
            return import_result

    with (
        patch("jidou.workers.import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock) as mock_event,
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch("jidou.workers.import_tasks.PathImportOrchestrator", FakePathOrchestrator),
    ):
        result = await _path_import("tid-ioev1", "/show/ep.mkv\n", "anime", False)

    assert result == "tid-ioev1"
    mock_event.assert_called()


@pytest.mark.asyncio
async def test_path_import_cancellation_swallowed() -> None:
    """TaskCancelledError from _path_import is caught and swallowed."""
    from jidou.models.task import TaskStatus
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.import_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch(
            "jidou.workers.import_tasks.PathImportOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _path_import("tid-ican1", "/show/ep.mkv\n", "anime", False)

    assert result == "tid-ican1"


@pytest.mark.asyncio
async def test_path_import_skips_emit_when_task_is_none() -> None:
    """No 'complete' emit when update_task_status returns None for path import."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    import_result = PathImportResult(show_results=[])

    with (
        patch("jidou.workers.import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("jidou.workers.import_tasks.emit_progress", new_callable=AsyncMock) as mock_emit,
        patch("jidou.workers.import_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch(
            "jidou.workers.import_tasks.PathImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=import_result,
        ),
    ):
        result = await _path_import("tid-inone1", "/show/ep.mkv\n", "anime", False)

    assert result == "tid-inone1"
    complete_calls = [c for c in mock_emit.call_args_list if c[0][0].get("type") == "complete"]
    assert len(complete_calls) == 0


# ---------------------------------------------------------------------------
# _fetch_trending (tasks.py)
# ---------------------------------------------------------------------------


def test_fetch_trending_shows_task_reraises_exception() -> None:
    """Unhandled exception in fetch_trending_shows_task is logged and re-raised."""
    with (
        patch(
            "jidou.workers.tasks._fetch_trending",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection failed"),
        ),
        pytest.raises(RuntimeError, match="connection failed"),
    ):
        fetch_trending_shows_task()


@pytest.mark.asyncio
async def test_fetch_trending_empty_result() -> None:
    """_fetch_trending returns 0 when TMDB returns empty results."""
    from jidou.workers.tasks import _fetch_trending

    mock_engine = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)

    with (
        patch("jidou.workers.tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.tasks.TMDBService.get_trending",
            new_callable=AsyncMock,
            return_value={"results": []},
        ),
    ):
        count = await _fetch_trending()

    assert count == 0
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_trending_skips_items_without_id() -> None:
    """Items without tmdb id are skipped in the upsert loop."""
    from jidou.workers.tasks import _fetch_trending

    mock_engine = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)

    results = [{"name": "No ID Show"}, {"id": 123, "name": "Valid Show"}]

    # on_conflict_do_update is PostgreSQL-only — mock the insert builder to avoid
    # SQLAlchemy dialect errors when running tests without a real Postgres engine.
    mock_insert = MagicMock()
    mock_insert.return_value = mock_insert

    with (
        patch("jidou.workers.tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.tasks.TMDBService.get_trending",
            new_callable=AsyncMock,
            return_value={"results": results},
        ),
        patch("jidou.workers.tasks.insert", return_value=mock_insert),
    ):
        count = await _fetch_trending()

    # Only the item with an id should have been counted
    assert count == 1


# ---------------------------------------------------------------------------
# seed_tasks
# ---------------------------------------------------------------------------


def test_seed_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in seed_remote_task must call mark_task_timed_out."""
    from jidou.workers.seed_tasks import seed_remote_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.seed_tasks._seed_remote",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.seed_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        seed_remote_task(dry_run=False)

    assert len(mark_calls) == 1


@pytest.mark.asyncio
async def test_seed_remote_skips_redelivery() -> None:
    """_seed_remote exits early when task is already terminal."""
    from jidou.models.task import TaskStatus
    from jidou.workers.seed_tasks import _seed_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    terminal = MagicMock(status=TaskStatus.COMPLETED.value)

    with (
        patch("jidou.workers.seed_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.seed_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.seed_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch("jidou.workers.seed_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
    ):
        result = await _seed_remote("tid-s1", dry_run=False)

    assert result == "tid-s1"
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_seed_remote_success_path() -> None:
    """_seed_remote runs the orchestrator and marks the task COMPLETED."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.seed_orchestrator import SeedResult
    from jidou.workers.seed_tasks import _seed_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    seed_result = SeedResult(
        paths_scanned=1,
        paths_failed=0,
        files_found=3,
        files_seeded=3,
        files_skipped=0,
    )

    with (
        patch("jidou.workers.seed_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.seed_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.seed_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch(
            "jidou.workers.seed_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.seed_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.seed_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.seed_tasks.SFTPService"),
        patch(
            "jidou.workers.seed_tasks.SeedOrchestrator.run",
            new_callable=AsyncMock,
            return_value=seed_result,
        ),
    ):
        result = await _seed_remote("tid-s2", dry_run=False)

    assert result == "tid-s2"
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_seed_remote_on_progress_is_invoked() -> None:
    """The on_progress closure body in _seed_remote executes when the orchestrator calls it."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.seed_orchestrator import SeedResult
    from jidou.workers.seed_tasks import _seed_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    seed_result = SeedResult(
        paths_scanned=1,
        paths_failed=0,
        files_found=1,
        files_seeded=1,
        files_skipped=0,
    )

    async def fake_run(*args: object, **kwargs: object) -> SeedResult:
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            await on_progress(1, 1, "seeding")  # type: ignore[operator]
        return seed_result

    with (
        patch("jidou.workers.seed_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.seed_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.seed_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.seed_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.seed_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.seed_tasks.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.seed_tasks.SFTPService"),
        patch("jidou.workers.seed_tasks.SeedOrchestrator.run", side_effect=fake_run),
    ):
        result = await _seed_remote("tid-sop1", dry_run=False)

    assert result == "tid-sop1"


@pytest.mark.asyncio
async def test_seed_remote_cancellation_marks_cancelled() -> None:
    """TaskCancelledError in _seed_remote updates status to CANCELLED."""
    from jidou.models.task import TaskStatus
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.seed_tasks import _seed_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.seed_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.seed_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.seed_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.seed_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.seed_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.seed_tasks.SFTPService"),
        patch(
            "jidou.workers.seed_tasks.SeedOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        result = await _seed_remote("tid-sc1", dry_run=False)

    assert result == "tid-sc1"
    cancelled_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.CANCELLED]
    assert len(cancelled_calls) >= 1


@pytest.mark.asyncio
async def test_seed_remote_exception_marks_failed() -> None:
    """Unexpected exception in _seed_remote marks task FAILED and re-raises."""
    from jidou.models.task import TaskStatus
    from jidou.workers.seed_tasks import _seed_remote

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)

    with (
        patch("jidou.workers.seed_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.seed_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.seed_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=pending,
        ),
        patch("jidou.workers.seed_tasks.update_task_status", new_callable=AsyncMock) as mock_update,
        patch("jidou.workers.seed_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.seed_tasks.SFTPService"),
        patch(
            "jidou.workers.seed_tasks.SeedOrchestrator.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("sftp connection lost"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _seed_remote("tid-s3", dry_run=False)

    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1
