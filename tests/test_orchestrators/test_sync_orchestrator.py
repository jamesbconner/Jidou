"""Tests for SyncOrchestrator."""

from contextlib import ExitStack
from typing import Any
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

    assert result.tmdb.shows_synced == 0
    session.rollback.assert_called_once()


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


async def test_run_scan_summary_includes_already_known_count():
    """The Scan phase summary reports both new and already-known counts.

    ScanOrchestrator itself only emits per-item events for newly discovered
    files (a library scan can skip thousands of already-known files, which
    would drown the log) -- so the phase-summary line SyncOrchestrator emits
    is the only place the "already known" count is visible, and must include it.
    """
    session = _make_session()
    sftp = MagicMock()
    sftp.max_workers = 4
    tmdb = MagicMock()

    on_event = AsyncMock()
    scan_res = _make_scan_result(files_created=3, files_skipped=1204)

    with (
        patch("jidou.orchestrators.sync_orchestrator.TMDBOrchestrator") as mock_tmdb_cls,
        patch("jidou.orchestrators.sync_orchestrator.ScanOrchestrator") as mock_scan_cls,
        patch("jidou.orchestrators.sync_orchestrator.DownloadOrchestrator") as mock_dl_cls,
        patch("jidou.orchestrators.sync_orchestrator.ParseOrchestrator") as mock_parse_cls,
        patch("jidou.orchestrators.sync_orchestrator.RouteOrchestrator") as mock_route_cls,
    ):
        mock_tmdb_cls.return_value.sync_all_shows = AsyncMock(return_value=_make_tmdb_result())
        mock_scan_cls.return_value.run = AsyncMock(return_value=scan_res)
        mock_dl_cls.return_value.run = AsyncMock(return_value=_make_download_result())
        mock_parse_cls.return_value.run = AsyncMock(return_value=_make_parse_result())
        mock_route_cls.return_value.run = AsyncMock(return_value=_make_route_result())

        orch = SyncOrchestrator(session, sftp, tmdb)
        await orch.run(on_event=on_event)

    scan_messages = [c[0][1] for c in on_event.call_args_list if c[0][1].startswith("Scan:")]
    assert len(scan_messages) == 1
    assert "3 new file(s) discovered" in scan_messages[0]
    assert "1204 already known" in scan_messages[0]


async def test_run_on_event_forwarded_to_every_sub_orchestrator():
    """on_event must reach Scan/Download/Parse/Route, not just Route.

    Regression test: SyncOrchestrator used to forward on_event only to
    RouteOrchestrator, so the task log only ever showed per-file detail for
    the routing phase -- Scan/Download/Parse collapsed to a single
    one-line phase summary even though all four orchestrators support the
    same structured per-item event callback.
    """
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

    for mock_cls in (mock_scan_cls, mock_dl_cls, mock_parse_cls, mock_route_cls):
        mock_cls.return_value.run.assert_called_once()
        call_kwargs = mock_cls.return_value.run.call_args.kwargs
        assert call_kwargs.get("on_event") is on_event


# ---------------------------------------------------------------------------
# Characterization tests (ORC-7): pin the observable sequence of the pipeline
# -- external calls, events, progress ticks, commit/rollback -- so the phase
# split cannot reorder or drop any of it, including on failure paths.
# ---------------------------------------------------------------------------

_PATCH_BASE = "jidou.orchestrators.sync_orchestrator"


def _scripted_session(calls: list[str], results: list[object]) -> MagicMock:
    """Session whose execute() returns *results* in order and logs every DB call."""
    session = MagicMock()
    queue = list(results)

    async def execute(*_args: object, **_kwargs: object) -> object:
        calls.append("db.execute")
        if not queue:
            raise AssertionError("unexpected extra session.execute() call")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def commit() -> None:
        calls.append("db.commit")

    async def rollback() -> None:
        calls.append("db.rollback")

    async def flush() -> None:
        calls.append("db.flush")

    session.execute = execute
    session.commit = commit
    session.rollback = rollback
    session.flush = flush
    return session


