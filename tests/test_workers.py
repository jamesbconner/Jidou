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

    def test_broker_visibility_timeout_exceeds_longest_task_time_limit(self) -> None:
        """Redis redelivers unacked messages after visibility_timeout elapses.

        With task_acks_late=True, a task isn't acked until it finishes, so
        visibility_timeout must stay above every task's time_limit override —
        otherwise a still-running task gets redelivered and re-executed from
        scratch, racing against itself on the same DB rows.
        """
        from jidou.workers.import_tasks import path_import_task
        from jidou.workers.sync_tasks import sync_all_task

        visibility_timeout = celery_app.conf.broker_transport_options["visibility_timeout"]
        assert visibility_timeout > path_import_task.time_limit
        assert visibility_timeout > sync_all_task.time_limit
        assert visibility_timeout > celery_app.conf.task_time_limit


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


def _capture_run_task_workflow(module_path: str) -> tuple:
    """Patch <module_path>.run_task_workflow, capturing its call kwargs and `work` callback.

    Lifecycle machinery (redelivery skip, RUNNING/COMPLETED/CANCELLED/FAILED
    transitions, on_progress, on_event separate-session wiring) is now covered
    once, generically, in tests/test_worker_harness.py. Worker-level tests use
    this to verify the worker calls run_task_workflow with the right
    task_type/progress_total/dry_run/running_message, then invoke the
    captured `work` closure directly (with fake session/on_progress/on_event)
    to verify it wires the right orchestrator and returns the right
    WorkflowResult -- the part that's actually worker-specific.

    Returns (patcher, captured) -- use `with patcher:` then read `captured`.
    """
    captured: dict[str, object] = {}

    async def fake_run_task_workflow(
        celery_task_id: str,
        task_type: str,
        work: object,
        *,
        progress_total: int = 0,
        dry_run: bool = False,
        running_message: str = "",
    ) -> str:
        captured["celery_task_id"] = celery_task_id
        captured["task_type"] = task_type
        captured["work"] = work
        captured["progress_total"] = progress_total
        captured["dry_run"] = dry_run
        captured["running_message"] = running_message
        return celery_task_id

    return patch(f"{module_path}.run_task_workflow", side_effect=fake_run_task_workflow), captured


