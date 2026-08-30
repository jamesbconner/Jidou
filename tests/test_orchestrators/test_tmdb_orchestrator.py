"""Tests for TMDBOrchestrator."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator, _flatten_episode_group
from tests._fake_orchestrator_session import FakeNested


def _make_session(existing_episode=None):
    """Build a mock session where execute returns no existing episodes by default."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.begin_nested = MagicMock(return_value=FakeNested())
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
    session.begin_nested = MagicMock(return_value=FakeNested())
    session.add = MagicMock()

    show_result = MagicMock()
    show_result.scalars.return_value.all.return_value = shows

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = existing_episode

    session.execute = AsyncMock(side_effect=[show_result] + [ep_result] * 20)
    return session


def _two_shows_first_fails_second_succeeds():
    """Shared fixture for the "show1's TMDB fetch raises, show2 succeeds"
    scenario exercised by several sync_all_shows tests below.
    """
    show1 = _make_show(tmdb_id=111, show_id=1)
    show2 = _make_show(tmdb_id=222, show_id=2)
    session = _make_session_with_shows(shows=[show1, show2], existing_episode=None)

    tmdb = AsyncMock()
    tmdb.get_show_seasons = AsyncMock(
        side_effect=[
            Exception("TMDB error"),
            {"seasons": [{"season_number": 1}]},
        ]
    )
    tmdb.get_season_details = AsyncMock(
        return_value={"episodes": [{"id": 201, "episode_number": 1, "name": "Ep1"}]}
    )
    return session, tmdb, show1, show2


def _make_show(tmdb_id=12345, title="Test Show", cached=False, show_id=1, last_air_date=None):
    show = MagicMock()
    show.id = show_id
    show.tmdb_id = tmdb_id
    show.title = title
    show.cached = cached
    show.last_air_date = last_air_date
    # Default: no manually applied episode_group, so sync_show_episodes takes
    # the native get_show_seasons/get_season_details path these tests exercise.
    show.active_episode_group_id = None
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
    # Default: show has no episode_groups at all. Tests exercising the
    # on-demand summary fetch (show.episode_groups is None) override this.
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})
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


async def test_sync_show_episodes_raises_for_a_movie():
    """Movies have no TMDB /tv/{id}/season structure -- sync_show_episodes
    must reject them with a clear error rather than let the caller 404
    against an endpoint that was never going to work.
    """
    session = _make_session(existing_episode=None)
    show = _make_show()
    show.media_type = "movie"
    tmdb = _make_tmdb()

    orch = TMDBOrchestrator(session, tmdb)
    with pytest.raises(ValueError, match="movie"):
        await orch.sync_show_episodes(show)

    tmdb.get_show_seasons.assert_not_called()


async def test_sync_show_episodes_updates_last_air_date_from_newest_aired_episode():
    """A routine episode sync (not just a full rematch) should keep
    show.last_air_date current, since the Shows page "Recently Aired" sort
    reads that column directly.
    """
    session = _make_session(existing_episode=None)
    show = _make_show(last_air_date=None)
    yesterday = date.today() - timedelta(days=1)
    last_week = date.today() - timedelta(days=7)
    tmdb = _make_tmdb(
        episodes=[
            {"id": 101, "episode_number": 1, "name": "Ep1", "air_date": last_week.isoformat()},
            {"id": 102, "episode_number": 2, "name": "Ep2", "air_date": yesterday.isoformat()},
        ]
    )

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    assert show.last_air_date == yesterday.isoformat()


async def test_sync_show_episodes_ignores_unaired_future_episodes():
    """A scheduled-but-unaired episode must not push last_air_date forward --
    only episodes that have actually aired count.
    """
    session = _make_session(existing_episode=None)
    show = _make_show(last_air_date=None)
    yesterday = date.today() - timedelta(days=1)
    next_week = date.today() + timedelta(days=7)
    tmdb = _make_tmdb(
        episodes=[
            {"id": 101, "episode_number": 1, "name": "Ep1", "air_date": yesterday.isoformat()},
            {"id": 102, "episode_number": 2, "name": "Ep2", "air_date": next_week.isoformat()},
        ]
    )

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    assert show.last_air_date == yesterday.isoformat()