def _scalar_one_or_none(value: object) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _scalar(value: object) -> MagicMock:
    res = MagicMock()
    res.scalar.return_value = value
    return res


def _scalars_all(values: list[object]) -> MagicMock:
    res = MagicMock()
    res.scalars.return_value.all.return_value = values
    return res


def _patched_pipeline(calls: list[str]) -> tuple[ExitStack, dict[str, MagicMock]]:
    """Patch the five sub-orchestrators; each ``run`` appends to *calls*."""

    def make(name: str, result: object) -> MagicMock:
        cls = MagicMock()

        async def run(**kwargs: object) -> object:
            calls.append(f"{name}.run")
            return result

        cls.return_value.run = run
        return cls

    stack = ExitStack()
    mocks: dict[str, MagicMock] = {}
    for key, name, result in (
        ("ScanOrchestrator", "scan", _make_scan_result()),
        ("DownloadOrchestrator", "download", _make_download_result()),
        ("ParseOrchestrator", "parse", _make_parse_result()),
        ("RouteOrchestrator", "route", _make_route_result()),
    ):
        mocks[key] = stack.enter_context(patch(f"{_PATCH_BASE}.{key}", make(name, result)))
    tmdb_cls = stack.enter_context(patch(f"{_PATCH_BASE}.TMDBOrchestrator"))

    async def sync_all() -> TMDBSyncResult:
        calls.append("tmdb.sync_all_shows")
        return _make_tmdb_result()

    tmdb_cls.return_value.sync_all_shows = sync_all
    mocks["TMDBOrchestrator"] = tmdb_cls
    return stack, mocks


def _recorders(calls: list[str]) -> tuple[Any, Any]:
    async def on_phase(current: int, total: int, message: str) -> None:
        calls.append(f"phase:{current}/{total}:{message}")

    async def on_event(level: str, message: str, ctx: dict[str, Any] | None = None) -> None:
        calls.append(f"event:{level}:{message}")

    return on_phase, on_event


def _sftp() -> MagicMock:
    sftp = MagicMock()
    sftp.max_workers = 4
    return sftp


def _cached_show(*, cached: bool, show_id: int = 7) -> MagicMock:
    show = MagicMock()
    show.id = show_id
    show.cached = cached
    return show


async def test_characterize_full_run_call_order_all_shows():
    """Phase ticks, TMDB/sub-orchestrator calls and summary events interleave in order."""
    calls: list[str] = []
    session = _scripted_session(calls, [_scalars_all([])])  # phase 4.5 gap query only
    on_phase, on_event = _recorders(calls)
    stack, _ = _patched_pipeline(calls)
    with stack:
        await SyncOrchestrator(session, _sftp(), MagicMock()).run(
            on_phase=on_phase, on_event=on_event
        )

    assert calls == [
        "phase:1/5:Syncing TMDB episode data",
        "tmdb.sync_all_shows",
        "event:info:TMDB sync: 1 shows refreshed, 5 episodes upserted",
        "phase:2/5:Scanning remote files",
        "scan.run",
        "event:info:Scan: 3 new file(s) discovered, 0 already known",
        "phase:3/5:Downloading new files",
        "download.run",
        "event:info:Download: 3 file(s) downloaded",
        "phase:4/5:Parsing and matching files to shows",
        "parse.run",
        "event:info:Parse: 3 file(s) matched to shows",
        "db.execute",  # phase 4.5 gap query
        "phase:5/5:Routing matched files",
        "route.run",
        "event:info:Route: 3 file(s) routed to final paths",
    ]