# ---------------------------------------------------------------------------
# route_tasks / sync_tasks — on_event wiring regression
#
# Locks down that _route_files and _sync_all actually construct and pass a
# working on_event closure through to RouteOrchestrator/SyncOrchestrator,
# added *before* migrating either to the harness (see PR-13 / issue #304) so
# the just-fixed per-file event-log bug (commits ee1cfd5/5ef3c77 on
# route_orchestrator.py) can't silently regress during that migration.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_files_wires_on_event_to_orchestrator() -> None:
    """_route_files passes a working on_event to RouteOrchestrator.run()."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.route_orchestrator import RouteResult
    from jidou.workers.route_tasks import _route_files

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    route_result = RouteResult(files_routed=1, files_failed=0, dry_run=False)

    async def fake_run(*args: object, **kwargs: object) -> RouteResult:
        on_event = kwargs.get("on_event")
        assert callable(on_event)
        await on_event("info", "Routed Show S01E01", {"show": "Show"})  # type: ignore[operator]
        return route_result

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
        patch("jidou.workers._harness.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers._harness.append_task_event", new_callable=AsyncMock) as mock_append,
        patch("jidou.workers.route_tasks.RouteOrchestrator.run", side_effect=fake_run),
    ):
        result = await _route_files("tid-revent", dry_run=False)

    assert result == "tid-revent"
    mock_append.assert_awaited_once_with(
        _mock_session, "tid-revent", "info", "Routed Show S01E01", {"show": "Show"}
    )


@pytest.mark.asyncio
async def test_sync_all_wires_on_event_to_orchestrator() -> None:
    """_sync_all passes a working on_event to SyncOrchestrator.run()."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.sync_orchestrator import SyncResult
    from jidou.workers.sync_tasks import _sync_all

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    sync_result = MagicMock()
    sync_result.tmdb.episodes_upserted = 0
    sync_result.scan.files_created = 0
    sync_result.download.files_downloaded = 0
    sync_result.parse.files_matched = 0
    sync_result.route.files_routed = 0

    async def fake_run(*args: object, **kwargs: object) -> SyncResult:
        on_event = kwargs.get("on_event")
        assert callable(on_event)
        await on_event("info", "Routed Show S01E01", {"show": "Show"})  # type: ignore[operator]
        return sync_result

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
        patch("jidou.workers._harness.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers._harness.append_task_event", new_callable=AsyncMock) as mock_append,
        patch("jidou.workers.sync_tasks.SFTPService"),
        patch("jidou.workers.sync_tasks.TMDBService"),
        patch("jidou.workers.sync_tasks.create_llm_service"),
        patch("jidou.workers.sync_tasks.SyncOrchestrator.run", side_effect=fake_run),
    ):
        result = await _sync_all("tid-sevent", dry_run=False)

    assert result == "tid-sevent"
    mock_append.assert_awaited_once_with(
        _mock_session, "tid-sevent", "info", "Routed Show S01E01", {"show": "Show"}
    )


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
async def test_route_files_wires_orchestrator_and_returns_summary() -> None:
    """_route_files wires run_task_workflow, and its `work` closure calls RouteOrchestrator.

    Lifecycle machinery (redelivery skip, RUNNING/COMPLETED/CANCELLED/FAILED,
    on_progress/on_event plumbing) is covered generically in
    tests/test_worker_harness.py; this test covers what's route-specific.
    """
    from jidou.orchestrators.route_orchestrator import RouteResult
    from jidou.workers.route_tasks import _route_files

    patcher, captured = _capture_run_task_workflow("jidou.workers.route_tasks")
    with patcher:
        result = await _route_files("tid-r1", dry_run=True)

    assert result == "tid-r1"
    assert captured["task_type"] == "route"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is True

    route_result = RouteResult(files_routed=3, files_failed=1, dry_run=True)
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with patch(
        "jidou.workers.route_tasks.RouteOrchestrator.run",
        new_callable=AsyncMock,
        return_value=route_result,
    ) as mock_run:
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    mock_run.assert_awaited_once_with(dry_run=True, on_progress=on_progress, on_event=on_event)
    assert wf_result.progress_current == 4
    assert wf_result.progress_total == 4
    assert wf_result.result_summary == {
        "files_routed": 3,
        "files_failed": 1,
        "dry_run": True,
    }
    assert wf_result.complete_summary == {"files_routed": 3, "dry_run": True}


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
async def test_match_files_wires_orchestrator_and_returns_summary() -> None:
    """_match_files wires run_task_workflow, and its `work` closure calls ParseOrchestrator."""
    from jidou.orchestrators.parse_orchestrator import ParseResult
    from jidou.workers.match_tasks import _match_files

    patcher, captured = _capture_run_task_workflow("jidou.workers.match_tasks")
    with patcher:
        result = await _match_files("tid-m1", dry_run=True)

    assert result == "tid-m1"
    assert captured["task_type"] == "match"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is True

    parse_result = ParseResult(
        files_processed=4, files_matched=3, files_unmatched=1, files_failed=0, dry_run=True
    )
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.match_tasks.create_llm_service") as mock_create_llm,
        patch(
            "jidou.workers.match_tasks.ParseOrchestrator.run",
            new_callable=AsyncMock,
            return_value=parse_result,
        ) as mock_run,
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    mock_create_llm.assert_called_once()
    mock_run.assert_awaited_once_with(dry_run=True, on_progress=on_progress, on_event=on_event)
    assert wf_result.progress_current == 4
    assert wf_result.progress_total == 4
    assert wf_result.result_summary == {
        "files_processed": 4,
        "files_matched": 3,
        "files_unmatched": 1,
        "files_failed": 0,
        "dry_run": True,
    }
    assert wf_result.complete_summary == {"files_matched": 3, "dry_run": True}


# ---------------------------------------------------------------------------
# sync_tasks
# ---------------------------------------------------------------------------


