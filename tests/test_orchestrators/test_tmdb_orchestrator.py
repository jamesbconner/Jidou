"""Tests for TMDBOrchestrator."""

from unittest.mock import AsyncMock, MagicMock

from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator


def _make_session(existing_episode=None):
    """Build a mock session where execute returns no existing episodes by default."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = existing_episode
    session.execute = AsyncMock(return_value=ep_result)
    return session


def _make_session_with_shows(shows, existing_episode=None):
    """Build a session that returns a show list first, then episode lookups."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()

    show_result = MagicMock()
    show_result.scalars.return_value.all.return_value = shows

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = existing_episode

    session.execute = AsyncMock(side_effect=[show_result] + [ep_result] * 20)
    return session


def _make_show(tmdb_id=12345, title="Test Show", cached=False, show_id=1):
    show = MagicMock()
    show.id = show_id
    show.tmdb_id = tmdb_id
    show.title = title
    show.cached = cached
    return show


def _make_tmdb(seasons=None, episodes=None):
    tmdb = AsyncMock()
    tmdb.get_show_seasons = AsyncMock(
        return_value={"seasons": seasons or [{"season_number": 1}]}
    )
    tmdb.get_season_details = AsyncMock(
        return_value={
            "episodes": episodes
            or [
                {"id": 101, "episode_number": 1, "name": "Ep1"},
                {"id": 102, "episode_number": 2, "name": "Ep2"},
            ]
        }
    )
    return tmdb


async def test_sync_show_episodes_upserts_new_episodes():
    """New episodes are added to the session when they don't exist."""
    session = _make_session(existing_episode=None)
    show = _make_show()
    tmdb = _make_tmdb()

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_show_episodes(show)

    assert result.episodes_upserted == 2
    assert result.episodes_skipped == 0
    assert result.shows_synced == 1
    assert session.add.call_count == 2
    assert show.cached is True
    session.commit.assert_called_once()


async def test_sync_show_episodes_updates_existing():
    """Existing episodes are updated in place without calling session.add."""
    existing = MagicMock()
    existing.name = "Old Name"

    session = _make_session(existing_episode=existing)
    show = _make_show()
    tmdb = _make_tmdb(episodes=[{"id": 101, "episode_number": 1, "name": "New Name"}])

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_show_episodes(show)

    assert result.episodes_skipped == 1
    assert result.episodes_upserted == 0
    assert existing.name == "New Name"
    session.add.assert_not_called()


async def test_sync_show_episodes_skips_season_zero():
    """Season 0 (specials) must be excluded from syncing."""
    session = _make_session(existing_episode=None)
    show = _make_show()
    tmdb = _make_tmdb(
        seasons=[{"season_number": 0}, {"season_number": 1}],
        episodes=[{"id": 201, "episode_number": 1, "name": "Ep1"}],
    )

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    # get_season_details should only be called for season 1, not season 0
    tmdb.get_season_details.assert_called_once_with(show.tmdb_id, 1)


async def test_sync_all_shows_skips_cached():
    """Shows with cached=True are excluded from the query, only uncached are synced."""
    uncached = _make_show(cached=False, show_id=1)

    session = _make_session_with_shows(shows=[uncached], existing_episode=None)
    tmdb = _make_tmdb(
        seasons=[{"season_number": 1}],
        episodes=[{"id": 101, "episode_number": 1, "name": "Ep1"}],
    )

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_all_shows()

    # Only the uncached show should be synced
    assert result.shows_synced == 1
    assert tmdb.get_show_seasons.call_count == 1


async def test_sync_all_shows_continues_on_error():
    """If the first show fails, the second show is still processed."""
    show1 = _make_show(tmdb_id=111, show_id=1)
    show2 = _make_show(tmdb_id=222, show_id=2)

    session = _make_session_with_shows(shows=[show1, show2], existing_episode=None)

    tmdb = AsyncMock()
    # First show raises, second succeeds
    tmdb.get_show_seasons = AsyncMock(
        side_effect=[
            Exception("TMDB error"),
            {"seasons": [{"season_number": 1}]},
        ]
    )
    tmdb.get_season_details = AsyncMock(
        return_value={"episodes": [{"id": 201, "episode_number": 1, "name": "Ep1"}]}
    )

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_all_shows()

    assert result.shows_synced == 1  # only second show succeeded
    assert tmdb.get_show_seasons.call_count == 2


async def test_on_progress_called_per_season():
    """on_progress callback is invoked once per season."""
    session = _make_session(existing_episode=None)
    show = _make_show()
    tmdb = _make_tmdb(
        seasons=[
            {"season_number": 1},
            {"season_number": 2},
            {"season_number": 3},
        ],
        episodes=[{"id": 101, "episode_number": 1, "name": "Ep1"}],
    )

    on_progress = AsyncMock()
    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show, on_progress=on_progress)

    assert on_progress.call_count == 3