async def test_characterize_dry_run_call_order_and_event_suffixes():
    """Dry run: no TMDB, no gap fill, no DB access; suffixes and zero TMDB counts pinned."""
    calls: list[str] = []
    session = _scripted_session(calls, [])
    events: list[tuple[str, str, dict[str, Any] | None]] = []

    async def on_event(level: str, message: str, ctx: dict[str, Any] | None = None) -> None:
        calls.append(f"event:{message}")
        events.append((level, message, ctx))

    stack, mocks = _patched_pipeline(calls)
    with stack:
        result = await SyncOrchestrator(session, _sftp(), MagicMock()).run(
            dry_run=True, on_event=on_event
        )

    mocks["TMDBOrchestrator"].assert_not_called()
    assert calls == [
        "event:TMDB sync: 0 shows refreshed, 0 episodes upserted (skipped — dry run)",
        "scan.run",
        "event:Scan: 3 new file(s) discovered, 0 already known (dry run)",
        "download.run",
        "event:Download: 3 file(s) downloaded (dry run)",
        "parse.run",
        "event:Parse: 3 file(s) matched to shows (dry run)",
        "route.run",
        "event:Route: 3 file(s) routed to final paths (dry run)",
    ]
    assert result.tmdb == TMDBSyncResult(0, 0, 0)
    assert [e[0] for e in events] == ["info"] * 5
    assert events[0][2] == {"shows_synced": 0, "episodes_upserted": 0}
    assert events[1][2] == {"files_created": 3, "files_skipped": 0}
    assert events[2][2] == {"files_downloaded": 3}
    assert events[3][2] == {"files_matched": 3}
    assert events[4][2] == {"files_routed": 3}


async def test_characterize_single_show_sync_commits_before_scan():
    """show_id sync: select show, episode-exists check, sync, commit, then later phases."""
    calls: list[str] = []
    show = _cached_show(cached=False)
    session = _scripted_session(calls, [_scalar_one_or_none(show), _scalar(True), _scalars_all([])])
    stack, mocks = _patched_pipeline(calls)

    async def sync_show(s: object) -> TMDBSyncResult:
        calls.append("tmdb.sync_show_episodes")
        assert s is show
        return TMDBSyncResult(1, 9, 2)

    with stack:
        mocks["TMDBOrchestrator"].return_value.sync_show_episodes = sync_show
        result = await SyncOrchestrator(session, _sftp(), MagicMock()).run(show_id=7)

    assert calls == [
        "db.execute",  # select show
        "db.execute",  # episodes-exist check
        "tmdb.sync_show_episodes",
        "db.commit",
        "scan.run",
        "download.run",
        "parse.run",
        "db.execute",  # gap query
        "route.run",
    ]
    assert result.tmdb == TMDBSyncResult(1, 9, 2)


async def test_characterize_cached_show_with_episodes_skips_sync_but_builds_orchestrator():
    """Cached show with episodes: empty TMDB result, orchestrator still built for gap fill."""
    calls: list[str] = []
    session = _scripted_session(
        calls, [_scalar_one_or_none(_cached_show(cached=True)), _scalar(True), _scalars_all([])]
    )
    stack, mocks = _patched_pipeline(calls)
    with stack:
        result = await SyncOrchestrator(session, _sftp(), MagicMock()).run(show_id=7)

    mocks["TMDBOrchestrator"].assert_called_once()
    assert result.tmdb == TMDBSyncResult(0, 0, 0)
    assert "db.commit" not in calls
    assert calls.count("db.execute") == 3  # show, exists, gap query (gap fill ran)


async def test_characterize_cached_show_without_episodes_still_syncs():
    """show.cached=True but no Episode rows: the sync still runs."""
    calls: list[str] = []
    session = _scripted_session(
        calls, [_scalar_one_or_none(_cached_show(cached=True)), _scalar(False), _scalars_all([])]
    )
    stack, mocks = _patched_pipeline(calls)
    mocks["TMDBOrchestrator"].return_value.sync_show_episodes = AsyncMock(
        return_value=TMDBSyncResult(1, 2, 0)
    )
    with stack:
        result = await SyncOrchestrator(session, _sftp(), MagicMock()).run(show_id=7)

    mocks["TMDBOrchestrator"].return_value.sync_show_episodes.assert_awaited_once()
    assert result.tmdb == TMDBSyncResult(1, 2, 0)
    assert calls[:4] == ["db.execute", "db.execute", "db.commit", "scan.run"]


