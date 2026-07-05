"""Tests for SyncOrchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators.download_orchestrator import DownloadResult
from jidou.orchestrators.parse_orchestrator import ParseResult
from jidou.orchestrators.route_orchestrator import RouteResult
from jidou.orchestrators.scan_orchestrator import ScanResult
from jidou.orchestrators.sync_orchestrator import SyncOrchestrator
from jidou.orchestrators.tmdb_orchestrator import TMDBSyncResult
from jidou.services.progress import TaskCancelledError


def _make_tmdb_result(**kwargs):
    defaults = {"shows_synced": 1, "episodes_upserted": 5, "episodes_skipped": 0}
    return TMDBSyncResult(**{**defaults, **kwargs})


def _make_scan_result(**kwargs):
    defaults = {"paths_scanned": 1, "files_found": 3, "files_created": 3, "files_skipped": 0}
    return ScanResult(**{**defaults, **kwargs})


def _make_download_result(**kwargs):
    defaults = {
        "files_downloaded": 3,
        "bytes_downloaded": 3000,
        "files_failed": 0,
        "dry_run": False,
    }
    return DownloadResult(**{**defaults, **kwargs})


def _make_parse_result(**kwargs):
    defaults = {
        "files_processed": 3,
        "files_matched": 3,
        "files_unmatched": 0,
        "files_failed": 0,
        "dry_run": False,
    }
    return ParseResult(**{**defaults, **kwargs})


def _make_route_result(**kwargs):
    defaults = {"files_routed": 3, "files_failed": 0, "dry_run": False}
    return RouteResult(**{**defaults, **kwargs})


def _make_session(show=None):
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = show
    session.execute = AsyncMock(return_value=result)
    return session


async def test_run_returns_all_phase_results():
    """SyncResult contains the results from all 5 phases."""
    session = _make_session()
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    tmdb_res = _make_tmdb_result()
    scan_res = _make_scan_result()
    dl_res = _make_download_result()
    parse_res = _make_parse_result()
    route_res = _make_route_result()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_tmdb_cls.return_value.sync_all_shows = AsyncMock(return_value=tmdb_res)
        mock_scan_cls.return_value.run = AsyncMock(return_value=scan_res)
        mock_dl_cls.return_value.run = AsyncMock(return_value=dl_res)
        mock_parse_cls.return_value.run = AsyncMock(return_value=parse_res)
        mock_route_cls.return_value.run = AsyncMock(return_value=route_res)

        orch = SyncOrchestrator(session, sftp, tmdb)
        result = await orch.run()

    assert result.tmdb == tmdb_res
    assert result.scan == scan_res
    assert result.download == dl_res
    assert result.parse == parse_res
    assert result.route == route_res


async def test_run_skips_tmdb_if_show_cached():
    """When show_id given and show.cached=True, sync_show_episodes is not called."""
    show = MagicMock()
    show.cached = True

    session = _make_session(show=show)
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    scan_res = _make_scan_result()
    dl_res = _make_download_result()
    parse_res = _make_parse_result()
    route_res = _make_route_result()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_tmdb_instance = mock_tmdb_cls.return_value
        mock_tmdb_instance.sync_show_episodes = AsyncMock()
        mock_scan_cls.return_value.run = AsyncMock(return_value=scan_res)
        mock_dl_cls.return_value.run = AsyncMock(return_value=dl_res)
        mock_parse_cls.return_value.run = AsyncMock(return_value=parse_res)
        mock_route_cls.return_value.run = AsyncMock(return_value=route_res)

        orch = SyncOrchestrator(session, sftp, tmdb)
        await orch.run(show_id=1)

    mock_tmdb_instance.sync_show_episodes.assert_not_called()


async def test_run_dry_run_skips_tmdb_entirely():
    """With dry_run=True, TMDBOrchestrator is never instantiated or called."""
    session = _make_session()
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    scan_res = _make_scan_result()
    dl_res = _make_download_result()
    parse_res = _make_parse_result()
    route_res = _make_route_result()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_scan_cls.return_value.run = AsyncMock(return_value=scan_res)
        mock_dl_cls.return_value.run = AsyncMock(return_value=dl_res)
        mock_parse_cls.return_value.run = AsyncMock(return_value=parse_res)
        mock_route_cls.return_value.run = AsyncMock(return_value=route_res)

        orch = SyncOrchestrator(session, sftp, tmdb)
        result = await orch.run(dry_run=True)

    mock_tmdb_cls.assert_not_called()
    assert result.tmdb.episodes_upserted == 0


async def test_run_on_phase_called_5_times():
    """on_phase callback is invoked once per phase with correct phase numbers."""
    session = _make_session()
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    on_phase = AsyncMock()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_tmdb_cls.return_value.sync_all_shows = AsyncMock(return_value=_make_tmdb_result())
        mock_scan_cls.return_value.run = AsyncMock(return_value=_make_scan_result())
        mock_dl_cls.return_value.run = AsyncMock(return_value=_make_download_result())
        mock_parse_cls.return_value.run = AsyncMock(return_value=_make_parse_result())
        mock_route_cls.return_value.run = AsyncMock(return_value=_make_route_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        await orch.run(on_phase=on_phase)

    assert on_phase.call_count == 5
    phase_numbers = [c.args[0] for c in on_phase.call_args_list]
    assert phase_numbers == [1, 2, 3, 4, 5]


async def test_run_cancellation_propagates():
    """TaskCancelledError raised by on_phase propagates out and stops later phases."""
    session = _make_session()
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    call_count = 0

    async def cancel_on_second(current: int, total: int, message: str) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise TaskCancelledError("cancelled")

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_tmdb_cls.return_value.sync_all_shows = AsyncMock(return_value=_make_tmdb_result())
        mock_scan_cls.return_value.run = AsyncMock(return_value=_make_scan_result())
        mock_dl_cls.return_value.run = AsyncMock(return_value=_make_download_result())
        mock_parse_cls.return_value.run = AsyncMock(return_value=_make_parse_result())
        mock_route_cls.return_value.run = AsyncMock(return_value=_make_route_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        with pytest.raises(TaskCancelledError):
            await orch.run(on_phase=cancel_on_second)

    # Phase 3 (Download) should never have run — cancelled at phase 2
    mock_dl_cls.return_value.run.assert_not_called()


async def test_run_show_not_found_uses_empty_tmdb_result():
    """When show_id is given but show is missing from DB, TMDB result is empty."""
    session = _make_session(show=None)
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
        mock_tmdb_cls.return_value.sync_show_episodes = AsyncMock()
        mock_scan_cls.return_value.run = AsyncMock(return_value=_make_scan_result())
        mock_dl_cls.return_value.run = AsyncMock(return_value=_make_download_result())
        mock_parse_cls.return_value.run = AsyncMock(return_value=_make_parse_result())
        mock_route_cls.return_value.run = AsyncMock(return_value=_make_route_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        result = await orch.run(show_id=99)

    mock_tmdb_cls.return_value.sync_show_episodes.assert_not_called()
    assert result.tmdb.shows_synced == 0


async def test_run_tmdb_exception_handled_and_sync_continues():
    """When sync_show_episodes raises, exception is caught and sync continues."""
    show = MagicMock()
    show.cached = False
    show.id = 5

    result_show = MagicMock()
    result_show.scalar_one_or_none.return_value = show
    result_ep = MagicMock()
    result_ep.scalar.return_value = False  # no episodes → triggers sync
    # Phase 4.5 gap-fill query: no shows need re-sync after the rollback.
    result_gap = MagicMock()
    result_gap.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(side_effect=[result_show, result_ep, result_gap])

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
        mock_tmdb_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=RuntimeError("TMDB API down")
        )
        mock_scan_cls.return_value.run = AsyncMock(return_value=_make_scan_result())
        mock_dl_cls.return_value.run = AsyncMock(return_value=_make_download_result())
        mock_parse_cls.return_value.run = AsyncMock(return_value=_make_parse_result())
        mock_route_cls.return_value.run = AsyncMock(return_value=_make_route_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        result = await orch.run(show_id=5)  # must not raise


async def test_run_on_event_called_for_phase_results():
    """on_event callback is passed to sub-orchestrators and called with phase summaries."""
    session = _make_session()
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    on_event = AsyncMock()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_tmdb_cls.return_value.sync_all_shows = AsyncMock(return_value=_make_tmdb_result())
        mock_scan_cls.return_value.run = AsyncMock(return_value=_make_scan_result())
        mock_dl_cls.return_value.run = AsyncMock(return_value=_make_download_result())
        mock_parse_cls.return_value.run = AsyncMock(return_value=_make_parse_result())
        mock_route_cls.return_value.run = AsyncMock(return_value=_make_route_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        await orch.run(on_event=on_event)

    # on_event should be called for each phase (5 total)
    assert on_event.call_count == 5
    # Verify that at least one call has a summary message
    calls = on_event.call_args_list
    messages = [c[0][1] for c in calls]  # Extract message from each call
    assert any("TMDB" in msg or "sync" in msg for msg in messages)


async def test_run_on_event_passed_to_route_orchestrator():
    """RouteOrchestrator.run() is called with on_event parameter."""
    session = _make_session()
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    on_event = AsyncMock()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_tmdb_cls.return_value.sync_all_shows = AsyncMock(return_value=_make_tmdb_result())
        mock_scan_cls.return_value.run = AsyncMock(return_value=_make_scan_result())
        mock_dl_cls.return_value.run = AsyncMock(return_value=_make_download_result())
        mock_parse_cls.return_value.run = AsyncMock(return_value=_make_parse_result())
        mock_route_cls.return_value.run = AsyncMock(return_value=_make_route_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        await orch.run(on_event=on_event)

    # Verify RouteOrchestrator.run was called with on_event keyword argument
    mock_route_cls.return_value.run.assert_called_once()
    call_kwargs = mock_route_cls.return_value.run.call_args[1]
    assert "on_event" in call_kwargs
    assert call_kwargs["on_event"] == on_event