async def test_sync_show_episodes_leaves_last_air_date_when_nothing_has_aired():
    """No aired episodes in the synced set (e.g. a brand-new unreleased show)
    must leave any previously-known last_air_date untouched rather than
    clobbering it with None.
    """
    session = _make_session(existing_episode=None)
    show = _make_show(last_air_date="2020-01-01")
    next_week = date.today() + timedelta(days=7)
    tmdb = _make_tmdb(
        episodes=[
            {"id": 101, "episode_number": 1, "name": "Ep1", "air_date": next_week.isoformat()},
        ]
    )

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    assert show.last_air_date == "2020-01-01"


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


async def test_sync_show_episodes_never_checked_episode_groups_fetches_summary_on_demand():
    """Bugbot-caught regression: show.episode_groups is only populated by
    fetch_show_metadata, which not every show-creation path calls (e.g. the
    "Add Show from search" endpoint). None means "never checked" and must be
    fetched on demand here rather than silently treating the show as having
    no groups forever.
    """
    session = _make_session(existing_episode=None)
    show = _make_show()
    show.episode_groups = None
    tmdb = _make_tmdb()
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    tmdb.get_episode_groups.assert_called_once_with(show.tmdb_id)
    assert show.episode_groups == []
    assert show.episode_group_map == {}
    tmdb.get_episode_group.assert_not_called()


async def test_sync_show_episodes_already_confirmed_no_groups_does_not_refetch_summary():
    """Once episode_groups is confirmed empty ([], not None), the summary
    must not be re-fetched on every subsequent sync.
    """
    session = _make_session(existing_episode=None)
    show = _make_show()
    show.episode_groups = []
    tmdb = _make_tmdb()

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    tmdb.get_episode_groups.assert_not_called()
    assert show.episode_group_map == {}


async def test_sync_show_episodes_summary_fetch_failure_leaves_state_untouched():
    """A failed episode_groups summary fetch must not clear a previously
    successful map, same contract as the per-group-detail failure path.
    """
    existing = MagicMock()
    existing.name = "Ep1"
    existing.absolute_episode_number = 5
    session = _make_session(existing_episode=existing)
    show = _make_show()
    show.episode_groups = None
    show.episode_group_map = {"6": {"1": {"1": [1, 1]}}}
    tmdb = _make_tmdb(episodes=[{"id": 101, "episode_number": 1, "name": "Ep1"}])
    tmdb.get_episode_groups = AsyncMock(side_effect=RuntimeError("TMDB down"))

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    assert existing.absolute_episode_number == 5
    assert show.episode_group_map == {"6": {"1": {"1": [1, 1]}}}


async def test_sync_show_episodes_group_fetch_failure_does_not_abort_sync():
    """A per-type episode_group detail fetch failure is swallowed inside
    fetch_group_breakdowns itself -- the episode sync still completes, and
    the show is left with no map since neither type fetched successfully
    (this is a genuinely empty result, not a raised exception).
    """
    session = _make_session(existing_episode=None)
    show = _make_show()
    show.episode_groups = _SEASONS_GROUP_SUMMARY
    tmdb = _make_tmdb()
    tmdb.get_episode_group = AsyncMock(side_effect=Exception("TMDB down"))

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_show_episodes(show)

    assert result.episodes_upserted == 2
    assert show.episode_group_map == {}


async def test_sync_show_episodes_clears_stale_absolute_number_when_groups_now_empty():
    """A previously-backfilled absolute_episode_number must be cleared, not left
    stale, when a later successful fetch finds no applicable episode_groups --
    otherwise a show whose TMDB grouping changed (or was removed) keeps using
    numbers that no longer reflect any real grouping.
    """
    existing = MagicMock()
    existing.name = "Ep1"
    existing.absolute_episode_number = 99  # stale from an earlier sync

    session = _make_session(existing_episode=existing)
    show = _make_show()
    show.episode_groups = []  # TMDB no longer reports any qualifying group
    tmdb = _make_tmdb(episodes=[{"id": 101, "episode_number": 1, "name": "Ep1"}])

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_show_episodes(show)

    assert existing.absolute_episode_number is None
    assert show.episode_group_map == {}