async def test_characterize_missing_show_still_builds_orchestrator_for_gap_fill():
    """Spec section 6 item 5: show_id not in DB gives an empty result, and gap fill still runs."""
    calls: list[str] = []
    session = _scripted_session(calls, [_scalar_one_or_none(None), _scalars_all([])])
    stack, mocks = _patched_pipeline(calls)
    with stack:
        result = await SyncOrchestrator(session, _sftp(), MagicMock()).run(show_id=99)

    mocks["TMDBOrchestrator"].assert_called_once()
    assert result.tmdb == TMDBSyncResult(0, 0, 0)
    assert calls == [
        "db.execute",  # select show
        "scan.run",
        "download.run",
        "parse.run",
        "db.execute",  # gap query proves _fill_missing_episodes ran
        "route.run",
    ]


async def test_characterize_tmdb_failure_rolls_back_then_continues_in_order():
    """sync_show_episodes failure: rollback (no commit), zero counts, pipeline continues."""
    calls: list[str] = []
    session = _scripted_session(
        calls,
        [
            _scalar_one_or_none(_cached_show(cached=False, show_id=5)),
            _scalar(False),
            _scalars_all([]),
        ],
    )
    on_phase, on_event = _recorders(calls)
    stack, mocks = _patched_pipeline(calls)
    mocks["TMDBOrchestrator"].return_value.sync_show_episodes = AsyncMock(
        side_effect=RuntimeError("TMDB API down")
    )
    with stack:
        result = await SyncOrchestrator(session, _sftp(), MagicMock()).run(
            show_id=5, on_phase=on_phase, on_event=on_event
        )

    assert result.tmdb == TMDBSyncResult(0, 0, 0)
    assert calls[:6] == [
        "phase:1/5:Syncing TMDB episode data",
        "db.execute",
        "db.execute",
        "db.rollback",
        "event:info:TMDB sync: 0 shows refreshed, 0 episodes upserted",
        "phase:2/5:Scanning remote files",
    ]
    assert "db.commit" not in calls


async def test_raising_on_event_is_swallowed_in_tmdb_summary():
    """A raising on_event is swallowed by sync: the scan and later phases still run."""
    calls: list[str] = []
    session = _scripted_session(calls, [_scalars_all([])])  # gap query only

    async def boom(level: str, message: str, ctx: dict[str, Any] | None = None) -> None:
        calls.append("event")
        raise RuntimeError("sink down")

    stack, _ = _patched_pipeline(calls)
    with stack:
        await SyncOrchestrator(session, _sftp(), MagicMock()).run(on_event=boom)

    assert calls[:3] == ["tmdb.sync_all_shows", "event", "scan.run"]
    assert "route.run" in calls


async def test_raising_on_event_is_swallowed_in_parse_summary():
    """An on_event failure after Parse is swallowed: gap fill and Route still run."""
    calls: list[str] = []
    session = _scripted_session(calls, [_scalars_all([])])  # gap query only

    async def boom_on_parse(level: str, message: str, ctx: dict[str, Any] | None = None) -> None:
        if message.startswith("Parse:"):
            raise RuntimeError("sink down")

    stack, _ = _patched_pipeline(calls)
    with stack:
        await SyncOrchestrator(session, _sftp(), MagicMock()).run(on_event=boom_on_parse)

    assert calls[:4] == ["tmdb.sync_all_shows", "scan.run", "download.run", "parse.run"]
    assert "route.run" in calls


async def test_characterize_cancellation_at_phase_5_after_gap_fill():
    """Cancelling at the phase-5 tick leaves Parse and the gap fill done, Route unrun."""
    calls: list[str] = []
    session = _scripted_session(calls, [_scalars_all([])])

    async def on_phase(current: int, total: int, message: str) -> None:
        calls.append(f"phase:{current}")
        if current == 5:
            raise TaskCancelledError("cancelled")

    stack, _ = _patched_pipeline(calls)
    with stack, pytest.raises(TaskCancelledError):
        await SyncOrchestrator(session, _sftp(), MagicMock()).run(on_phase=on_phase)

    assert calls == [
        "phase:1",
        "tmdb.sync_all_shows",
        "phase:2",
        "scan.run",
        "phase:3",
        "download.run",
        "phase:4",
        "parse.run",
        "db.execute",
        "phase:5",
    ]


