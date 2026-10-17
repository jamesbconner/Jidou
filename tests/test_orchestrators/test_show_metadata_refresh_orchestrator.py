"""Tests for ShowMetadataRefreshOrchestrator."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2 as httpx
import pytest

from jidou.models.show import Show
from jidou.orchestrators.show_metadata_refresh_orchestrator import (
    ShowMetadataRefreshOrchestrator,
)
from jidou.services.metadata_refresh_policy import RefreshPolicy, ShowRefreshFacts

_MOD = "jidou.orchestrators.show_metadata_refresh_orchestrator"
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


class _FakeNestedTransaction:
    """Mimics AsyncSession.begin_nested()'s async context manager."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _policy(limit: int = 10) -> RefreshPolicy:
    return RefreshPolicy(
        now=NOW, limit=limit, stale_days=30, airing_days=7, ended_days=90, lookback_years=5
    )


def _show(show_id: int = 1, tmdb_id: int = 100, **fields: object) -> Show:
    """A transient (never persisted) Show with sensible defaults."""
    defaults: dict[str, object] = {
        "id": show_id,
        "tmdb_id": tmdb_id,
        "title": f"Show {show_id}",
        "media_type": "tv",
        "sys_name": f"Show {show_id}",
        "status": "Returning Series",
        "next_episode_to_air": {"air_date": "2026-08-30", "episode_number": 4},
        "last_episode_to_air": {"air_date": "2026-08-23", "episode_number": 3},
        "episode_groups": [{"id": "old"}],
        "local_path": "/library/Show",
        "aliases": ["alias"],
        "active_episode_group_id": "grp",
        "list_poster_path": "/mine.jpg",
    }
    return Show(**{**defaults, **fields})


def _facts(show_id: int) -> ShowRefreshFacts:
    return ShowRefreshFacts(
        show_id=show_id,
        title=f"Show {show_id}",
        media_type="tv",
        status="Returning Series",
        metadata_refreshed_at=None,
        vote_count=1,
        next_air_date=None,
        last_air_date=None,
        latest_season_fully_aired=None,
        latest_season_last_air=None,
        has_rss_subscription=False,
    )


def _session(shows: list[Show]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = shows
    session.execute = AsyncMock(return_value=result)
    by_id = {s.id: s for s in shows}
    session.get = AsyncMock(side_effect=lambda _model, pk: by_id.get(pk))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.begin_nested = MagicMock(side_effect=lambda: _FakeNestedTransaction())
    return session


_ENDED_PAYLOAD = {
    "name": "Show 1",
    "status": "Ended",
    "in_production": False,
    "number_of_seasons": 1,
    "number_of_episodes": 12,
    "next_episode_to_air": None,
    "last_episode_to_air": {"air_date": "2026-09-05", "episode_number": 12},
    "vote_count": 10,
    "external_ids": {"imdb_id": "tt1"},
    "episode_groups": [{"id": "new"}, {"id": "grp"}],
}


def _orch(session: AsyncMock) -> ShowMetadataRefreshOrchestrator:
    return ShowMetadataRefreshOrchestrator(session, MagicMock(), now=lambda: NOW)


# ---------------------------------------------------------------------------
# refresh_show
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_replaces_stale_status_and_clears_past_next_episode() -> None:
    """Regression: a show that ended after being added loses its stale 'next' episode."""
    show = _show()
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)):
        await _orch(_session([show])).refresh_show(show)

    assert show.status == "Ended"
    assert show.next_episode_to_air is None
    assert show.last_episode_to_air == {"air_date": "2026-09-05", "episode_number": 12}
    assert show.number_of_episodes == 12


@pytest.mark.asyncio
async def test_refresh_never_touches_user_or_derived_columns() -> None:
    show = _show()
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)):
        await _orch(_session([show])).refresh_show(show)

    assert show.local_path == "/library/Show"
    assert show.aliases == ["alias"]
    assert show.active_episode_group_id == "grp"
    assert show.list_poster_path == "/mine.jpg"
    assert show.sys_name == "Show 1"
    assert show.tmdb_id == 100


@pytest.mark.asyncio
async def test_refresh_stamps_metadata_refreshed_at() -> None:
    show = _show()
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)):
        await _orch(_session([show])).refresh_show(show)

    assert show.metadata_refreshed_at == NOW