def test_sync_all_task_has_extended_time_limits() -> None:
    """sync_all_task overrides the app-wide 50min/60min limits.

    Unlike scan/download/match/route, which each budget the default window
    for a single phase, sync chains all four sequentially in one task
    execution and can legitimately exceed the global default on any real
    backlog — regression test for the celery_app.py-wide default being
    silently reapplied if the decorator override were ever removed.
    """
    from jidou.workers.celery_app import celery_app
    from jidou.workers.sync_tasks import sync_all_task

    assert sync_all_task.soft_time_limit > celery_app.conf.task_soft_time_limit
    assert sync_all_task.time_limit > celery_app.conf.task_time_limit


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
async def test_sync_all_wires_orchestrator_and_returns_summary() -> None:
    """_sync_all wires run_task_workflow and its `work` closure calls SyncOrchestrator correctly."""
    from jidou.workers.sync_tasks import _sync_all

    patcher, captured = _capture_run_task_workflow("jidou.workers.sync_tasks")
    with patcher:
        result = await _sync_all("tid-s1", dry_run=True)

    assert result == "tid-s1"
    assert captured["task_type"] == "sync"
    assert captured["progress_total"] == 5
    assert captured["dry_run"] is True

    sync_result = MagicMock()
    sync_result.tmdb.episodes_upserted = 2
    sync_result.scan.files_created = 3
    sync_result.download.files_downloaded = 4
    sync_result.parse.files_matched = 5
    sync_result.route.files_routed = 6
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.sync_tasks.SFTPService"),
        patch("jidou.workers.sync_tasks.TMDBService"),
        patch("jidou.workers.sync_tasks.create_llm_service"),
        patch(
            "jidou.workers.sync_tasks.SyncOrchestrator.run",
            new_callable=AsyncMock,
            return_value=sync_result,
        ) as mock_run,
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    mock_run.assert_awaited_once_with(dry_run=True, on_phase=on_progress, on_event=on_event)
    assert wf_result.progress_current == 5
    assert wf_result.progress_total == 5
    assert wf_result.result_summary == {
        "episodes_upserted": 2,
        "files_created": 3,
        "files_downloaded": 4,
        "files_matched": 5,
        "files_routed": 6,
        "dry_run": True,
    }
    assert wf_result.complete_summary == {
        "files_matched": 5,
        "files_routed": 6,
        "dry_run": True,
    }


# ---------------------------------------------------------------------------
# import_tasks (path_import_task)
# ---------------------------------------------------------------------------


def test_path_import_task_has_extended_time_limits() -> None:
    """path_import_task overrides the app-wide 50min/60min limits.

    A bulk import can span hundreds of TMDB-rate-limited new shows and
    legitimately take hours, well past the global default meant for quick
    per-file tasks — regression test for the celery_app.py-wide default
    being silently reapplied if the decorator override were ever removed.
    """
    from jidou.workers.celery_app import celery_app
    from jidou.workers.import_tasks import path_import_task

    assert path_import_task.soft_time_limit > celery_app.conf.task_soft_time_limit
    assert path_import_task.time_limit > celery_app.conf.task_time_limit


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


# ---------------------------------------------------------------------------
# scan_tasks — _scan_remote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_remote_wires_orchestrator_and_returns_summary() -> None:
    """_scan_remote wires run_task_workflow, and its `work` closure calls ScanOrchestrator."""
    from jidou.orchestrators.scan_orchestrator import ScanResult
    from jidou.workers.scan_tasks import _scan_remote

    patcher, captured = _capture_run_task_workflow("jidou.workers.scan_tasks")
    with patcher:
        result = await _scan_remote("tid-sc1", dry_run=True)

    assert result == "tid-sc1"
    assert captured["task_type"] == "scan"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is True

    scan_result = ScanResult(
        paths_scanned=5, files_found=10, files_created=3, files_skipped=7, dirs_discovered=2
    )
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.scan_tasks.SFTPService") as mock_sftp,
        patch(
            "jidou.workers.scan_tasks.ScanOrchestrator.run",
            new_callable=AsyncMock,
            return_value=scan_result,
        ) as mock_run,
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    mock_sftp.assert_called_once()
    mock_run.assert_awaited_once_with(dry_run=True, on_progress=on_progress, on_event=on_event)
    assert wf_result.progress_current == 5
    assert wf_result.progress_total == 5
    assert wf_result.result_summary == {
        "paths_scanned": 5,
        "files_found": 10,
        "files_created": 3,
        "files_skipped": 7,
        "dirs_discovered": 2,
        "dry_run": True,
    }
    assert wf_result.complete_summary == {"files_created": 3, "dry_run": True}