async def test_characterize_cancellation_at_phase_1_builds_nothing():
    """Cancelling at the first tick means no TMDB orchestrator is built and nothing runs."""
    calls: list[str] = []
    session = _scripted_session(calls, [])

    async def on_phase(current: int, total: int, message: str) -> None:
        raise TaskCancelledError("cancelled")

    stack, mocks = _patched_pipeline(calls)
    with stack, pytest.raises(TaskCancelledError):
        await SyncOrchestrator(session, _sftp(), MagicMock()).run(on_phase=on_phase)

    mocks["TMDBOrchestrator"].assert_not_called()
    assert calls == []


def _gap_file(file_id: int, season: int | None = None) -> MagicMock:
    f = MagicMock()
    f.id = file_id
    f.original_filename = f"file{file_id}.mkv"
    f.parsed_season = season
    f.parsed_episode = 3
    f.episode_id = None
    return f


async def test_characterize_gap_fill_commits_per_show_and_backfills_season():
    """Per show: select show, resync, retry select, resolve each file, commit; season backfill."""
    calls: list[str] = []
    f_none, f_set, f_unresolved = _gap_file(1), _gap_file(2, season=1), _gap_file(3)
    session = _scripted_session(
        calls,
        [
            _scalars_all([1, 2]),
            _scalar_one_or_none(MagicMock()),
            _scalars_all([f_none, f_set, f_unresolved]),
            _scalar_one_or_none(MagicMock()),
            _scalars_all([]),
        ],
    )
    tmdb_orch = MagicMock()

    async def sync_show(show: object) -> None:
        calls.append("tmdb.sync_show_episodes")

    tmdb_orch.sync_show_episodes = sync_show
    ep = MagicMock()
    ep.id = 55
    ep.season_number = 2
    outcomes = iter([ep, ep, None])

    async def resolve(_s: object, sid: int, season: int | None, episode: int | None) -> object:
        calls.append(f"resolve:{sid}:{season}:{episode}")
        return next(outcomes)

    with patch(f"{_PATCH_BASE}.resolve_episode", resolve):
        await SyncOrchestrator(session, _sftp(), MagicMock())._fill_missing_episodes(tmdb_orch)

    assert calls == [
        "db.execute",  # gap query
        "db.execute",  # show 1
        "tmdb.sync_show_episodes",
        "db.execute",  # retry files
        "resolve:1:None:3",
        "resolve:1:1:3",
        "resolve:1:None:3",
        "db.commit",
        "db.execute",  # show 2
        "tmdb.sync_show_episodes",
        "db.execute",
        "db.commit",
    ]
    assert f_none.episode_id == 55 and f_none.parsed_season == 2  # backfilled
    assert f_set.episode_id == 55 and f_set.parsed_season == 1  # left alone
    assert f_unresolved.episode_id is None and f_unresolved.parsed_season is None


async def test_characterize_gap_fill_db_error_mid_show_rolls_back_and_continues():
    """A failing resync rolls back and skips that show (no commit); later shows still commit."""
    calls: list[str] = []
    f = _gap_file(9)
    session = _scripted_session(
        calls,
        [
            _scalars_all([1, 2]),
            _scalar_one_or_none(MagicMock()),
            _scalar_one_or_none(MagicMock()),
            _scalars_all([f]),
        ],
    )
    tmdb_orch = MagicMock()
    attempts = 0

    async def sync_show(show: object) -> None:
        nonlocal attempts
        attempts += 1
        calls.append(f"tmdb.sync:{attempts}")
        if attempts == 1:
            raise RuntimeError("db boom")

    tmdb_orch.sync_show_episodes = sync_show
    ep = MagicMock()
    ep.id = 4
    ep.season_number = 1
    with patch(f"{_PATCH_BASE}.resolve_episode", AsyncMock(return_value=ep)):
        await SyncOrchestrator(session, _sftp(), MagicMock())._fill_missing_episodes(tmdb_orch)

    assert calls == [
        "db.execute",
        "db.execute",
        "tmdb.sync:1",
        "db.rollback",
        "db.execute",
        "tmdb.sync:2",
        "db.execute",
        "db.commit",
    ]
    assert f.episode_id == 4