@pytest.mark.asyncio
async def test_refresh_uses_live_fetch_bypassing_the_cache() -> None:
    show = _show()
    fetch = AsyncMock(return_value=_ENDED_PAYLOAD)
    with patch(f"{_MOD}.fetch_show_metadata", new=fetch):
        await _orch(_session([show])).refresh_show(show)

    assert fetch.await_args.kwargs == {"bypass_cache": True}


@pytest.mark.asyncio
async def test_refresh_keeps_existing_episode_groups_when_fetch_failed() -> None:
    """None means the groups fetch failed; it must not overwrite known groups."""
    show = _show()
    payload = {**_ENDED_PAYLOAD, "episode_groups": None}
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=payload)):
        await _orch(_session([show])).refresh_show(show)

    assert show.episode_groups == [{"id": "old"}]


@pytest.mark.asyncio
async def test_refresh_dry_run_writes_nothing_and_does_not_stamp() -> None:
    show = _show()
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)):
        await _orch(_session([show])).refresh_show(show, dry_run=True)

    assert show.status == "Returning Series"
    assert show.metadata_refreshed_at is None


@pytest.mark.asyncio
async def test_refresh_movie_succeeds() -> None:
    movie = _show(media_type="movie", status="Released", next_episode_to_air=None)
    payload = {"title": "Show 1", "status": "Released", "external_ids": {}, "episode_groups": []}
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=payload)):
        await _orch(_session([movie])).refresh_show(movie)

    assert movie.metadata_refreshed_at == NOW
    assert movie.status == "Released"


@pytest.mark.asyncio
async def test_refresh_never_rewrites_the_title() -> None:
    """A TMDB retitle must not rename a library show; only an explicit rematch does."""
    show = _show(title="My Title")
    payload = {**_ENDED_PAYLOAD, "name": "Retitled On TMDB"}
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=payload)):
        changes = await _orch(_session([show])).refresh_show(show)

    assert show.title == "My Title"
    assert "title" not in changes


@pytest.mark.asyncio
async def test_refresh_returns_old_and_new_values_of_only_the_changed_columns() -> None:
    show = _show()
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)):
        changes = await _orch(_session([show])).refresh_show(show)

    assert changes["status"] == ("Returning Series", "Ended")
    assert changes["next_episode_to_air"] == (
        {"air_date": "2026-08-30", "episode_number": 4},
        None,
    )
    assert "local_path" not in changes
    assert "metadata_refreshed_at" not in changes


@pytest.mark.asyncio
async def test_refresh_dry_run_reports_the_changes_it_would_make() -> None:
    show = _show()
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)):
        changes = await _orch(_session([show])).refresh_show(show, dry_run=True)

    assert changes["status"] == ("Returning Series", "Ended")
    assert show.status == "Returning Series"


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


