"""Tests for the POST /shows/calendar/sync-missing API route."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from jidou.api.routes.shows import get_tmdb
from jidou.database import get_session
from jidou.main import app
from jidou.orchestrators.tmdb_orchestrator import TMDBSyncResult
from tests._fake_orchestrator_session import FakeNested


def _session(
    show_ids: list[int],
    shows_by_id: dict[int, MagicMock],
    rss_by_id: dict[int, bool] | None = None,
) -> object:
    """Build a mock session answering the show-id lookup then per-show lookups.

    The first execute() call is the distinct show_id query; every call after
    that is a per-show ``select(Show, has_active_rss_subscription)`` lookup,
    in the same order as *show_ids*. *rss_by_id* controls the RSS half of
    that row and defaults to True for any show present in *shows_by_id*.
    """
    rss_by_id = rss_by_id or {}
    ids_result = MagicMock()
    ids_result.scalars.return_value.all.return_value = show_ids

    show_results = []
    for sid in show_ids:
        r = MagicMock()
        show = shows_by_id.get(sid)
        r.first.return_value = (show, rss_by_id.get(sid, True)) if show is not None else None
        show_results.append(r)

    async def _mock_session() -> AsyncMock:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[ids_result, *show_results])
        session.begin_nested = MagicMock(return_value=FakeNested())
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        yield session

    return _mock_session


def _make_show(id: int, *, track_missing_episodes: bool = True) -> MagicMock:
    show = MagicMock()
    show.id = id
    show.track_missing_episodes = track_missing_episodes
    return show


def _post_sync_missing(session_override: object, tmdb_override: object = None) -> object:
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_tmdb] = tmdb_override or (lambda: MagicMock())
    try:
        return TestClient(app).post(
            "/api/shows/calendar/sync-missing?start=2026-07-01&end=2026-07-14"
        )
    finally:
        app.dependency_overrides.clear()


def test_no_missing_shows_returns_zeroed_result() -> None:
    """An empty distinct-show_id result means nothing to sync."""
    response = _post_sync_missing(_session([], {}))

    assert response.status_code == 200
    assert response.json() == {
        "shows_synced": 0,
        "shows_failed": 0,
        "episodes_upserted": 0,
    }


def test_syncs_each_distinct_show_and_aggregates_counts() -> None:
    """Every distinct show_id from the missing-episode query gets synced once."""
    show1, show2 = _make_show(1), _make_show(2)
    session_override = _session([1, 2], {1: show1, 2: show2})

    with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
        mock_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=[
                TMDBSyncResult(shows_synced=1, episodes_upserted=3, episodes_skipped=0),
                TMDBSyncResult(shows_synced=1, episodes_upserted=2, episodes_skipped=1),
            ]
        )
        response = _post_sync_missing(session_override)

    assert response.status_code == 200
    assert response.json() == {
        "shows_synced": 2,
        "shows_failed": 0,
        "episodes_upserted": 5,
    }
    # Regression: this endpoint exists to pick up a TMDB change made after
    # the last sync, so it must not settle for whatever's still in the
    # TMDB response cache.
    for call in mock_orch_cls.return_value.sync_show_episodes.await_args_list:
        assert call.kwargs.get("bypass_cache") is True


def test_one_show_failing_does_not_block_the_rest() -> None:
    """A TMDB failure for one show is caught and counted, other shows still sync."""
    show1, show2 = _make_show(1), _make_show(2)
    session_override = _session([1, 2], {1: show1, 2: show2})

    with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
        mock_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=[
                Exception("TMDB unavailable"),
                TMDBSyncResult(shows_synced=1, episodes_upserted=4, episodes_skipped=0),
            ]
        )
        response = _post_sync_missing(session_override)

    assert response.status_code == 200
    assert response.json() == {
        "shows_synced": 1,
        "shows_failed": 1,
        "episodes_upserted": 4,
    }


def test_show_id_with_no_matching_show_is_skipped() -> None:
    """A show_id that no longer resolves to a Show row is silently skipped."""
    session_override = _session([1], {})

    with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
        mock_orch_cls.return_value.sync_show_episodes = AsyncMock()
        response = _post_sync_missing(session_override)
        mock_orch_cls.return_value.sync_show_episodes.assert_not_called()

    assert response.status_code == 200
    assert response.json() == {
        "shows_synced": 0,
        "shows_failed": 0,
        "episodes_upserted": 0,
    }


def test_show_with_track_missing_episodes_false_is_skipped() -> None:
    """A show that opted out of missing-episode tracking is not re-synced.

    Regression test for the calendar's "Sync missing" button re-syncing
    shows the user has deliberately excluded from missing-episode tracking
    (e.g. shows with no RSS feed), which is wasted work and an inflated count.
    """
    show1, show2 = (
        _make_show(1, track_missing_episodes=False),
        _make_show(2),
    )
    session_override = _session([1, 2], {1: show1, 2: show2})

    with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
        mock_orch_cls.return_value.sync_show_episodes = AsyncMock(
            return_value=TMDBSyncResult(shows_synced=1, episodes_upserted=2, episodes_skipped=0)
        )
        response = _post_sync_missing(session_override)
        mock_orch_cls.return_value.sync_show_episodes.assert_called_once()

    assert response.status_code == 200
    assert response.json() == {
        "shows_synced": 1,
        "shows_failed": 0,
        "episodes_upserted": 2,
    }


def test_show_with_no_active_rss_subscription_is_skipped() -> None:
    """A show with no active, published RSS subscription is not re-synced.

    Regression test: a show that will never auto-download its episodes (no
    RSS feed configured at all) shouldn't inflate the "Sync missing" count
    or be re-synced, even if the user never explicitly toggled "Ignore
    Missing Eps" for it.
    """
    show1, show2 = _make_show(1), _make_show(2)
    session_override = _session([1, 2], {1: show1, 2: show2}, rss_by_id={1: False})

    with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
        mock_orch_cls.return_value.sync_show_episodes = AsyncMock(
            return_value=TMDBSyncResult(shows_synced=1, episodes_upserted=2, episodes_skipped=0)
        )
        response = _post_sync_missing(session_override)
        mock_orch_cls.return_value.sync_show_episodes.assert_called_once()

    assert response.status_code == 200
    assert response.json() == {
        "shows_synced": 1,
        "shows_failed": 0,
        "episodes_upserted": 2,
    }


def test_missing_start_param_returns_422() -> None:
    app.dependency_overrides[get_session] = _session([], {})
    try:
        response = TestClient(app).post("/api/shows/calendar/sync-missing?end=2026-07-14")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