async def test_characterize_gap_fill_skips_missing_show_without_commit():
    """A show id whose row vanished is skipped: no resync, no commit."""
    calls: list[str] = []
    session = _scripted_session(calls, [_scalars_all([1]), _scalar_one_or_none(None)])
    tmdb_orch = MagicMock()
    tmdb_orch.sync_show_episodes = AsyncMock()
    await SyncOrchestrator(session, _sftp(), MagicMock())._fill_missing_episodes(tmdb_orch)

    tmdb_orch.sync_show_episodes.assert_not_called()
    assert calls == ["db.execute", "db.execute"]


async def test_characterize_gap_fill_db_error_in_retry_query_propagates_without_commit():
    """A DB error outside the resync try/except propagates and aborts the pipeline."""
    calls: list[str] = []
    session = _scripted_session(
        calls,
        [_scalars_all([1]), _scalar_one_or_none(MagicMock()), RuntimeError("db gone")],
    )
    tmdb_orch = MagicMock()
    tmdb_orch.sync_show_episodes = AsyncMock()
    with pytest.raises(RuntimeError, match="db gone"):
        await SyncOrchestrator(session, _sftp(), MagicMock())._fill_missing_episodes(tmdb_orch)

    assert "db.commit" not in calls and "db.rollback" not in calls


def test_tmdb_sync_result_empty():
    """TMDBSyncResult.empty() is the all-zero result, and each call returns a fresh object."""
    first = TMDBSyncResult.empty()
    assert first == TMDBSyncResult(shows_synced=0, episodes_upserted=0, episodes_skipped=0)
    assert TMDBSyncResult.empty() is not first


async def test_sync_tmdb_phase_missing_show_returns_empty_and_orchestrator():
    """Spec section 6 item 5: a missing show gives an empty result AND a built orchestrator."""
    calls: list[str] = []
    session = _scripted_session(calls, [_scalar_one_or_none(None)])
    with patch(f"{_PATCH_BASE}.TMDBOrchestrator") as tmdb_cls:
        orch = SyncOrchestrator(session, _sftp(), MagicMock())
        result, tmdb_orch = await orch._sync_tmdb_phase(99, False)

    assert result == TMDBSyncResult(0, 0, 0)
    assert tmdb_orch is tmdb_cls.return_value
    tmdb_cls.return_value.sync_show_episodes.assert_not_called()
    assert calls == ["db.execute"]


async def test_sync_tmdb_phase_dry_run_returns_empty_and_no_orchestrator():
    """Dry run never builds the TMDB orchestrator and never touches the DB."""
    calls: list[str] = []
    session = _scripted_session(calls, [])
    with patch(f"{_PATCH_BASE}.TMDBOrchestrator") as tmdb_cls:
        orch = SyncOrchestrator(session, _sftp(), MagicMock())
        result, tmdb_orch = await orch._sync_tmdb_phase(None, True)

    assert result == TMDBSyncResult(0, 0, 0)
    assert tmdb_orch is None
    tmdb_cls.assert_not_called()
    assert calls == []


def test_dry_run_suffix():
    """The suffix helper keeps the exact wording used by the phase summaries."""
    from jidou.orchestrators.sync_orchestrator import _dry_run_suffix

    assert _dry_run_suffix(False) == ""
    assert _dry_run_suffix(False, tmdb=True) == ""
    assert _dry_run_suffix(True) == " (dry run)"
    assert _dry_run_suffix(True, tmdb=True) == " (skipped — dry run)"