async def test_sync_show_episodes_group_fetch_outer_failure_leaves_existing_state_untouched():
    """An unexpected failure while resolving episode_groups -- distinct from a
    single per-type TMDB fetch failure, which fetch_group_breakdowns already
    handles internally -- must leave show.episode_group_map and any existing
    absolute_episode_number values untouched rather than wiping them, so a
    transient failure never regresses a show that previously synced fine.
    """
    existing = MagicMock()
    existing.name = "Ep1"
    existing.absolute_episode_number = 5
    session = _make_session(existing_episode=existing)
    show = _make_show()
    show.episode_groups = _SEASONS_GROUP_SUMMARY
    show.episode_group_map = {"6": {"1": {"1": [1, 1]}}}  # a previously-successful map
    tmdb = _make_tmdb(episodes=[{"id": 101, "episode_number": 1, "name": "Ep1"}])

    orch = TMDBOrchestrator(session, tmdb)
    with patch(
        "jidou.orchestrators.tmdb_orchestrator.fetch_group_breakdowns",
        AsyncMock(side_effect=RuntimeError("unexpected")),
    ):
        await orch.sync_show_episodes(show)

    assert existing.absolute_episode_number == 5
    assert show.episode_group_map == {"6": {"1": {"1": [1, 1]}}}


class TestSyncEpisodeGroupMap:
    """Tests for the lighter, already-synced-show backfill entry point."""

    async def test_backfills_map_and_absolute_numbers_for_existing_episodes(self):
        ep1 = MagicMock(season_number=1, episode_number=1, absolute_episode_number=None)
        ep2 = MagicMock(season_number=1, episode_number=2, absolute_episode_number=None)
        ep3 = MagicMock(season_number=1, episode_number=3, absolute_episode_number=None)

        eps_result = MagicMock()
        eps_result.scalars.return_value.all.return_value = [ep1, ep2, ep3]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=eps_result)
        session.flush = AsyncMock()

        show = _make_show()
        show.episode_groups = _SEASONS_GROUP_SUMMARY
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_SEASONS_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        await orch.sync_episode_group_map(show)

        assert show.episode_group_map == {
            "6": {
                "1": {"1": [1, 1], "2": [1, 2], "3": [1, 3]},
                "2": {"1": [1, 4], "2": [1, 5]},
            }
        }
        assert ep1.absolute_episode_number == 1
        assert ep2.absolute_episode_number == 2
        assert ep3.absolute_episode_number == 3
        session.flush.assert_awaited()

    async def test_does_not_fetch_full_season_episode_data(self):
        """The lighter path must never touch get_show_seasons/get_season_details --
        that's the whole point of it existing separately from sync_show_episodes.

        Also covers the Bugbot-caught scenario this method exists for: a show
        added via a path that skips fetch_show_metadata (e.g. "Add Show from
        search") has episode_groups=None, so this must fetch the summary
        on-demand via the lightweight get_episode_groups call rather than
        silently treating the show as having no groups.
        """
        eps_result = MagicMock()
        eps_result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=eps_result)

        show = _make_show()
        show.episode_groups = None
        tmdb = AsyncMock()
        tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

        orch = TMDBOrchestrator(session, tmdb)
        await orch.sync_episode_group_map(show)

        tmdb.get_episode_groups.assert_called_once_with(show.tmdb_id)
        assert show.episode_groups == []
        tmdb.get_show_seasons.assert_not_called()
        tmdb.get_season_details.assert_not_called()

    async def test_outer_failure_leaves_existing_state_untouched(self):
        existing_ep = MagicMock(season_number=1, episode_number=1, absolute_episode_number=7)
        eps_result = MagicMock()
        eps_result.scalars.return_value.all.return_value = [existing_ep]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=eps_result)
        session.flush = AsyncMock()

        show = _make_show()
        show.episode_groups = _SEASONS_GROUP_SUMMARY
        show.episode_group_map = {"6": {"1": {"1": [1, 1]}}}
        tmdb = AsyncMock()

        orch = TMDBOrchestrator(session, tmdb)
        with patch(
            "jidou.orchestrators.tmdb_orchestrator.fetch_group_breakdowns",
            AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            await orch.sync_episode_group_map(show)

        assert existing_ep.absolute_episode_number == 7
        assert show.episode_group_map == {"6": {"1": {"1": [1, 1]}}}


class TestEnsureEpisodeGroupMap:
    """Tests for the best-effort backfill gate used by file-matching callers."""

    async def test_noops_when_a_manual_group_is_active(self):
        """Bugbot-caught regression: the type-6/2 auto-pick remap this
        backfills only makes sense against TMDB's *native* season/episode
        numbering. Once a manual group is applied, Episode.season_number/
        episode_number are that group's own numbering -- rebuilding a remap
        against the native structure would let file-matching resolve a
        declared season/episode to whatever episode happens to occupy that
        native (season, episode) pair, which is no longer the applied
        catalog at all.
        """
        session = AsyncMock()
        show = _make_show()
        show.active_episode_group_id = "us-broadcast-id"
        show.episode_group_map = None
        tmdb = AsyncMock()

        orch = TMDBOrchestrator(session, tmdb)
        await orch.ensure_episode_group_map(show)

        session.execute.assert_not_called()
        tmdb.get_episode_groups.assert_not_called()
        tmdb.get_episode_group.assert_not_called()
        assert show.episode_group_map is None

    async def test_backfills_when_no_group_is_active_and_map_is_unset(self):
        eps_result = MagicMock()
        eps_result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=3)  # ep_count precondition check
        session.execute = AsyncMock(return_value=eps_result)

        show = _make_show()
        show.active_episode_group_id = None
        show.episode_groups = []
        show.episode_group_map = None
        tmdb = AsyncMock()

        orch = TMDBOrchestrator(session, tmdb)
        await orch.ensure_episode_group_map(show)

        assert show.episode_group_map == {}