# ---------------------------------------------------------------------------
# download_tasks — _download_files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_files_wires_orchestrator_and_returns_summary() -> None:
    """_download_files wires run_task_workflow, and `work` calls DownloadOrchestrator."""
    from jidou.orchestrators.download_orchestrator import DownloadResult
    from jidou.workers.download_tasks import _download_files

    patcher, captured = _capture_run_task_workflow("jidou.workers.download_tasks")
    with patcher:
        result = await _download_files("tid-dl1", dry_run=True)

    assert result == "tid-dl1"
    assert captured["task_type"] == "download"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is True

    dl_result = DownloadResult(
        files_downloaded=4, bytes_downloaded=1024, files_failed=1, dry_run=True
    )
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.download_tasks.SFTPService") as mock_sftp,
        patch(
            "jidou.workers.download_tasks.DownloadOrchestrator.run",
            new_callable=AsyncMock,
            return_value=dl_result,
        ) as mock_run,
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    mock_sftp.assert_called_once()
    mock_run.assert_awaited_once()
    assert mock_run.call_args.kwargs["on_progress"] is on_progress
    assert mock_run.call_args.kwargs["on_event"] is on_event
    assert wf_result.progress_current == 5
    assert wf_result.progress_total == 5
    assert wf_result.result_summary == {
        "files_downloaded": 4,
        "bytes_downloaded": 1024,
        "files_failed": 1,
        "dry_run": True,
    }
    assert wf_result.complete_summary == {"files_downloaded": 4, "dry_run": True}


# ---------------------------------------------------------------------------
# import_tasks — _path_import (success + exception)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_import_wires_orchestrator_and_returns_summary() -> None:
    """_path_import wires run_task_workflow, and its `work` closure calls PathImportOrchestrator.

    Also covers what used to be test_path_import_on_event_closure_invoked:
    PathImportOrchestrator receives on_event at *construction* time (unlike
    route/sync, which pass it to .run()) -- worth locking down since it's a
    different wiring shape than every other worker.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    patcher, captured = _capture_run_task_workflow("jidou.workers.import_tasks")
    with patcher:
        result = await _path_import("tid-pi1", "/show/S01E01.mkv\n", "anime", True)

    assert result == "tid-pi1"
    assert captured["task_type"] == "import"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is True
    assert captured["running_message"] == "Parsing file…"

    import_result = PathImportResult(
        shows_processed=2,
        shows_created=1,
        shows_found=1,
        shows_not_found=0,
        episodes_tracked=5,
        episodes_unmatched=0,
        show_results=[],
    )
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    captured_on_event: list[object] = []

    class FakePathOrchestrator:
        def __init__(self, *args: object, on_event: object = None, **kwargs: object) -> None:
            captured_on_event.append(on_event)

        async def run(self, *args: object, **kwargs: object) -> PathImportResult:
            assert kwargs.get("on_progress") is on_progress
            return import_result

    with (
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch("jidou.workers.import_tasks.PathImportOrchestrator", FakePathOrchestrator),
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    assert captured_on_event == [on_event]
    assert wf_result.progress_current == 2
    assert wf_result.progress_total == 2
    assert wf_result.result_summary["shows_created"] == 1
    assert wf_result.result_summary["episodes_tracked"] == 5
    assert wf_result.result_summary["show_results"] == []


@pytest.mark.asyncio
async def test_path_import_forwards_mode_to_orchestrator_and_summary() -> None:
    """mode threads from _path_import's signature into PathImportOrchestrator's
    constructor and into result_summary["mode"], and shows_only mode gets a
    done-message that doesn't claim episodes were tracked when none were.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    patcher, captured = _capture_run_task_workflow("jidou.workers.import_tasks")
    with patcher:
        await _path_import("tid-pi-mode", "/show/S01E01.mkv\n", "anime", False, "shows_only")

    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    captured_kwargs: dict[str, object] = {}

    import_result = PathImportResult(
        shows_processed=1,
        shows_created=1,
        shows_found=0,
        shows_not_found=0,
        episodes_tracked=0,
        episodes_unmatched=0,
        show_results=[],
        mode="shows_only",
    )

    class FakePathOrchestrator:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

        async def run(self, *args: object, **kwargs: object) -> PathImportResult:
            return import_result

    with (
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch("jidou.workers.import_tasks.PathImportOrchestrator", FakePathOrchestrator),
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    assert captured_kwargs["mode"] == "shows_only"
    assert wf_result.result_summary["mode"] == "shows_only"
    assert "episode matching skipped" in wf_result.message
    assert "0 episodes tracked" not in wf_result.message


@pytest.mark.parametrize(
    ("content_type", "expected_attr"),
    [
        ("anime", "local_anime_host_path"),
        ("tv", "local_tv_host_path"),
        ("movie", "local_movie_host_path"),
    ],
)
def test_host_root_for_content_type(content_type: str, expected_attr: str) -> None:
    """_host_root_for_content_type maps each content type to its configured
    host-side library root, mirroring shows._auto_local_path's container-side
    mapping.
    """
    from jidou.config import settings
    from jidou.workers.import_tasks import _host_root_for_content_type

    assert _host_root_for_content_type(content_type) == getattr(settings, expected_attr)


@pytest.mark.asyncio
async def test_path_import_passes_content_type_root_to_parse_file() -> None:
    """_path_import anchors show_dir resolution by passing the content type's
    configured host root into parse_file, instead of leaving it to infer the
    show directory purely from local path shape.
    """
    from jidou.config import settings
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    import_result = PathImportResult()
    mock_parse_file = MagicMock(return_value=[])

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
        patch("jidou.workers._harness.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.parse_file", mock_parse_file),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch(
            "jidou.workers.import_tasks.PathImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=import_result,
        ),
    ):
        await _path_import("tid-pi-root", "/show/S01E01.mkv\n", "anime", False)

    mock_parse_file.assert_called_once_with(
        "/show/S01E01.mkv\n", root=settings.local_anime_host_path, directories_only=False
    )


