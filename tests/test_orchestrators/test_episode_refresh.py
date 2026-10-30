"""Tests for TMDBEpisodeRefresher, the parse step's on-demand episode refresh."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators._episode_refresh import TMDBEpisodeRefresher
from jidou.orchestrators.tmdb_orchestrator import TMDBSyncResult

_SYNC = "jidou.orchestrators._episode_refresh.TMDBOrchestrator.sync_show_episodes"


def _session() -> tuple[MagicMock, dict[str, bool]]:
    """Session whose ``begin_nested`` records whether its block exited with an error."""
    state = {"entered": False, "failed": False}

    @asynccontextmanager
    async def _nested():
        state["entered"] = True
        try:
            yield
        except BaseException:
            state["failed"] = True
            raise

    session = MagicMock()
    session.begin_nested = _nested
    session.refresh = AsyncMock()
    return session, state


def _show() -> MagicMock:
    show = MagicMock()
    show.id = 7
    show.title = "Test Show"
    return show


@pytest.mark.parametrize(("upserted", "expected"), [(3, True), (0, False)])
async def test_returns_whether_new_episodes_arrived(upserted, expected):
    """True only when the sync upserted at least one new episode row."""
    session, state = _session()
    result = TMDBSyncResult(shows_synced=1, episodes_upserted=upserted, episodes_skipped=10)

    with patch(_SYNC, AsyncMock(return_value=result)):
        refreshed = await TMDBEpisodeRefresher(session, MagicMock()).refresh_episodes(_show())

    assert refreshed is expected
    assert state["entered"]
    assert not state["failed"]


async def test_bypasses_the_tmdb_cache():
    """A new season cannot be seen through a cached response."""
    session, _ = _session()
    show = _show()
    sync = AsyncMock(return_value=TMDBSyncResult.empty())

    with patch(_SYNC, sync):
        await TMDBEpisodeRefresher(session, MagicMock()).refresh_episodes(show)

    sync.assert_awaited_once_with(show, bypass_cache=True)


async def test_failure_is_swallowed_rolled_back_and_reported_as_nothing_new(caplog):
    """A TMDB failure discards only the savepoint and does not raise."""
    session, state = _session()
    show = _show()

    with patch(_SYNC, AsyncMock(side_effect=RuntimeError("tmdb down"))):
        refreshed = await TMDBEpisodeRefresher(session, MagicMock()).refresh_episodes(show)

    assert refreshed is False
    assert state["failed"]  # the savepoint block saw the error, so it rolls back
    session.refresh.assert_awaited_once_with(show)
    assert "Episode refresh failed" in caplog.text