class _Events:
    """Collects (level, message, ctx) events from a run."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict | None]] = []

    async def __call__(self, level: str, msg: str, ctx: dict | None = None) -> None:
        self.events.append((level, msg, ctx))


@pytest.mark.asyncio
async def test_run_logs_each_shows_changed_columns() -> None:
    events = _Events()
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)),
    ):
        await _orch(_session([_show()])).run(policy=_policy(), on_event=events)

    ((level, msg, ctx),) = events.events
    assert level == "info"
    assert msg.startswith("Refreshed 'Show 1' (NEVER_REFRESHED): ")
    assert "status: 'Returning Series' → 'Ended'" in msg
    assert "next_episode_to_air: S" not in msg  # the fixture dicts carry no season number
    assert "next_episode_to_air: (set) → none" in msg
    assert ctx["show_id"] == 1
    assert ctx["reason"] == "NEVER_REFRESHED"
    assert ctx["changes"]["status"] == "'Returning Series' → 'Ended'"


@pytest.mark.asyncio
async def test_run_logs_when_nothing_changed() -> None:
    events = _Events()
    show = _show()
    with _patch_selection([1]), patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock()) as fetch:
        orch = _orch(_session([show]))
        fetch.return_value = _ENDED_PAYLOAD
        await orch.run(policy=_policy())  # bring the show in line with TMDB
        fetch.return_value = _ENDED_PAYLOAD
        await orch.run(policy=_policy(), on_event=events)

    ((_, msg, ctx),) = events.events
    assert msg.endswith("no changes")
    assert ctx["changes"] == {}


@pytest.mark.asyncio
async def test_run_dry_run_logs_what_it_would_change() -> None:
    events = _Events()
    show = _show()
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)),
    ):
        await _orch(_session([show])).run(dry_run=True, policy=_policy(), on_event=events)

    ((_, msg, _ctx),) = events.events
    assert msg.startswith("[Dry run] Would refresh 'Show 1'")
    assert show.status == "Returning Series"


@pytest.mark.asyncio
async def test_run_logs_a_warning_for_a_failed_show() -> None:
    events = _Events()
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        await _orch(_session([_show()])).run(policy=_policy(), on_event=events)

    ((level, msg, ctx),) = events.events
    assert level == "warning"
    assert "Could not refresh 'Show 1'" in msg
    assert "RuntimeError: boom" in msg
    assert ctx == {"show_id": 1}


@pytest.mark.asyncio
async def test_run_logs_that_tmdb_no_longer_has_a_missing_show() -> None:
    events = _Events()
    response = httpx.Response(404, request=httpx.Request("GET", "https://x/tv/100"))
    err = httpx.HTTPStatusError("not found", request=response.request, response=response)
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(side_effect=err)),
    ):
        await _orch(_session([_show()])).run(policy=_policy(), on_event=events)

    ((level, msg, _ctx),) = events.events
    assert level == "warning"
    assert "TMDB no longer has this id" in msg


def _patch_selection(ids: list[int]):
    return patch(f"{_MOD}.load_refresh_facts", new=AsyncMock(return_value=[_facts(i) for i in ids]))


@pytest.mark.asyncio
async def test_run_refreshes_each_selected_show_and_commits_per_show() -> None:
    shows = [_show(1, 100), _show(2, 200)]
    session = _session(shows)
    with (
        _patch_selection([1, 2]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)),
    ):
        result = await _orch(session).run(policy=_policy())

    assert (result.shows_checked, result.shows_updated, result.shows_failed) == (2, 2, 0)
    assert result.updated_titles == ["Show 1", "Show 2"]
    assert session.commit.await_count == 2
    assert result.reasons == {"NEVER_REFRESHED": 2}


@pytest.mark.asyncio
async def test_run_respects_the_per_run_limit() -> None:
    shows = [_show(i, 100 + i) for i in range(1, 6)]
    session = _session(shows)
    fetch = AsyncMock(return_value=_ENDED_PAYLOAD)
    with _patch_selection([1, 2, 3, 4, 5]), patch(f"{_MOD}.fetch_show_metadata", new=fetch):
        result = await _orch(session).run(policy=_policy(limit=2))

    assert result.shows_checked == 2
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_run_isolates_a_transient_failure_and_does_not_stamp_that_show() -> None:
    good, bad = _show(1, 100), _show(2, 200)
    session = _session([good, bad])

    async def fetch(_tmdb, tmdb_id, _media, **_kw):
        if tmdb_id == 200:
            raise RuntimeError("boom")
        return _ENDED_PAYLOAD

    with _patch_selection([1, 2]), patch(f"{_MOD}.fetch_show_metadata", new=fetch):
        result = await _orch(session).run(policy=_policy())

    assert result.shows_updated == 1
    assert result.failed_titles == ["Show 2"]
    assert bad.metadata_refreshed_at is None
    assert good.metadata_refreshed_at == NOW


@pytest.mark.asyncio
async def test_run_stamps_a_show_tmdb_reports_gone_so_it_is_not_retried_every_run() -> None:
    dead = _show(1, 100)
    session = _session([dead])
    response = httpx.Response(404, request=httpx.Request("GET", "https://x/tv/100"))
    err = httpx.HTTPStatusError("not found", request=response.request, response=response)

    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(side_effect=err)),
    ):
        result = await _orch(session).run(policy=_policy())

    assert result.shows_failed == 1
    assert dead.metadata_refreshed_at == NOW
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_rolls_back_a_failed_commit_and_continues() -> None:
    a, b = _show(1, 100), _show(2, 200)
    session = _session([a, b])
    session.commit = AsyncMock(side_effect=[RuntimeError("db down"), None])

    with (
        _patch_selection([1, 2]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)),
    ):
        result = await _orch(session).run(policy=_policy())

    session.rollback.assert_awaited_once()
    assert result.shows_failed == 1
    assert result.shows_updated == 1


@pytest.mark.asyncio
async def test_run_dry_run_commits_nothing_and_stamps_nothing() -> None:
    show = _show()
    session = _session([show])
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)),
    ):
        result = await _orch(session).run(dry_run=True, policy=_policy())

    assert result.shows_updated == 1
    session.commit.assert_not_awaited()
    assert show.metadata_refreshed_at is None
    assert show.status == "Returning Series"


@pytest.mark.asyncio
async def test_run_with_no_candidates_does_nothing() -> None:
    session = _session([])
    with _patch_selection([]):
        result = await _orch(session).run(policy=_policy())

    assert result.shows_checked == 0
    session.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_reports_progress() -> None:
    session = _session([_show()])
    progress = AsyncMock()
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)),
    ):
        await _orch(session).run(policy=_policy(), on_progress=progress)

    progress.assert_awaited_once_with(1, 1, "Refreshing Show 1")


@pytest.mark.asyncio
async def test_run_loads_each_show_after_the_previous_one_finishes() -> None:
    """A rollback expires every loaded Show, so shows must not be prefetched.

    Regression: with all selected shows loaded up front, one failed commit's
    session.rollback() expired the rest, and their next attribute access
    raised MissingGreenlet instead of isolating the bad show.
    """
    a, b = _show(1, 100), _show(2, 200)
    session = _session([a, b])
    order: list[str] = []
    real_get = session.get.side_effect
    session.get = AsyncMock(
        side_effect=lambda model, pk: (order.append(f"get:{pk}"), real_get(model, pk))[1]
    )
    session.commit = AsyncMock(side_effect=[RuntimeError("db down"), None])
    session.rollback = AsyncMock(side_effect=lambda: order.append("rollback"))

    with (
        _patch_selection([1, 2]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)),
    ):
        result = await _orch(session).run(policy=_policy())

    assert order == ["get:1", "rollback", "get:2"]
    assert (result.shows_updated, result.shows_failed) == (1, 1)


@pytest.mark.asyncio
async def test_run_skips_a_show_deleted_after_selection() -> None:
    session = _session([_show(1, 100)])
    session.get = AsyncMock(return_value=None)
    with _patch_selection([1]), patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock()) as fetch:
        result = await _orch(session).run(policy=_policy())

    fetch.assert_not_awaited()
    assert result.shows_updated == 0


@pytest.mark.asyncio
async def test_refresh_keeps_existing_external_ids_when_the_fetch_came_back_empty() -> None:
    """fetch_show_metadata turns a failed external_ids call into {}; don't wipe known IDs."""
    show = _show(external_ids={"imdb_id": "tt1", "tvdb_id": 5})
    payload = {**_ENDED_PAYLOAD, "external_ids": {}}
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=payload)):
        await _orch(_session([show])).refresh_show(show)

    assert show.external_ids == {"imdb_id": "tt1", "tvdb_id": 5}