async def test_sync_all_shows_excludes_movies_from_the_query():
    """Movies have no TMDB /tv/{id} season structure -- the query sync_all_shows
    issues must filter them out rather than 404ing sync_show_episodes on every one.
    """
    session = _make_session_with_shows(shows=[], existing_episode=None)
    tmdb = _make_tmdb()

    orch = TMDBOrchestrator(session, tmdb)
    await orch.sync_all_shows()

    show_stmt = session.execute.call_args_list[0].args[0]
    compiled = str(show_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "media_type != 'movie'" in compiled


async def test_sync_all_shows_uses_savepoint_instead_of_session_rollback():
    """Regression test for a production MissingGreenlet crash -- see the
    begin_nested() comment in sync_all_shows for the full mechanism. This
    asserts the fix stays in place: begin_nested per show, and
    session.rollback() never called directly for a failure inside it.
    """
    session, tmdb, _show1, _show2 = _two_shows_first_fails_second_succeeds()

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_all_shows()

    assert result.shows_synced == 1  # show2 still processed after show1's failure
    assert session.begin_nested.call_count == 2
    session.rollback.assert_not_awaited()


async def test_sync_all_shows_show_id_survives_savepoint_rollback_for_logging():
    """Regression test for a MissingGreenlet-shaped bug in the fix itself:
    begin_nested()'s SAVEPOINT rollback expires *this* show too if it was
    mutated before the failure (e.g. show.cached = True in
    sync_show_episodes, which runs before its terminal flush()). The except
    block must log the show_id captured before entering the SAVEPOINT, not
    show.id, or the log call itself can crash with MissingGreenlet -- this
    time uncaught, aborting the whole batch instead of just this show.

    Empirically verified against a live async SQLAlchemy session
    (sqlite+aiosqlite) outside this test suite: mutating an object inside
    begin_nested(), then raising, then accessing an unrelated column on that
    same object in the except block does raise sqlalchemy.exc.MissingGreenlet.
    This test proves the orchestrator no longer does that bare access at all
    by using a show double whose .id/.tmdb_id raise if touched after the
    failure point, standing in for that real expiry.
    """

    class _ExpiringAfterMutationShow:
        """Raises if .id/.tmdb_id/.title are accessed after `poison()` is
        called -- simulates SQLAlchemy expiring a mutated object's
        attributes on SAVEPOINT rollback, without needing a real session.
        """

        def __init__(self, show_id: int, tmdb_id: int, title: str) -> None:
            self._id = show_id
            self._tmdb_id = tmdb_id
            self._title = title
            self.cached = False
            self.episode_groups = []
            self.episode_group_map = None
            self.active_episode_group_id = None
            self._poisoned = False

        def poison(self) -> None:
            self._poisoned = True

        @property
        def id(self) -> int:
            if self._poisoned:
                raise AssertionError("show.id accessed after simulated SAVEPOINT expiry")
            return self._id

        @property
        def tmdb_id(self) -> int:
            if self._poisoned:
                raise AssertionError("show.tmdb_id accessed after simulated SAVEPOINT expiry")
            return self._tmdb_id

        @property
        def title(self) -> str:
            if self._poisoned:
                raise AssertionError("show.title accessed after simulated SAVEPOINT expiry")
            return self._title

    show = _ExpiringAfterMutationShow(show_id=1, tmdb_id=111, title="Poisoned Show")
    session = _make_session_with_shows(shows=[show], existing_episode=None)  # type: ignore[list-item]

    tmdb = _make_tmdb()

    async def _flush_then_poison() -> None:
        show.poison()
        raise RuntimeError("simulated flush() failure after show.cached = True")

    session.flush = AsyncMock(side_effect=_flush_then_poison)

    orch = TMDBOrchestrator(session, tmdb)
    # Must not raise -- that's the regression under test. Before the fix,
    # this crashed with AssertionError from the poisoned .id property
    # (standing in for the real MissingGreenlet).
    result = await orch.sync_all_shows()

    assert result.shows_synced == 0


async def test_sync_all_shows_commit_failure_rolls_back_and_continues():
    """Regression test: unlike a failure inside the SAVEPOINT (contained by
    begin_nested), a session.commit() failure after a successful SAVEPOINT
    needs its own explicit rollback() -- otherwise the session is left
    unusable for every subsequent show in the batch.
    """
    show1 = _make_show(tmdb_id=111, show_id=1)
    show2 = _make_show(tmdb_id=222, show_id=2)
    session = _make_session_with_shows(shows=[show1, show2], existing_episode=None)
    session.commit = AsyncMock(side_effect=[RuntimeError("commit failed"), None])

    tmdb = _make_tmdb()

    orch = TMDBOrchestrator(session, tmdb)
    result = await orch.sync_all_shows()

    # Counts are tallied before commit() is attempted (same as the
    # pre-fix behavior -- a Python variable increment doesn't undo itself
    # when a later statement in the same try block raises), so both shows
    # are counted; what this test actually guards is that show1's commit
    # failure doesn't prevent show2 from being processed, and that the
    # session is rolled back rather than left unusable.
    assert result.shows_synced == 2
    assert tmdb.get_show_seasons.call_count == 2
    session.rollback.assert_awaited_once()


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
    session, tmdb, _show1, _show2 = _two_shows_first_fails_second_succeeds()

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
    # One commit per successful show (1 and 3). Show 2's failure is undone by
    # its own SAVEPOINT (begin_nested), not a session-wide rollback() -- see
    # test_sync_all_shows_uses_savepoint_instead_of_session_rollback above for
    # why that distinction matters.
    assert session.commit.await_count == 2
    assert session.begin_nested.call_count == 3
    session.rollback.assert_not_awaited()


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


# Shaped after the "24 native episodes, 12-combined US broadcast" scenario
# this feature exists for: a single real season plus a Specials sub-group
# that must be excluded from the applied catalog.
_US_BROADCAST_GROUP_DETAIL = {
    "id": "us-broadcast-id",
    "name": "US Broadcast Order",
    "groups": [
        {
            "name": "Specials",
            "order": 0,
            "episodes": [
                {"id": 900, "season_number": 0, "episode_number": 1, "order": 0, "name": "OVA"},
            ],
        },
        {
            "name": "Season 1",
            "order": 1,
            "episodes": [
                {
                    "id": 501,
                    "season_number": 1,
                    "episode_number": 1,
                    "order": 0,
                    "name": "Combined Ep 1",
                    "overview": "o1",
                    "air_date": "2026-01-01",
                    "runtime": 44,
                },
                {
                    "id": 502,
                    "season_number": 1,
                    "episode_number": 3,
                    "order": 1,
                    "name": "Combined Ep 2",
                    "overview": "o2",
                    "air_date": "2026-01-08",
                    "runtime": 44,
                },
            ],
        },
    ],
}


def test_flatten_episode_group_renumbers_by_sub_group_order_and_excludes_specials():
    """Sub-group order becomes season_number; position within it becomes
    episode_number -- the group is treated as an authoritative structure in
    its own right, not a remap back to native numbering. Specials (native
    season_number == 0) are dropped.
    """
    flattened = _flatten_episode_group(_US_BROADCAST_GROUP_DETAIL)

    assert [
        (e["season_number"], e["episode_number"], e["absolute_episode_number"], e["id"])
        for e in flattened
    ] == [
        (1, 1, 1, 501),
        (1, 2, 2, 502),
    ]


def _make_tracked_episode(
    *,
    id=1,
    season_number=1,
    episode_number=1,
    tracked_filename="ep.mkv",
    tracked_source="match",
    file_tracked=True,
    watched=False,
):
    ep = MagicMock()
    ep.id = id
    ep.season_number = season_number
    ep.episode_number = episode_number
    ep.file_tracked = file_tracked
    ep.watched = watched
    ep.tracked_filename = tracked_filename
    ep.tracked_source = tracked_source
    return ep


def _make_downloaded_file(*, id=1, episode_id=1):
    f = MagicMock()
    f.id = id
    f.episode_id = episode_id
    return f


def _make_apply_session(tracked_episodes=None, downloaded_files=None, episodes_removed_count=0):
    """Session double for apply_episode_group's call sequence: a tracked-
    episode select, a downloaded-file select (only issued when tracked
    episodes exist), then an Episode bulk delete. episodes_removed_count is
    answered via session.scalar(), a separate call from execute().
    """
    session = MagicMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    tracked_result = MagicMock()
    tracked_result.scalars.return_value.all.return_value = tracked_episodes or []

    execute_side_effects = [tracked_result]
    if tracked_episodes:
        files_result = MagicMock()
        files_result.scalars.return_value.all.return_value = downloaded_files or []
        execute_side_effects.append(files_result)
    execute_side_effects.append(MagicMock())  # the Episode delete statement

    session.execute = AsyncMock(side_effect=execute_side_effects)
    session.scalar = AsyncMock(return_value=episodes_removed_count)
    return session


class TestApplyEpisodeGroup:
    """Tests for the manual per-show episode_group switch."""

    async def test_raises_for_a_movie(self):
        session = _make_apply_session()
        show = _make_show()
        show.media_type = "movie"
        tmdb = AsyncMock()

        orch = TMDBOrchestrator(session, tmdb)
        with pytest.raises(ValueError, match="movie"):
            await orch.apply_episode_group(show, "us-broadcast-id")
        tmdb.get_episode_group.assert_not_called()

    async def test_deletes_old_episodes_and_inserts_group_episodes(self):
        session = _make_apply_session(episodes_removed_count=24)
        show = _make_show()
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_US_BROADCAST_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        result = await orch.apply_episode_group(show, "us-broadcast-id")

        tmdb.get_episode_group.assert_called_once_with("us-broadcast-id")
        assert result.episodes_added == 2
        assert result.episodes_removed == 24
        assert result.orphaned_file_count == 0
        added = {
            call.args[0].tmdb_id: call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], Episode)
        }
        assert set(added) == {501, 502}
        assert added[501].season_number == 1
        assert added[501].episode_number == 1
        assert added[502].episode_number == 2
        assert show.active_episode_group_id == "us-broadcast-id"
        assert show.active_episode_group_name == "US Broadcast Order"
        assert show.episode_group_map is None
        assert show.cached is True

    async def test_excludes_specials_from_the_new_catalog(self):
        session = _make_apply_session()
        show = _make_show()
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_US_BROADCAST_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        await orch.apply_episode_group(show, "us-broadcast-id")

        added_ids = {
            call.args[0].tmdb_id
            for call in session.add.call_args_list
            if isinstance(call.args[0], Episode)
        }
        assert 900 not in added_ids

    async def test_orphans_previously_tracked_episode_with_backing_file(self):
        tracked = _make_tracked_episode(
            id=11,
            season_number=1,
            episode_number=1,
            tracked_filename="f1.mkv",
            tracked_source="match",
        )
        backing_file = _make_downloaded_file(id=99, episode_id=11)
        session = _make_apply_session(tracked_episodes=[tracked], downloaded_files=[backing_file])
        show = _make_show()
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_US_BROADCAST_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        result = await orch.apply_episode_group(show, "us-broadcast-id")

        assert result.orphaned_file_count == 1
        orphans = [
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], OrphanedTrackingRecord)
        ]
        assert len(orphans) == 1
        assert orphans[0].old_season_number == 1
        assert orphans[0].old_episode_number == 1
        assert orphans[0].downloaded_file_id == 99
        assert orphans[0].tracked_source == "match"

    async def test_orphans_tracked_episode_without_backing_file_or_source(self):
        """A filename-only import (no DownloadedFile row, no tracked_source)
        must still produce a resolvable orphan record -- tracked_source
        falls back to "match" rather than violating the non-nullable column.
        """
        tracked = _make_tracked_episode(id=12, tracked_filename="imported.mkv", tracked_source=None)
        session = _make_apply_session(tracked_episodes=[tracked], downloaded_files=[])
        show = _make_show()
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_US_BROADCAST_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        result = await orch.apply_episode_group(show, "us-broadcast-id")

        assert result.orphaned_file_count == 1
        orphan = next(
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], OrphanedTrackingRecord)
        )
        assert orphan.downloaded_file_id is None
        assert orphan.tracked_source == "match"

    async def test_orphans_watched_only_episode_with_no_file_tracked(self):
        """Bugbot-caught regression: a watched-but-untracked episode has no
        DownloadedFile to relink, but must still be recorded -- otherwise
        watch history vanishes with no trace at all.
        """
        watched_only = _make_tracked_episode(
            id=13, tracked_filename=None, tracked_source=None, file_tracked=False, watched=True
        )
        session = _make_apply_session(tracked_episodes=[watched_only], downloaded_files=[])
        show = _make_show()
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_US_BROADCAST_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        result = await orch.apply_episode_group(show, "us-broadcast-id")

        assert result.orphaned_file_count == 1
        orphan = next(
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], OrphanedTrackingRecord)
        )
        assert orphan.downloaded_file_id is None

    async def test_sets_absolute_episode_number_on_new_episodes(self):
        session = _make_apply_session()
        show = _make_show()
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_US_BROADCAST_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        await orch.apply_episode_group(show, "us-broadcast-id")

        added = {
            call.args[0].tmdb_id: call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], Episode)
        }
        assert added[501].absolute_episode_number == 1
        assert added[502].absolute_episode_number == 2

    async def test_updates_last_air_date_from_newest_aired_group_episode(self):
        yesterday = date.today() - timedelta(days=1)
        last_week = date.today() - timedelta(days=7)
        detail = {
            "id": "us-broadcast-id",
            "name": "US Broadcast Order",
            "groups": [
                {
                    "name": "Season 1",
                    "order": 1,
                    "episodes": [
                        {
                            "id": 501,
                            "season_number": 1,
                            "episode_number": 1,
                            "order": 0,
                            "name": "Ep1",
                            "air_date": last_week.isoformat(),
                        },
                        {
                            "id": 502,
                            "season_number": 1,
                            "episode_number": 2,
                            "order": 1,
                            "name": "Ep2",
                            "air_date": yesterday.isoformat(),
                        },
                    ],
                }
            ],
        }
        session = _make_apply_session()
        show = _make_show(last_air_date=None)
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=detail)

        orch = TMDBOrchestrator(session, tmdb)
        await orch.apply_episode_group(show, "us-broadcast-id")

        assert show.last_air_date == yesterday.isoformat()