@pytest.mark.asyncio
async def test_path_import_shows_only_mode_passes_directories_only_true() -> None:
    """mode='shows_only' passes directories_only=True into parse_file, so a
    bare show-directory listing (no filenames) is accepted for this mode."""
    from jidou.config import settings
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    import_result = PathImportResult(mode="shows_only")
    mock_parse_file = MagicMock(return_value=[])

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
        patch("jidou.workers._harness.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.parse_file", mock_parse_file),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch(
            "jidou.workers.import_tasks.PathImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=import_result,
        ),
    ):
        await _path_import(
            "tid-pi-shows-only", "Z:\\anime tv\\Show\\\n", "anime", False, "shows_only"
        )

    mock_parse_file.assert_called_once_with(
        "Z:\\anime tv\\Show\\\n", root=settings.local_anime_host_path, directories_only=True
    )


@pytest.mark.asyncio
async def test_path_import_zero_entries_from_nontrivial_file_emits_warning() -> None:
    """A file with real content but zero parseable entries (e.g. wrong
    encoding) emits a warn event instead of completing silently with no
    indication of what went wrong.
    """
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.path_import_orchestrator import PathImportResult
    from jidou.workers.import_tasks import _path_import

    mock_engine, _mock_session, mock_factory = _worker_session_mocks()
    pending = MagicMock(status=TaskStatus.PENDING.value)
    completed = MagicMock(status=TaskStatus.COMPLETED.value)
    empty_result = PathImportResult()
    mock_append_event = AsyncMock()

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
        patch("jidou.workers._harness.check_task_cancelled", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.import_tasks.append_task_event", mock_append_event),
        patch("jidou.workers.import_tasks.parse_file", return_value=[]),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch(
            "jidou.workers.import_tasks.PathImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=empty_result,
        ),
    ):
        result = await _path_import(
            "tid-pi-empty",
            "Z:\\anime\\Show\\Season 01\\Show.S01E01.mkv\n",
            "anime",
            False,
        )

    assert result == "tid-pi-empty"
    warn_calls = [c for c in mock_append_event.call_args_list if c.args[2] == "warn"]
    assert warn_calls, "expected a warn event for zero entries from a non-trivial file"
    assert "0 usable entries" in warn_calls[0].args[3]


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
async def test_seed_remote_wires_orchestrator_and_returns_summary() -> None:
    """_seed_remote wires run_task_workflow, and its `work` closure calls SeedOrchestrator."""
    from jidou.orchestrators.seed_orchestrator import SeedResult
    from jidou.workers.seed_tasks import _seed_remote

    patcher, captured = _capture_run_task_workflow("jidou.workers.seed_tasks")
    with patcher:
        result = await _seed_remote("tid-s2", dry_run=True)

    assert result == "tid-s2"
    assert captured["task_type"] == "seed"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is True

    seed_result = SeedResult(
        paths_scanned=1,
        paths_failed=0,
        files_found=3,
        files_seeded=3,
        files_skipped=0,
    )
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.seed_tasks.SFTPService") as mock_sftp,
        patch(
            "jidou.workers.seed_tasks.SeedOrchestrator.run",
            new_callable=AsyncMock,
            return_value=seed_result,
        ) as mock_run,
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    mock_sftp.assert_called_once()
    mock_run.assert_awaited_once_with(dry_run=True, on_progress=on_progress)
    assert wf_result.progress_current == 3
    assert wf_result.progress_total == 3
    assert wf_result.result_summary == {
        "paths_scanned": 1,
        "paths_failed": 0,
        "files_found": 3,
        "files_seeded": 3,
        "files_skipped": 0,
        "skipped_by_status": seed_result.skipped_by_status,
        "dry_run": True,
    }
    assert wf_result.complete_summary is None