@pytest.mark.asyncio
async def test_refresh_replaces_external_ids_when_tmdb_returned_some() -> None:
    show = _show(external_ids={"imdb_id": "tt1"})
    with patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)):
        await _orch(_session([show])).refresh_show(show)

    assert show.external_ids == {"imdb_id": "tt1"}


@pytest.mark.asyncio
async def test_run_uses_the_per_run_limit_from_runtime_settings() -> None:
    """Without an explicit policy the cap comes from the Settings page value."""
    shows = [_show(i, 100 + i) for i in range(1, 6)]
    session = _session(shows)
    fetch = AsyncMock(return_value=_ENDED_PAYLOAD)
    with (
        _patch_selection([1, 2, 3, 4, 5]),
        patch(f"{_MOD}.get_metadata_refresh_limit", new=AsyncMock(return_value=2)) as limit,
        patch(f"{_MOD}.fetch_show_metadata", new=fetch),
    ):
        result = await _orch(session).run()

    limit.assert_awaited_once_with(session)
    assert result.shows_checked == 2
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_an_explicit_policy_wins_over_runtime_settings() -> None:
    session = _session([_show(1, 100)])
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.get_metadata_refresh_limit", new=AsyncMock()) as limit,
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=_ENDED_PAYLOAD)),
    ):
        await _orch(session).run(policy=_policy())

    limit.assert_not_awaited()


