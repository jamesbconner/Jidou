"""Characterization pins for how each orchestrator treats an ``on_event`` failure.

These tests freeze the *current* behavior, which is deliberately inconsistent:
download, parse, route and scan swallow an event-logging failure and finish the
work; sync and path import let it propagate and abort the run. A later approved
roadmap item (DF-7) changes these semantics on purpose, so each test is named
per orchestrator and is expected to be edited, not deleted, when that happens.

Setups are borrowed from the existing per-orchestrator test modules so the
failing ``on_event`` is the only variable.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators.download_orchestrator import DownloadOrchestrator
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator
from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
from jidou.orchestrators.route_orchestrator import RouteOrchestrator
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator
from jidou.orchestrators.sync_orchestrator import SyncOrchestrator
from tests.test_orchestrators import test_download_orchestrator as download_tests
from tests.test_orchestrators import test_match_orchestrator as match_tests
from tests.test_orchestrators import test_route_orchestrator as route_tests
from tests.test_orchestrators import test_scan_orchestrator as scan_tests
from tests.test_orchestrators import test_sync_orchestrator as sync_tests


def _failing_on_event() -> AsyncMock:
    """Build an ``on_event`` callback whose every invocation raises."""
    return AsyncMock(side_effect=RuntimeError("log down"))


async def test_route_event_failure_is_swallowed() -> None:
    """RouteOrchestrator finishes with the same result when on_event raises."""

    async def _run(on_event: AsyncMock) -> Any:
        file = route_tests._make_file()
        show = route_tests._make_show(local_path=None)
        session = route_tests._make_session([(file, show)])
        return await RouteOrchestrator(session).run(on_event=on_event)

    baseline = await _run(AsyncMock())
    on_event = _failing_on_event()
    result = await _run(on_event)

    assert on_event.await_count >= 1  # the failing callback really was hit
    assert result == baseline


async def test_parse_event_failure_is_swallowed() -> None:
    """ParseOrchestrator finishes with the same result when on_event raises."""

    async def _run(on_event: AsyncMock) -> Any:
        file1 = match_tests._make_file(filename="UnknownFile.S01E01.mkv")
        session = match_tests._make_session(files=[file1])
        return await ParseOrchestrator(session, llm=None).run(on_event=on_event)

    baseline = await _run(AsyncMock())
    on_event = _failing_on_event()
    result = await _run(on_event)

    assert on_event.await_count >= 1
    assert result == baseline


async def test_download_event_failure_is_swallowed() -> None:
    """DownloadOrchestrator returns, with files_downloaded unchanged, when on_event raises."""

    async def _run(on_event: AsyncMock) -> Any:
        file1 = download_tests._make_file(file_id=1, filename="ep1.mkv")
        file2 = download_tests._make_file(file_id=2, filename="ep2.mkv")
        session = download_tests._make_session(files=[file1, file2], dry_run=True)
        orch = DownloadOrchestrator(session, MagicMock(), download_tests._STAGING)
        return await orch.run(dry_run=True, on_event=on_event)

    baseline = await _run(AsyncMock())
    on_event = _failing_on_event()
    result = await _run(on_event)

    assert on_event.await_count >= 1
    assert result.files_downloaded == baseline.files_downloaded


async def test_scan_event_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """ScanOrchestrator returns when on_event raises while reporting a listing failure."""
    session = scan_tests._make_session()
    sftp = MagicMock()
    sftp.max_workers = 8
    sftp.list_remote_children = AsyncMock(side_effect=Exception("connection error"))
    sftp.list_remote_files_recursive_batch = AsyncMock(return_value=[])
    scan_tests._patch_existing(monkeypatch)

    on_event = _failing_on_event()
    result = await ScanOrchestrator(session, sftp, ["/bad/path"]).run(on_event=on_event)

    assert on_event.await_count >= 1
    assert result is not None


async def test_sync_event_failure_propagates() -> None:
    """SyncOrchestrator aborts with the on_event error instead of swallowing it."""
    session = sync_tests._make_session()
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_tmdb_cls.return_value.sync_all_shows = AsyncMock(
            return_value=sync_tests._make_tmdb_result()
        )
        mock_scan_cls.return_value.run = AsyncMock(return_value=sync_tests._make_scan_result())
        mock_dl_cls.return_value.run = AsyncMock(return_value=sync_tests._make_download_result())
        mock_parse_cls.return_value.run = AsyncMock(return_value=sync_tests._make_parse_result())
        mock_route_cls.return_value.run = AsyncMock(return_value=sync_tests._make_route_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        with pytest.raises(RuntimeError, match="log down"):
            await orch.run(on_event=_failing_on_event())


async def test_path_import_event_failure_propagates() -> None:
    """PathImportOrchestrator aborts with the on_event error instead of swallowing it."""
    # An empty run still emits the "LLM not configured" notice first, which is
    # enough to hit the callback without any TMDB/DB wiring.
    orch = PathImportOrchestrator(AsyncMock(), AsyncMock(), on_event=_failing_on_event())

    with pytest.raises(RuntimeError, match="log down"):
        await orch.run([])
