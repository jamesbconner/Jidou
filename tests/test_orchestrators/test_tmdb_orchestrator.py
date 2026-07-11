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
    tmdb.get_show_seasons = AsyncMock(return_value={"seasons": seasons or [{"season_number": 1}]})
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
    # sync_show_episodes flushes but never commits -- the caller owns the
    # transaction boundary (see sync_all_shows for the per-show commit).
    session.flush.assert_awaited()
    session.commit.assert_not_called()


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


# Shaped after Frieren: Beyond Journey's End's real TMDB episode_groups (a
# single absolute-numbered season, split by a type-6 "Seasons" group into a
# fansub-style Season 1 / Specials / Season 2 breakdown), scaled down for
# test speed (3 + 2 episodes instead of 28 + 10).
_SEASONS_GROUP_SUMMARY = [
    {"id": "seasons-group-id", "name": "Seasons", "type": 6, "episode_count": 5, "group_count": 3},
]

_SEASONS_GROUP_DETAIL = {
    "id": "seasons-group-id",
    "name": "Seasons",
    "groups": [
        {
            "name": "Specials",
            "order": 0,
            "episodes": [
                {"id": 901, "season_number": 0, "episode_number": 1, "order": 0},
            ],
        },
        {
            "name": "Season 1",
            "order": 1,
            "episodes": [
                {"id": 101, "season_number": 1, "episode_number": 1, "order": 0},
                {"id": 102, "season_number": 1, "episode_number": 2, "order": 1},
                {"id": 103, "season_number": 1, "episode_number": 3, "order": 2},
            ],
        },
        {
            "name": "Season 2",
            "order": 2,
            "episodes": [
                {"id": 104, "season_number": 1, "episode_number": 4, "order": 0},
                {"id": 105, "season_number": 1, "episode_number": 5, "order": 1},
            ],
        },
    ],
}


async def test_sync_show_episodes_populates_episode_group_map():
    """A type-6 episode_groups breakdown is resolved into Show.episode_group_map."""
    session = _make_session(existing_episode=None)
    show = _make_show()
    show.episode_groups = _SEASONS_GROUP_SUMMARY
    tmdb = _make_tmdb(
        seasons=[{"season_number": 1}],
        episodes=[
            {"id": 101, "episode_number": 1, "name": "Ep1"},
            {"id": 102, "episode_number": 2, "name": "Ep2"},
            {"id": 103, "episode_number": 3, "name": "Ep3"},
            {"id": 104, "episode_number": 4, "name": "Ep4"},
            {"id": 105, "episode_number": 5, "name": "Ep5"},
        ],
    )
    tmdb.get_episode_group = AsyncMock(return_value=_SEASONS_GROUP_DETAIL)

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    assert show.episode_group_map == {
        "6": {
            "1": {"1": [1, 1], "2": [1, 2], "3": [1, 3]},
            "2": {"1": [1, 4], "2": [1, 5]},
        }
    }
    tmdb.get_episode_group.assert_called_once_with("seasons-group-id")


async def test_sync_show_episodes_backfills_absolute_episode_number():
    """Episodes newly synced this run get absolute_episode_number from the type-6 breakdown.

    No type-2 ("Absolute") group exists on this show, so flatten_for_absolute_numbering
    falls back to type 6, concatenating its sub-groups (excluding Specials) in
    order: Season 1 (3 eps) then Season 2 (2 eps) -> absolute 1-5.
    """
    session = _make_session(existing_episode=None)
    show = _make_show()
    show.episode_groups = _SEASONS_GROUP_SUMMARY
    tmdb = _make_tmdb(
        seasons=[{"season_number": 1}],
        episodes=[
            {"id": 101, "episode_number": 1, "name": "Ep1"},
            {"id": 102, "episode_number": 2, "name": "Ep2"},
            {"id": 103, "episode_number": 3, "name": "Ep3"},
            {"id": 104, "episode_number": 4, "name": "Ep4"},
            {"id": 105, "episode_number": 5, "name": "Ep5"},
        ],
    )
    tmdb.get_episode_group = AsyncMock(return_value=_SEASONS_GROUP_DETAIL)

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    added_episodes = {call.args[0].tmdb_id: call.args[0] for call in session.add.call_args_list}
    assert added_episodes[101].absolute_episode_number == 1
    assert added_episodes[102].absolute_episode_number == 2
    assert added_episodes[103].absolute_episode_number == 3
    assert added_episodes[104].absolute_episode_number == 4
    assert added_episodes[105].absolute_episode_number == 5


async def test_sync_show_episodes_no_episode_groups_leaves_map_none():
    """A show with no episode_groups at all never calls get_episode_group and stores no map."""
    session = _make_session(existing_episode=None)
    show = _make_show()
    show.episode_groups = None
    tmdb = _make_tmdb()

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    assert show.episode_group_map is None
    tmdb.get_episode_group.assert_not_called()


async def test_sync_show_episodes_group_fetch_failure_does_not_abort_sync():
    """A failed episode_group detail fetch is best-effort -- the episode sync still completes."""
    session = _make_session(existing_episode=None)
    show = _make_show()
    show.episode_groups = _SEASONS_GROUP_SUMMARY
    tmdb = _make_tmdb()
    tmdb.get_episode_group = AsyncMock(side_effect=Exception("TMDB down"))

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_show_episodes(show)

    assert result.episodes_upserted == 2
    assert show.episode_group_map is None


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


async def test_sync_all_shows_commits_after_each_successful_show():
    """A later show's failure must not roll back an earlier show's success.

    Regression test: sync_show_episodes only flushes now (the caller owns
    the commit boundary), so sync_all_shows must commit after each show it
    successfully syncs -- otherwise a mid-batch failure's rollback() would
    discard every prior show's uncommitted work in the same transaction,
    even though the result summary reports them as synced.
    """
    show1 = _make_show(tmdb_id=111, show_id=1)
    show2 = _make_show(tmdb_id=222, show_id=2)
    show3 = _make_show(tmdb_id=333, show_id=3)

    session = _make_session_with_shows(shows=[show1, show2, show3], existing_episode=None)

    tmdb = AsyncMock()
    # Show 1 succeeds, show 2 raises, show 3 succeeds.
    tmdb.get_show_seasons = AsyncMock(
        side_effect=[
            {"seasons": [{"season_number": 1}]},
            Exception("TMDB error"),
            {"seasons": [{"season_number": 1}]},
        ]
    )
    tmdb.get_season_details = AsyncMock(
        return_value={"episodes": [{"id": 201, "episode_number": 1, "name": "Ep1"}]}
    )

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_all_shows()

    assert result.shows_synced == 2  # shows 1 and 3
    # One commit per successful show (1 and 3); one rollback for show 2.
    assert session.commit.await_count == 2
    session.rollback.assert_awaited_once()


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