def test_default_clock_is_timezone_aware() -> None:
    orch = ShowMetadataRefreshOrchestrator(MagicMock(), MagicMock())
    assert orch._now().tzinfo is not None
    assert abs(orch._now() - datetime.now(UTC)) < timedelta(seconds=5)


@pytest.mark.parametrize(
    ("active", "payload_groups", "warns"),
    [
        ("gone", [{"id": "other"}], True),
        ("gone", [], True),
        ("kept", [{"id": "kept"}], False),
        (None, [{"id": "other"}], False),
    ],
)
@pytest.mark.asyncio
async def test_run_warns_when_the_active_episode_group_is_no_longer_offered(
    active: str | None, payload_groups: list[dict], warns: bool
) -> None:
    events = _Events()
    show = _show(active_episode_group_id=active)
    payload = {**_ENDED_PAYLOAD, "episode_groups": payload_groups}
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=payload)),
    ):
        await _orch(_session([show])).run(policy=_policy(), on_event=events)

    warnings = [e for e in events.events if e[0] == "warning"]
    assert bool(warnings) is warns
    assert show.active_episode_group_id == active  # never cleared
    if warns:
        assert "gone" in warnings[0][1]
        assert warnings[0][2] == {"show_id": 1, "episode_group_id": "gone"}


@pytest.mark.asyncio
async def test_run_does_not_warn_when_the_group_list_could_not_be_fetched() -> None:
    """None means the groups fetch failed; absence from the old list proves nothing."""
    events = _Events()
    show = _show(active_episode_group_id="grp", episode_groups=None)
    payload = {**_ENDED_PAYLOAD, "episode_groups": None}
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=payload)),
    ):
        await _orch(_session([show])).run(policy=_policy(), on_event=events)

    assert not [e for e in events.events if e[0] == "warning"]


@pytest.mark.asyncio
async def test_run_warns_about_a_missing_active_group_in_a_dry_run_too() -> None:
    events = _Events()
    show = _show(active_episode_group_id="gone")
    payload = {**_ENDED_PAYLOAD, "episode_groups": [{"id": "other"}]}
    with (
        _patch_selection([1]),
        patch(f"{_MOD}.fetch_show_metadata", new=AsyncMock(return_value=payload)),
    ):
        await _orch(_session([show])).run(dry_run=True, policy=_policy(), on_event=events)

    assert [e[0] for e in events.events] == ["warning", "info"]


_EP = {"season_number": 2, "episode_number": 14, "vote_average": 7.0, "vote_count": 3}


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        # Same episode, its own rating moved: say what moved, not "S2E14 → S2E14".
        (_EP, {**_EP, "vote_count": 4}, "S2E14 (vote_count: 3 → 4)"),
        (
            _EP,
            {**_EP, "vote_average": 7.5, "vote_count": 4},
            "S2E14 (vote_average: 7.0 → 7.5, vote_count: 3 → 4)",
        ),
        # A genuinely new latest episode.
        (
            _EP,
            {**_EP, "episode_number": 15},
            "S2E14 → S2E15 (episode_number: 14 → 15)",
        ),
        (
            [{"id": 1, "name": "Drama"}],
            [{"id": 1, "name": "Drama"}, {"id": 2, "name": "Anime"}],
            "+Anime",
        ),
        (
            [{"id": 1, "name": "Drama"}, {"id": 2, "name": "Anime"}],
            [{"id": 2, "name": "Anime"}],
            "-Drama",
        ),
        ([{"id": 1, "name": "A"}], [{"id": 2, "name": "B"}], "+B -A"),
        (["JP"], ["JP", "US"], "+US"),
        ([{"id": 1}, {"id": 2}], [{"id": 2}, {"id": 1}], "reordered"),
        (7.6, 7.5, "7.6 → 7.5"),
        (None, {"a": 1}, "none → (set)"),
    ],
)
def test_describe_change_names_what_differs(old, new, expected) -> None:
    from jidou.orchestrators.show_metadata_refresh_orchestrator import _describe_change

    assert _describe_change(old, new) == expected
