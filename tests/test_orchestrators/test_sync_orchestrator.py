"""Tests for SyncOrchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators.download_orchestrator import DownloadResult
from jidou.orchestrators.match_orchestrator import MatchResult
from jidou.orchestrators.scan_orchestrator import ScanResult
from jidou.orchestrators.sync_orchestrator import SyncOrchestrator
from jidou.orchestrators.tmdb_orchestrator import TMDBSyncResult
from jidou.services.progress import TaskCancelledError


def _make_tmdb_result(**kwargs):
    defaults = {"shows_synced": 1, "episodes_upserted": 5, "episodes_skipped": 0}
    return TMDBSyncResult(**{**defaults, **kwargs})


def _make_scan_result(**kwargs):
    defaults = {"shows_scanned": 1, "files_found": 3, "files_created": 3, "files_skipped": 0}
    return ScanResult(**{**defaults, **kwargs})


def _make_download_result(**kwargs):
    defaults = {
        "files_downloaded": 3,
        "bytes_downloaded": 3000,
        "files_skipped": 0,
        "files_failed": 0,
        "dry_run": False,
    }
    return DownloadResult(**{**defaults, **kwargs})


def _make_match_result(**kwargs):
    defaults = {
        "files_matched": 3,
        "matched_by_heuristic": 3,
        "matched_by_llm": 0,
        "files_unmatched": 0,
        "files_failed": 0,
        "dry_run": False,
    }
    return MatchResult(**{**defaults, **kwargs})


def _make_session(show=None):
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = show
    session.execute = AsyncMock(return_value=result)
    return session


async def test_run_returns_all_phase_results():
    """SyncResult contains the results from all 4 phases."""
    session = _make_session()
    sftp = MagicMock()
    tmdb = MagicMock()

    tmdb_res = _make_tmdb_result()
    scan_res = _make_scan_result()
    dl_res = _make_download_result()
    match_res = _make_match_result()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as MockTMDB,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as MockScan,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as MockDL,
        patch("jidou.orchestrators.sync_orchestrator.MatchOrchestrator") as MockMatch,
    ):
        MockTMDB.return_value.sync_all_shows = AsyncMock(return_value=tmdb_res)
        MockScan.return_value.run = AsyncMock(return_value=scan_res)
        MockDL.return_value.run = AsyncMock(return_value=dl_res)
        MockMatch.return_value.run = AsyncMock(return_value=match_res)

        orch = SyncOrchestrator(session, sftp, tmdb)
        result = await orch.run()

    assert result.tmdb == tmdb_res
    assert result.scan == scan_res
    assert result.download == dl_res
    assert result.match == match_res


async def test_run_skips_tmdb_if_show_cached():
    """When show_id given and show.cached=True, sync_show_episodes is not called."""
    show = MagicMock()
    show.cached = True

    session = _make_session(show=show)
    sftp = MagicMock()
    tmdb = MagicMock()

    scan_res = _make_scan_result()
    dl_res = _make_download_result()
    match_res = _make_match_result()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as MockTMDB,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as MockScan,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as MockDL,
        patch("jidou.orchestrators.sync_orchestrator.MatchOrchestrator") as MockMatch,
    ):
        mock_tmdb_instance = MockTMDB.return_value
        mock_tmdb_instance.sync_show_episodes = AsyncMock()
        MockScan.return_value.run = AsyncMock(return_value=scan_res)
        MockDL.return_value.run = AsyncMock(return_value=dl_res)
        MockMatch.return_value.run = AsyncMock(return_value=match_res)

        orch = SyncOrchestrator(session, sftp, tmdb)
        await orch.run(show_id=1)

    mock_tmdb_instance.sync_show_episodes.assert_not_called()


async def test_run_on_phase_called_4_times():
    """on_phase callback is invoked once per phase with correct phase numbers."""
    session = _make_session()
    sftp = MagicMock()
    tmdb = MagicMock()

    on_phase = AsyncMock()

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as MockTMDB,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as MockScan,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as MockDL,
        patch("jidou.orchestrators.sync_orchestrator.MatchOrchestrator") as MockMatch,
    ):
        MockTMDB.return_value.sync_all_shows = AsyncMock(return_value=_make_tmdb_result())
        MockScan.return_value.run = AsyncMock(return_value=_make_scan_result())
        MockDL.return_value.run = AsyncMock(return_value=_make_download_result())
        MockMatch.return_value.run = AsyncMock(return_value=_make_match_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        await orch.run(on_phase=on_phase)

    assert on_phase.call_count == 4
    phase_numbers = [c.args[0] for c in on_phase.call_args_list]
    assert phase_numbers == [1, 2, 3, 4]


async def test_run_cancellation_propagates():
    """TaskCancelledError raised by on_phase propagates out and stops later phases."""
    session = _make_session()
    sftp = MagicMock()
    tmdb = MagicMock()

    call_count = 0

    async def cancel_on_second(current: int, total: int, message: str) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise TaskCancelledError("cancelled")

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as MockTMDB,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as MockScan,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as MockDL,
        patch("jidou.orchestrators.sync_orchestrator.MatchOrchestrator") as MockMatch,
    ):
        MockTMDB.return_value.sync_all_shows = AsyncMock(return_value=_make_tmdb_result())
        MockScan.return_value.run = AsyncMock(return_value=_make_scan_result())
        MockDL.return_value.run = AsyncMock(return_value=_make_download_result())
        MockMatch.return_value.run = AsyncMock(return_value=_make_match_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        with pytest.raises(TaskCancelledError):
            await orch.run(on_phase=cancel_on_second)

    # Phase 3 (Download) should never have run
    MockDL.return_value.run.assert_not_called()