class TestSyncShowEpisodesWithActiveGroup:
    """Tests for sync_show_episodes' branch to the non-destructive group refresh."""

    async def test_delegates_to_active_group_refresh_and_skips_native_fetch(self):
        session = _make_session(existing_episode=None)
        show = _make_show()
        show.active_episode_group_id = "us-broadcast-id"
        tmdb = _make_tmdb()
        tmdb.get_episode_group = AsyncMock(return_value=_US_BROADCAST_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        result = await orch.sync_show_episodes(show)

        tmdb.get_show_seasons.assert_not_called()
        tmdb.get_season_details.assert_not_called()
        tmdb.get_episode_group.assert_called_once_with("us-broadcast-id")
        assert result.episodes_upserted == 2
        assert show.active_episode_group_name == "US Broadcast Order"

    async def test_refresh_updates_existing_episodes_by_tmdb_id_without_deleting(self):
        existing = MagicMock()
        existing.name = "Old Name"
        session = _make_session(existing_episode=existing)
        show = _make_show()
        show.active_episode_group_id = "us-broadcast-id"
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_US_BROADCAST_GROUP_DETAIL)

        orch = TMDBOrchestrator(session, tmdb)
        result = await orch._refresh_active_group_episodes(show)

        assert result.episodes_skipped == 2
        assert result.episodes_upserted == 0
        assert existing.season_number == 1
        assert existing.episode_number == 2
        assert existing.absolute_episode_number == 2
        session.add.assert_not_called()

    async def test_refresh_updates_last_air_date_from_newest_aired_group_episode(self):
        yesterday = date.today() - timedelta(days=1)
        last_week = date.today() - timedelta(days=7)
        detail = {
            "id": "us-broadcast-id",
            "name": "US Broadcast Order",
            "groups": [
                {
                    "name": "Season 1",
                    "order": 1,
                    "episodes": [
                        {
                            "id": 501,
                            "season_number": 1,
                            "episode_number": 1,
                            "order": 0,
                            "name": "Ep1",
                            "air_date": last_week.isoformat(),
                        },
                        {
                            "id": 502,
                            "season_number": 1,
                            "episode_number": 2,
                            "order": 1,
                            "name": "Ep2",
                            "air_date": yesterday.isoformat(),
                        },
                    ],
                }
            ],
        }
        session = _make_session(existing_episode=None)
        show = _make_show(last_air_date=None)
        show.active_episode_group_id = "us-broadcast-id"
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=detail)

        orch = TMDBOrchestrator(session, tmdb)
        await orch._refresh_active_group_episodes(show)

        assert show.last_air_date == yesterday.isoformat()

    async def test_refresh_raises_if_no_active_group_is_set(self):
        """Guards against calling this directly on a show with no active
        group -- callers must check active_episode_group_id first.
        """
        session = _make_session(existing_episode=None)
        show = _make_show()
        show.active_episode_group_id = None
        tmdb = AsyncMock()

        orch = TMDBOrchestrator(session, tmdb)
        with pytest.raises(ValueError, match="active_episode_group_id"):
            await orch._refresh_active_group_episodes(show)
        tmdb.get_episode_group.assert_not_called()
