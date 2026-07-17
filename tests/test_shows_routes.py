"""Tests for the /shows API routes."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.episode import Episode
from jidou.models.show import Show


def _make_tmdb_mock() -> AsyncMock:
    """Return an AsyncMock TMDB service with common supplemental calls pre-configured.

    Without this, AsyncMock's auto-created child mocks for
    get_alternative_titles/get_external_ids/get_episode_groups return bogus
    AsyncMock objects instead of dicts -- either leaving unawaited coroutines
    that cascade as ERROR-at-setup failures in subsequent tests, or failing
    Pydantic response validation when a route serializes the mocked field.
    """
    mock = AsyncMock()
    mock.get_alternative_titles = AsyncMock(return_value={"results": []})
    mock.get_external_ids = AsyncMock(return_value={})
    mock.get_episode_groups = AsyncMock(return_value={"results": []})
    return mock


def _make_show(
    *,
    id: int = 1,
    tmdb_id: int = 100,
    title: str = "Test Show",
    media_type: str = "tv",
    local_path: str | None = None,
) -> MagicMock:
    """Build a minimal Show mock suitable for route responses."""
    from datetime import UTC, datetime

    s = MagicMock(spec=Show)
    s.id = id
    s.tmdb_id = tmdb_id
    s.title = title
    s.media_type = media_type
    s.overview = None
    s.poster_path = None
    s.backdrop_path = None
    s.vote_average = None
    s.vote_count = 0
    s.release_date = None
    s.original_language = None
    s.cached = False
    s.content_type = None
    s.sys_name = None
    s.aliases = None
    s.aliases_sources = None
    s.genres = None
    s.origin_country = None
    s.last_air_date = None
    s.last_episode_to_air = None
    s.next_episode_to_air = None
    s.homepage = None
    s.external_ids = None
    s.episode_groups = None
    s.episode_group_map = None
    s.status = None
    s.in_production = None
    s.number_of_seasons = None
    s.number_of_episodes = None
    s.networks = None
    s.show_type = None
    s.runtime = None
    s.tagline = None
    s.local_path = local_path
    s.created_at = datetime.now(UTC)
    s.updated_at = datetime.now(UTC)
    return s


def _make_episode(*, id: int = 10, show_id: int = 1) -> MagicMock:
    """Build a minimal Episode mock."""
    from datetime import UTC, datetime

    ep = MagicMock(spec=Episode)
    ep.id = id
    ep.show_id = show_id
    ep.tmdb_id = 5000
    ep.season_number = 1
    ep.episode_number = 1
    ep.name = "Pilot"
    ep.overview = None
    ep.air_date = None
    ep.runtime = None
    ep.absolute_episode_number = None
    ep.episode_type = None
    ep.still_path = None
    ep.file_tracked = False
    ep.tracked_filename = None
    ep.tracked_source = None
    ep.created_at = datetime.now(UTC)
    ep.updated_at = datetime.now(UTC)
    return ep


def _session_override(
    single: MagicMock | None = None,
    many: list[MagicMock] | None = None,
    has_active_rss: bool = False,
) -> "type[AsyncMock]":
    """Return a FastAPI dependency override that yields a mock session.

    The override returns *many* for scalars().all() and *single* for
    scalar_one_or_none().  Pass a second MagicMock as *single* to handle
    two consecutive selects (e.g. show-exists check + episode list).
    """

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        items = many or ([single] if single else [])
        result.scalar_one_or_none.return_value = single
        result.scalars.return_value.all.return_value = items
        # list_shows returns (show, ep_count, file_count, has_active_rss) tuples via .all()
        result.all.return_value = [(item, 0, 0, has_active_rss) for item in items]
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        session.delete = AsyncMock()
        yield session

    return _mock_session  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /api/shows
# ---------------------------------------------------------------------------


def test_list_shows_returns_200() -> None:
    """GET /api/shows must return a list."""
    from jidou.database import get_session

    show = _make_show()
    app.dependency_overrides[get_session] = _session_override(many=[show])
    try:
        response = TestClient(app).get("/api/shows")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert body[0]["tmdb_id"] == 100
    finally:
        app.dependency_overrides.clear()


def test_list_shows_empty_returns_empty_list() -> None:
    """GET /api/shows with no records returns []."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(many=[])
    try:
        response = TestClient(app).get("/api/shows")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.clear()


def test_list_shows_surfaces_active_rss_subscription_flag() -> None:
    """has_active_rss_subscription reflects the correlated EXISTS subquery per show."""
    from jidou.database import get_session

    show = _make_show()
    app.dependency_overrides[get_session] = _session_override(many=[show], has_active_rss=True)
    try:
        response = TestClient(app).get("/api/shows")
        assert response.status_code == 200
        assert response.json()[0]["has_active_rss_subscription"] is True
    finally:
        app.dependency_overrides.clear()


def test_list_shows_defaults_active_rss_subscription_to_false() -> None:
    """A show with no active/enabled subscription reports has_active_rss_subscription=False."""
    from jidou.database import get_session

    show = _make_show()
    app.dependency_overrides[get_session] = _session_override(many=[show])
    try:
        response = TestClient(app).get("/api/shows")
        assert response.status_code == 200
        assert response.json()[0]["has_active_rss_subscription"] is False
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/shows
# ---------------------------------------------------------------------------


def test_create_show_returns_201_on_new() -> None:
    """POST /api/shows with a new TMDB ID must return 201."""
    from jidou.database import get_session

    show = _make_show(tmdb_id=999)

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        # First execute (check duplicate): returns None (no existing show)
        # Second flush() populates id on the object → simulate via side_effect
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)
        session.flush = AsyncMock()
        session.add = MagicMock()

        # After flush, the Show object needs its id set.  We can't do that
        # without an actual DB, so return a pre-built mock from `add`.
        async def _flush_side_effect() -> None:
            session.add.call_args[0][0].id = show.id
            session.add.call_args[0][0].created_at = show.created_at
            session.add.call_args[0][0].updated_at = show.updated_at

        session.flush.side_effect = _flush_side_effect
        yield session

    app.dependency_overrides[get_session] = _new_session
    try:
        response = TestClient(app).post(
            "/api/shows",
            json={"tmdb_id": 999, "title": "New Show", "media_type": "tv"},
        )
        assert response.status_code == 201
    finally:
        app.dependency_overrides.clear()


def test_create_show_stores_adult_flag() -> None:
    """POST /api/shows with adult=true constructs the Show with adult=True."""
    from jidou.database import get_session

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)

        async def _flush() -> None:
            obj = session.add.call_args[0][0]
            obj.id = 998
            from datetime import UTC, datetime

            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        session.flush = AsyncMock(side_effect=_flush)
        session.add = MagicMock()
        yield session

    app.dependency_overrides[get_session] = _new_session
    try:
        response = TestClient(app).post(
            "/api/shows",
            json={"tmdb_id": 998, "title": "Adult Show", "media_type": "tv", "adult": True},
        )
        assert response.status_code == 201
        assert response.json()["adult"] is True
    finally:
        app.dependency_overrides.clear()


def test_create_show_returns_existing_if_duplicate_tmdb_id() -> None:
    """POST /api/shows with a duplicate TMDB ID must return the existing record."""
    from jidou.database import get_session

    show = _make_show(tmdb_id=100)
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        response = TestClient(app).post(
            "/api/shows",
            json={"tmdb_id": 100, "title": "Test Show", "media_type": "tv"},
        )
        # 201 status because the route always returns 201; the idempotency
        # is at data level (returns existing record without re-inserting).
        assert response.status_code == 201
        assert response.json()["tmdb_id"] == 100
    finally:
        app.dependency_overrides.clear()


def test_create_show_handles_concurrent_insert_race() -> None:
    """POST /api/shows recovers from IntegrityError caused by a concurrent insert.

    Two requests for the same tmdb_id can both pass the select-then-insert
    guard simultaneously.  The second flush raises IntegrityError; the route
    must roll back, re-query, and return the row the first request created.
    """
    from sqlalchemy.exc import IntegrityError

    from jidou.database import get_session

    show = _make_show(tmdb_id=200)

    async def _race_session() -> AsyncMock:
        session = AsyncMock()
        # First execute: initial select sees no existing row
        miss_result = MagicMock()
        miss_result.scalar_one_or_none.return_value = None
        # Second execute: re-select after rollback finds the concurrently inserted row
        hit_result = MagicMock()
        hit_result.scalar_one_or_none.return_value = show
        session.execute = AsyncMock(side_effect=[miss_result, hit_result])
        session.add = MagicMock()
        session.flush = AsyncMock(side_effect=IntegrityError("", {}, Exception()))
        session.rollback = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _race_session
    try:
        response = TestClient(app).post(
            "/api/shows",
            json={"tmdb_id": 200, "title": "Race Show", "media_type": "tv"},
        )
        assert response.status_code == 201
        assert response.json()["tmdb_id"] == 200
    finally:
        app.dependency_overrides.clear()


def test_create_show_race_return_still_backfills_episode_group_map() -> None:
    """Bugbot-caught regression: the concurrent-insert race branch must call
    ensure_episode_group_map on the row it falls back to returning, same as
    the normal already-exists branch -- otherwise a show that only ever hits
    this race path can keep a null episode_group_map indefinitely.
    """
    from sqlalchemy.exc import IntegrityError

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(tmdb_id=201)

    async def _race_session() -> AsyncMock:
        session = AsyncMock()
        miss_result = MagicMock()
        miss_result.scalar_one_or_none.return_value = None
        hit_result = MagicMock()
        hit_result.scalar_one_or_none.return_value = show
        session.execute = AsyncMock(side_effect=[miss_result, hit_result])
        session.add = MagicMock()
        session.flush = AsyncMock(side_effect=IntegrityError("", {}, Exception()))
        session.rollback = AsyncMock()
        yield session

    async def _fake_tmdb() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_session] = _race_session
    app.dependency_overrides[get_tmdb] = _fake_tmdb
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
            mock_orch = MagicMock()
            mock_orch.ensure_episode_group_map = AsyncMock()
            mock_orch_cls.return_value = mock_orch

            response = TestClient(app).post(
                "/api/shows",
                json={"tmdb_id": 201, "title": "Race Show", "media_type": "tv"},
            )
        assert response.status_code == 201
        mock_orch.ensure_episode_group_map.assert_awaited_once_with(show)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/shows/{show_id}
# ---------------------------------------------------------------------------


def test_get_show_returns_200_when_found() -> None:
    """GET /api/shows/{id} returns the show."""
    from jidou.database import get_session

    show = _make_show(id=1)
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        response = TestClient(app).get("/api/shows/1")
        assert response.status_code == 200
        assert response.json()["id"] == 1
    finally:
        app.dependency_overrides.clear()


def test_get_show_returns_404_when_not_found() -> None:
    """GET /api/shows/{id} returns 404 for an unknown ID."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).get("/api/shows/9999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PUT /api/shows/{show_id}/paths
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PATCH /api/shows/{show_id}
# ---------------------------------------------------------------------------


def test_patch_show_sets_content_type() -> None:
    """PATCH /api/shows/{id} updates content_type on the show object."""
    from jidou.database import get_session

    show = _make_show(id=1)
    show.content_type = None
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        response = TestClient(app).patch("/api/shows/1", json={"content_type": "anime"})
        assert response.status_code == 200
        assert show.content_type == "anime"
    finally:
        app.dependency_overrides.clear()


def test_patch_show_clears_content_type_with_null() -> None:
    """PATCH /api/shows/{id} with null clears content_type."""
    from jidou.database import get_session

    show = _make_show(id=1)
    show.content_type = "tv"
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        response = TestClient(app).patch("/api/shows/1", json={"content_type": None})
        assert response.status_code == 200
        assert show.content_type is None
    finally:
        app.dependency_overrides.clear()


def test_patch_show_returns_404_when_not_found() -> None:
    """PATCH /api/shows/{id} returns 404 for an unknown show."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).patch("/api/shows/9999", json={"content_type": "movie"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_patch_show_rejects_invalid_content_type() -> None:
    """PATCH /api/shows/{id} returns 422 for an invalid content_type value."""
    response = TestClient(app).patch("/api/shows/1", json={"content_type": "cartoon"})
    assert response.status_code == 422


def test_update_paths_returns_updated_show() -> None:
    """PUT /api/shows/{id}/paths returns the show with updated local_path."""
    from jidou.database import get_session

    show = _make_show(id=1)
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        response = TestClient(app).put(
            "/api/shows/1/paths",
            json={"local_path": "/media/test"},
        )
        assert response.status_code == 200
        assert "id" in response.json()
    finally:
        app.dependency_overrides.clear()


def test_update_paths_returns_404_for_missing_show() -> None:
    """PUT /api/shows/{id}/paths returns 404 when the show doesn't exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).put(
            "/api/shows/9999/paths",
            json={"local_path": "/x"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_update_paths_sets_local_path() -> None:
    """PUT /api/shows/{id}/paths updates local_path on the show object."""
    from jidou.database import get_session

    show = _make_show(id=1)
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        TestClient(app).put(
            "/api/shows/1/paths",
            json={"local_path": "/media/new"},
        )
        assert show.local_path == "/media/new"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /api/shows/{show_id}
# ---------------------------------------------------------------------------


def test_delete_show_returns_204() -> None:
    """DELETE /api/shows/{id} returns 204 No Content."""
    from jidou.database import get_session

    show = _make_show(id=1)
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        response = TestClient(app).delete("/api/shows/1")
        assert response.status_code == 204
    finally:
        app.dependency_overrides.clear()


def test_delete_show_returns_404_when_not_found() -> None:
    """DELETE /api/shows/{id} returns 404 for an unknown ID."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).delete("/api/shows/9999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/shows/{show_id}/episodes
# ---------------------------------------------------------------------------


def test_list_episodes_returns_episode_list() -> None:
    """GET /api/shows/{id}/episodes returns the show's episodes."""
    from jidou.database import get_session

    show = _make_show(id=1)
    episode = _make_episode(id=10, show_id=1)

    async def _two_query_session() -> AsyncMock:
        """First execute returns the show, second episodes, third backing files."""
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show

        ep_result = MagicMock()
        ep_result.scalars.return_value.all.return_value = [episode]

        files_result = MagicMock()
        files_result.all.return_value = []  # no backing files

        session.execute = AsyncMock(side_effect=[show_result, ep_result, files_result])
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _two_query_session
    try:
        response = TestClient(app).get("/api/shows/1/episodes")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["episode_number"] == 1
        assert body[0]["backing_files"] == []
    finally:
        app.dependency_overrides.clear()


def test_list_episodes_returns_404_for_missing_show() -> None:
    """GET /api/shows/{id}/episodes returns 404 when the show doesn't exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).get("/api/shows/9999/episodes")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/shows/trending  (TMDB proxy — no DB session needed)
# ---------------------------------------------------------------------------


def test_get_trending_proxies_tmdb() -> None:
    """GET /api/shows/trending returns TMDB response."""
    with patch("jidou.api.routes.shows._tmdb") as mock_tmdb:
        mock_tmdb.get_trending = AsyncMock(return_value={"results": []})
        response = TestClient(app).get("/api/shows/trending?media_type=tv&time_window=day")
    assert response.status_code == 200
    assert "results" in response.json()


def test_search_shows_proxies_tmdb() -> None:
    """GET /api/shows/search returns TMDB search results."""
    with patch("jidou.api.routes.shows._tmdb") as mock_tmdb:
        mock_tmdb.search = AsyncMock(return_value={"results": [{"title": "Stuff"}]})
        response = TestClient(app).get("/api/shows/search?query=stuff")
    assert response.status_code == 200
    assert response.json()["results"][0]["title"] == "Stuff"


# ---------------------------------------------------------------------------
# GET /api/shows/tmdb/{tmdb_id}  (TMDB detail proxy)
# ---------------------------------------------------------------------------


def test_get_tmdb_details_proxies_tmdb_service() -> None:
    """GET /api/shows/tmdb/{id} returns raw TMDB detail for the given TMDB ID.

    Regression: the old GET /shows/{tmdb_id} proxy was removed when the router
    switched to DB primary keys. This new endpoint preserves that capability
    under an unambiguous path so clients can still fetch TMDB metadata without
    first storing the show in the database.
    """
    detail_payload = {"id": 12345, "name": "Some Show", "overview": "Great show."}
    with patch("jidou.api.routes.shows._tmdb") as mock_tmdb:
        mock_tmdb.get_details = AsyncMock(return_value=detail_payload)
        response = TestClient(app).get("/api/shows/tmdb/12345?media_type=tv")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 12345
    assert body["name"] == "Some Show"


# ---------------------------------------------------------------------------
# PUT /api/shows/{show_id}/aliases
# ---------------------------------------------------------------------------


def test_update_aliases_returns_updated_show() -> None:
    """PUT /api/shows/{id}/aliases normalises and stores aliases."""
    from jidou.database import get_session

    show = _make_show(id=1)
    show.aliases = None
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        response = TestClient(app).put(
            "/api/shows/1/aliases",
            json={"aliases": ["  Alias One  ", "Alias Two", "alias two"]},
        )
        assert response.status_code == 200
        # duplicates are deduplicated; values are lowercased
        assert show.aliases == ["alias one", "alias two"]
    finally:
        app.dependency_overrides.clear()


def test_update_aliases_returns_404_for_missing_show() -> None:
    """PUT /api/shows/{id}/aliases returns 404 when the show doesn't exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).put("/api/shows/9999/aliases", json={"aliases": []})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/shows/{show_id}/rematch
# ---------------------------------------------------------------------------

_TMDB_DETAIL = {
    "name": "Correct Show",
    "overview": "Right one",
    "poster_path": None,
    "backdrop_path": None,
    "vote_average": 8.0,
    "vote_count": 100,
    "first_air_date": "2020-01-01",
    "original_language": "en",
    "genres": [],
    "origin_country": ["JP"],
    "last_air_date": None,
    "last_episode_to_air": None,
    "next_episode_to_air": None,
    "homepage": None,
    "status": "Ended",
    "in_production": False,
    "number_of_seasons": 1,
    "number_of_episodes": 12,
    "networks": [],
    "type": "Scripted",
    "episode_run_time": [24],
    "tagline": "A great show",
}


def _rematch_session(
    show: MagicMock,
    conflict: MagicMock | None = None,
    tracked_episodes: list[MagicMock] | None = None,
    new_episodes: list[MagicMock] | None = None,
    orphaned_files: list[MagicMock] | None = None,
    preserve_tracking: bool = True,
    media_type: str = "tv",
) -> "type[AsyncMock]":
    """Return a session override for rematch tests.

    Execute call order varies by rematch type:

    TV + preserve_tracking=True (default):
      1. show lookup
      2. conflict check
      3. tracked-episodes snapshot (Phase 1)
      4. episode bulk-delete
      5. orphan dedup-delete (always runs for TV)
      6. new-episodes query (Phase 2)
      7. orphaned-files query (Phase 3)

    TV + preserve_tracking=False:
      1. show lookup
      2. conflict check
      3. episode bulk-delete
      4. orphan dedup-delete (clean-slate clears prior DQ rows)

    Movie:
      1. show lookup
      2. conflict check
      3. episode bulk-delete
      4. orphan dedup-delete (unconditional for all media types)

    Unused entries at the end of the side_effect list are harmless.
    """

    async def _mock() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        conflict_result = MagicMock()
        conflict_result.scalar_one_or_none.return_value = conflict
        delete_result = MagicMock()
        dedup_delete_result = MagicMock()

        if media_type == "movie":
            side_effects = [show_result, conflict_result, delete_result, dedup_delete_result]
        elif preserve_tracking:
            tracked_result = MagicMock()
            tracked_scalars = MagicMock()
            tracked_scalars.all.return_value = tracked_episodes or []
            tracked_result.scalars.return_value = tracked_scalars
            new_eps_result = MagicMock()
            new_eps_scalars = MagicMock()
            new_eps_scalars.all.return_value = new_episodes or []
            new_eps_result.scalars.return_value = new_eps_scalars
            orphan_result = MagicMock()
            orphan_scalars = MagicMock()
            orphan_scalars.all.return_value = orphaned_files or []
            orphan_result.scalars.return_value = orphan_scalars
            side_effects = [
                show_result,
                conflict_result,
                tracked_result,
                delete_result,
                dedup_delete_result,
                new_eps_result,
                orphan_result,
            ]
        else:
            # TV + preserve_tracking=False: clean-slate still runs the dedup delete
            side_effects = [show_result, conflict_result, delete_result, dedup_delete_result]

        session.execute = AsyncMock(side_effect=side_effects)
        session.flush = AsyncMock()
        session.add = MagicMock()  # session.add is synchronous in SQLAlchemy
        yield session

    return _mock  # type: ignore[return-value]


def test_rematch_show_returns_200_on_success() -> None:
    """POST /{id}/rematch replaces metadata and syncs episodes; returns 200."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    app.dependency_overrides[get_session] = _rematch_session(show)
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            response = TestClient(app).post(
                "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "tv"}
            )
        assert response.status_code == 200
        assert response.json()["id"] == 1
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_uses_payload_media_type() -> None:
    """POST /{id}/rematch passes media_type from the payload to get_details."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    app.dependency_overrides[get_session] = _rematch_session(show)
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        # movie path skips sync_show_episodes; no TMDBOrchestrator patch needed
        TestClient(app).post("/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "movie"})
        tmdb_mock.get_details.assert_awaited_once_with(200, media_type="movie")
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_movie_applies_movie_fields() -> None:
    """POST /{id}/rematch for a movie uses data['title'] and data['release_date']."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    movie_data = {
        "title": "My Movie",  # movies use 'title', not 'name'
        "release_date": "2022-06-01",  # movies use 'release_date', not 'first_air_date'
        "overview": "A film",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 7.5,
        "vote_count": 200,
        "original_language": "en",
        "genres": [],
        "runtime": 120,
        "tagline": "A tagline",
        "status": "Released",
        "networks": [],
    }
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=movie_data)

    app.dependency_overrides[get_session] = _rematch_session(show)
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        response = TestClient(app).post(
            "/api/shows/1/rematch", json={"tmdb_id": 300, "media_type": "movie"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "My Movie"
        assert body["media_type"] == "movie"
        assert body["release_date"] == "2022-06-01"
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_returns_404_when_show_not_found() -> None:
    """POST /{id}/rematch returns 404 when the show does not exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).post("/api/shows/9999/rematch", json={"tmdb_id": 200})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_returns_409_on_tmdb_id_conflict() -> None:
    """POST /{id}/rematch returns 409 when the target TMDB ID is already tracked."""
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    conflict = _make_show(id=2, tmdb_id=200, title="Other Show")
    app.dependency_overrides[get_session] = _rematch_session(show, conflict=conflict)
    try:
        response = TestClient(app).post("/api/shows/1/rematch", json={"tmdb_id": 200})
        assert response.status_code == 409
        assert "Other Show" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_returns_502_when_tmdb_fetch_fails() -> None:
    """POST /{id}/rematch returns 502 when TMDB details cannot be fetched."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(side_effect=Exception("TMDB unavailable"))

    app.dependency_overrides[get_session] = _rematch_session(show)
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        response = TestClient(app).post("/api/shows/1/rematch", json={"tmdb_id": 200})
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_returns_502_when_episode_sync_fails() -> None:
    """POST /{id}/rematch returns 502 when episode sync raises; transaction rolls back."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    app.dependency_overrides[get_session] = _rematch_session(show)
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock(
                side_effect=Exception("Sync failed")
            )
            response = TestClient(app).post("/api/shows/1/rematch", json={"tmdb_id": 200})
        assert response.status_code == 502
        assert "sync" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_migrates_tracking_to_new_episodes() -> None:
    """Tracking state is restored on new episodes that share the same S/E key."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)

    old_ep = _make_episode(id=10, show_id=1)
    old_ep.season_number = 1
    old_ep.episode_number = 3
    old_ep.file_tracked = True
    old_ep.tracked_filename = "/media/show.s01e03.mkv"
    old_ep.tracked_source = "match"
    old_ep.file_tracked_at = None

    new_ep = _make_episode(id=50, show_id=1)
    new_ep.season_number = 1
    new_ep.episode_number = 3
    new_ep.file_tracked = False
    new_ep.tracked_filename = None
    new_ep.tracked_source = None

    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    app.dependency_overrides[get_session] = _rematch_session(
        show,
        tracked_episodes=[old_ep],
        new_episodes=[new_ep],
    )
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            response = TestClient(app).post(
                "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "tv"}
            )
        assert response.status_code == 200
        assert new_ep.file_tracked is True
        assert new_ep.tracked_filename == "/media/show.s01e03.mkv"
        assert new_ep.tracked_source == "match"
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_relinks_orphaned_downloaded_files() -> None:
    """DownloadedFiles with episode_id=NULL are re-linked to the matching new episode."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session
    from jidou.models.downloaded_file import DownloadedFile

    show = _make_show(id=1, tmdb_id=100)
    new_ep = _make_episode(id=50, show_id=1)
    new_ep.season_number = 2
    new_ep.episode_number = 1
    new_ep.file_tracked = False

    orphan = MagicMock(spec=DownloadedFile)
    orphan.show_id = 1
    orphan.episode_id = None
    orphan.parsed_season = 2
    orphan.parsed_episode = 1

    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    app.dependency_overrides[get_session] = _rematch_session(
        show,
        new_episodes=[new_ep],
        orphaned_files=[orphan],
    )
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            response = TestClient(app).post(
                "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "tv"}
            )
        assert response.status_code == 200
        assert orphan.episode_id == 50
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_logs_warning_for_unrecoverable_episodes(caplog: object) -> None:
    """A warning is logged when a tracked episode has no matching S/E in the new entry."""

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)

    old_ep = _make_episode(id=10, show_id=1)
    old_ep.season_number = 3
    old_ep.episode_number = 7
    old_ep.file_tracked = True
    old_ep.tracked_filename = "/media/show.s03e07.mkv"
    old_ep.tracked_source = "import"
    old_ep.file_tracked_at = None

    # New episode list has no S03E07
    new_ep = _make_episode(id=50, show_id=1)
    new_ep.season_number = 1
    new_ep.episode_number = 1
    new_ep.file_tracked = False

    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    app.dependency_overrides[get_session] = _rematch_session(
        show,
        tracked_episodes=[old_ep],
        new_episodes=[new_ep],
    )
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            with patch("jidou.orchestrators.show_rematch_orchestrator.logger") as mock_logger:
                response = TestClient(app).post(
                    "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "tv"}
                )
                warning_calls = [
                    call
                    for call in mock_logger.warning.call_args_list
                    if "Unrecoverable" in str(call)
                ]
        assert response.status_code == 200
        assert len(warning_calls) == 1
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_preserve_tracking_false_skips_migration() -> None:
    """When preserve_tracking=False, no snapshot or migration queries are issued."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    app.dependency_overrides[get_session] = _rematch_session(
        show, preserve_tracking=False, media_type="tv"
    )
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            response = TestClient(app).post(
                "/api/shows/1/rematch",
                json={"tmdb_id": 200, "media_type": "tv", "preserve_tracking": False},
            )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_preserve_tracking_false_purges_orphan_rows() -> None:
    """preserve_tracking=False still issues the orphan dedup delete so the DQ tab is cleared."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    captured: list[AsyncMock] = []
    base_session = _rematch_session(show, preserve_tracking=False, media_type="tv")

    async def _capturing():
        async for s in base_session():
            captured.append(s)
            yield s

    app.dependency_overrides[get_session] = _capturing
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            response = TestClient(app).post(
                "/api/shows/1/rematch",
                json={"tmdb_id": 200, "media_type": "tv", "preserve_tracking": False},
            )
        assert response.status_code == 200
        # 4 execute calls: show lookup, conflict check, episode delete, orphan dedup delete
        assert captured[0].execute.call_count == 4
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_movie_skips_tracking_phases() -> None:
    """Movie rematch skips Phase 1/2/3 entirely — no tracked-episode queries."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100, media_type="movie")
    movie_data = {
        "title": "Great Film",
        "release_date": "2023-03-01",
        "overview": None,
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 7.0,
        "vote_count": 50,
        "original_language": "en",
        "genres": [],
        "runtime": 90,
        "tagline": None,
        "status": "Released",
        "networks": [],
    }
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=movie_data)

    app.dependency_overrides[get_session] = _rematch_session(show, media_type="movie")
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        response = TestClient(app).post(
            "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "movie"}
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_rematch_show_movie_purges_orphan_rows() -> None:
    """Movie rematch still purges stale orphan rows even though it has no episodes."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100, media_type="movie")
    movie_data = {
        "title": "Great Film",
        "release_date": "2023-03-01",
        "overview": None,
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 7.0,
        "vote_count": 50,
        "original_language": "en",
        "genres": [],
        "runtime": 90,
        "tagline": None,
        "status": "Released",
        "networks": [],
    }
    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=movie_data)

    captured: list[AsyncMock] = []
    base_session = _rematch_session(show, media_type="movie")

    async def _capturing():
        async for s in base_session():
            captured.append(s)
            yield s

    app.dependency_overrides[get_session] = _capturing
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        response = TestClient(app).post(
            "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "movie"}
        )
        assert response.status_code == 200
        # 4 execute calls: show lookup, conflict check, episode delete, orphan dedup delete
        assert captured[0].execute.call_count == 4
    finally:
        app.dependency_overrides.clear()


def test_rematch_creates_orphan_record_for_unresolvable_import() -> None:
    """An import-sourced tracked episode with no matching new S/E is persisted as an orphan."""
    from unittest.mock import patch as _patch

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session
    from jidou.models.orphan import OrphanedTrackingRecord

    show = _make_show(id=1, tmdb_id=100)

    old_ep = _make_episode(id=10, show_id=1)
    old_ep.season_number = 5
    old_ep.episode_number = 2
    old_ep.file_tracked = True
    old_ep.tracked_filename = "/media/show.s05e02.mkv"
    old_ep.tracked_source = "import"
    old_ep.file_tracked_at = None

    # New episodes have no S05E02
    new_ep = _make_episode(id=50, show_id=1)
    new_ep.season_number = 1
    new_ep.episode_number = 1
    new_ep.file_tracked = False

    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    added_objects: list[object] = []

    app.dependency_overrides[get_session] = _rematch_session(
        show,
        tracked_episodes=[old_ep],
        new_episodes=[new_ep],
    )
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with _patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            # Intercept session.add to capture OrphanedTrackingRecord instances.
            original_session_override = app.dependency_overrides[get_session]

            async def _capturing_session() -> AsyncMock:  # type: ignore[return]
                async for session in original_session_override():
                    real_add = session.add

                    def _add(obj: object, _orig: object = real_add) -> None:
                        added_objects.append(obj)
                        return _orig(obj)  # type: ignore[call-arg]

                    session.add = _add
                    yield session

            app.dependency_overrides[get_session] = _capturing_session
            response = TestClient(app).post(
                "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "tv"}
            )
        assert response.status_code == 200
        orphans_created = [o for o in added_objects if isinstance(o, OrphanedTrackingRecord)]
        assert len(orphans_created) == 1
        assert orphans_created[0].old_season_number == 5
        assert orphans_created[0].old_episode_number == 2
        assert orphans_created[0].tracked_source == "import"
        assert orphans_created[0].downloaded_file_id is None
    finally:
        app.dependency_overrides.clear()


def test_rematch_creates_orphan_record_for_unresolvable_downloaded_file() -> None:
    """A downloaded file that cannot be re-linked to a new episode is persisted as an orphan."""
    from unittest.mock import patch as _patch

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session
    from jidou.models.downloaded_file import DownloadedFile
    from jidou.models.orphan import OrphanedTrackingRecord

    show = _make_show(id=1, tmdb_id=100)

    # Orphaned file whose parsed S/E (S02E03) doesn't appear in new episode list
    orphaned_file = MagicMock(spec=DownloadedFile)
    orphaned_file.id = 77
    orphaned_file.show_id = 1
    orphaned_file.episode_id = None
    orphaned_file.parsed_season = 2
    orphaned_file.parsed_episode = 3
    orphaned_file.local_path = None  # must pin to avoid truthy MagicMock
    orphaned_file.original_filename = "show.s02e03.mkv"

    # New episodes: S01E01 only — no S02E03
    new_ep = _make_episode(id=50, show_id=1)
    new_ep.season_number = 1
    new_ep.episode_number = 1
    new_ep.file_tracked = False

    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    added_objects: list[object] = []

    app.dependency_overrides[get_session] = _rematch_session(
        show,
        new_episodes=[new_ep],
        orphaned_files=[orphaned_file],
    )
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with _patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            original_session_override = app.dependency_overrides[get_session]

            async def _capturing_session() -> AsyncMock:  # type: ignore[return]
                async for session in original_session_override():
                    real_add = session.add

                    def _add(obj: object, _orig: object = real_add) -> None:
                        added_objects.append(obj)
                        return _orig(obj)  # type: ignore[call-arg]

                    session.add = _add
                    yield session

            app.dependency_overrides[get_session] = _capturing_session
            response = TestClient(app).post(
                "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "tv"}
            )
        assert response.status_code == 200
        orphans_created = [o for o in added_objects if isinstance(o, OrphanedTrackingRecord)]
        assert len(orphans_created) == 1
        assert orphans_created[0].old_season_number == 2
        assert orphans_created[0].old_episode_number == 3
        assert orphans_created[0].tracked_source == "match"
        assert orphans_created[0].downloaded_file_id == 77
        # Phase 3 uses local_path or original_filename, matching what PATCH /files writes
        assert orphans_created[0].tracked_filename == "show.s02e03.mkv"
    finally:
        app.dependency_overrides.clear()


def test_rematch_phase3_orphan_uses_local_path_when_set() -> None:
    """Phase 3 stores local_path in tracked_filename when the file has a local path."""
    from unittest.mock import patch as _patch

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session
    from jidou.models.downloaded_file import DownloadedFile
    from jidou.models.orphan import OrphanedTrackingRecord

    show = _make_show(id=1, tmdb_id=100)

    orphaned_file = MagicMock(spec=DownloadedFile)
    orphaned_file.id = 77
    orphaned_file.show_id = 1
    orphaned_file.episode_id = None
    orphaned_file.parsed_season = 2
    orphaned_file.parsed_episode = 3
    orphaned_file.local_path = "/media/library/show.s02e03.mkv"
    orphaned_file.original_filename = "show.s02e03.mkv"

    new_ep = _make_episode(id=50, show_id=1)
    new_ep.season_number = 1
    new_ep.episode_number = 1
    new_ep.file_tracked = False

    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    added_objects: list[object] = []

    app.dependency_overrides[get_session] = _rematch_session(
        show, new_episodes=[new_ep], orphaned_files=[orphaned_file]
    )
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with _patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            original_session_override = app.dependency_overrides[get_session]

            async def _capturing_session() -> AsyncMock:  # type: ignore[return]
                async for session in original_session_override():
                    real_add = session.add

                    def _add(obj: object, _orig: object = real_add) -> None:
                        added_objects.append(obj)
                        return _orig(obj)  # type: ignore[call-arg]

                    session.add = _add
                    yield session

            app.dependency_overrides[get_session] = _capturing_session
            response = TestClient(app).post(
                "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "tv"}
            )
        assert response.status_code == 200
        orphans_created = [o for o in added_objects if isinstance(o, OrphanedTrackingRecord)]
        assert len(orphans_created) == 1
        assert orphans_created[0].tracked_filename == "/media/library/show.s02e03.mkv"
    finally:
        app.dependency_overrides.clear()


def test_rematch_creates_orphan_for_match_source_not_found_by_file_query() -> None:
    """A match-sourced tracked episode with no parseable file is still persisted as an orphan.

    Phase 3 only finds DownloadedFile rows with non-NULL parsed_season/episode.
    A file with NULL parsed_season won't appear in the orphan_stmt query.
    The unrecoverable_keys loop must catch and persist these match-sourced entries.
    """
    from unittest.mock import patch as _patch

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session
    from jidou.models.orphan import OrphanedTrackingRecord

    show = _make_show(id=1, tmdb_id=100)

    # A match-sourced tracked episode — the file has no parseable S/E numbers
    old_ep = _make_episode(id=10, show_id=1)
    old_ep.season_number = 5
    old_ep.episode_number = 2
    old_ep.file_tracked = True
    old_ep.tracked_filename = "/media/show.weird_name.mkv"
    old_ep.tracked_source = "match"
    old_ep.file_tracked_at = None

    # New episodes have no S05E02
    new_ep = _make_episode(id=50, show_id=1)
    new_ep.season_number = 1
    new_ep.episode_number = 1
    new_ep.file_tracked = False

    tmdb_mock = _make_tmdb_mock()
    tmdb_mock.get_details = AsyncMock(return_value=_TMDB_DETAIL)

    added_objects: list[object] = []

    # orphaned_files=[] simulates the file not appearing in the Phase 3 query
    # (e.g., parsed_season=NULL so it's excluded by the orphan_stmt WHERE clause)
    app.dependency_overrides[get_session] = _rematch_session(
        show,
        tracked_episodes=[old_ep],
        new_episodes=[new_ep],
        orphaned_files=[],
    )
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with _patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            original_session_override = app.dependency_overrides[get_session]

            async def _capturing_session() -> AsyncMock:  # type: ignore[return]
                async for session in original_session_override():
                    real_add = session.add

                    def _add(obj: object, _orig: object = real_add) -> None:
                        added_objects.append(obj)
                        return _orig(obj)  # type: ignore[call-arg]

                    session.add = _add
                    yield session

            app.dependency_overrides[get_session] = _capturing_session
            response = TestClient(app).post(
                "/api/shows/1/rematch", json={"tmdb_id": 200, "media_type": "tv"}
            )
        assert response.status_code == 200
        orphans_created = [o for o in added_objects if isinstance(o, OrphanedTrackingRecord)]
        assert len(orphans_created) == 1
        assert orphans_created[0].old_season_number == 5
        assert orphans_created[0].old_episode_number == 2
        assert orphans_created[0].tracked_source == "match"
        assert orphans_created[0].downloaded_file_id is None
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/shows/{show_id}/sync-episodes
# ---------------------------------------------------------------------------


def test_sync_episodes_returns_updated_episode_list() -> None:
    """POST /{id}/sync-episodes returns the refreshed episode list."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1)
    episode = _make_episode(id=10, show_id=1)

    async def _sync_session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalars.return_value.all.return_value = [episode]
        session.execute = AsyncMock(side_effect=[show_result, ep_result])
        yield session

    tmdb_mock = _make_tmdb_mock()
    app.dependency_overrides[get_session] = _sync_session
    app.dependency_overrides[get_tmdb] = lambda: tmdb_mock
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch:
            mock_orch.return_value.sync_show_episodes = AsyncMock()
            response = TestClient(app).post("/api/shows/1/sync-episodes")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) == 1
    finally:
        app.dependency_overrides.clear()


def test_sync_episodes_returns_404_when_show_not_found() -> None:
    """POST /{id}/sync-episodes returns 404 when show doesn't exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).post("/api/shows/9999/sync-episodes")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# _infer_content_type helper
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.mark.parametrize(
    "media_type,genres,genre_ids,original_language,origin_country,expected",
    [
        # Movies are always "movie" regardless of other fields.
        ("movie", None, None, None, None, "movie"),
        ("movie", [{"id": 16, "name": "Animation"}], None, "ja", ["JP"], "movie"),
        # Anime via genres objects: Animation genre + Japanese language.
        ("tv", [{"id": 16, "name": "Animation"}], None, "ja", None, "anime"),
        # Anime via genre_ids (search/trending card shape).
        ("tv", None, [16], "ja", None, "anime"),
        # Anime: Animation genre + JP origin country (even without ja language).
        ("tv", [{"id": 16, "name": "Animation"}], None, "en", ["JP"], "anime"),
        # Anime via genre_ids + JP origin.
        ("tv", None, [16, 18], "en", ["JP"], "anime"),
        # Not anime: Animation genre but not Japanese (e.g. Avatar).
        ("tv", [{"id": 16, "name": "Animation"}], None, "en", ["US"], "tv"),
        # Not anime: Japanese language but not animated (live action).
        ("tv", [{"id": 18, "name": "Drama"}], None, "ja", ["JP"], "tv"),
        # Default fallback.
        ("tv", None, None, "en", ["US"], "tv"),
        ("tv", [], [], None, None, "tv"),
    ],
)
def test_infer_content_type(
    media_type: str,
    genres: list[dict] | None,
    genre_ids: list[int] | None,
    original_language: str | None,
    origin_country: list[str] | None,
    expected: str,
) -> None:
    """_infer_content_type returns the correct routing category for each TMDB profile."""
    from jidou.api.routes.shows import _infer_content_type
    from jidou.schemas.show_schema import ShowCreate

    payload = ShowCreate(
        tmdb_id=1,
        title="Test",
        media_type=media_type,
        genres=genres,
        genre_ids=genre_ids,
        original_language=original_language,
        origin_country=origin_country,
    )
    assert _infer_content_type(payload) == expected


def test_create_show_infers_anime_content_type() -> None:
    """POST /api/shows without content_type infers 'anime' for Japanese animation."""
    from jidou.database import get_session

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)

        async def _flush() -> None:
            obj = session.add.call_args[0][0]
            obj.id = 42
            from datetime import UTC, datetime

            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        session.flush = AsyncMock(side_effect=_flush)
        session.add = MagicMock()
        yield session

    app.dependency_overrides[get_session] = _new_session
    try:
        response = TestClient(app).post(
            "/api/shows",
            json={
                "tmdb_id": 1001,
                "title": "Demon Slayer",
                "media_type": "tv",
                "genres": [{"id": 16, "name": "Animation"}],
                "original_language": "ja",
                "origin_country": ["JP"],
            },
        )
        assert response.status_code == 201
        assert response.json()["content_type"] == "anime"
    finally:
        app.dependency_overrides.clear()


def test_create_show_syncs_episodes_for_new_show() -> None:
    """POST /api/shows calls TMDBOrchestrator.sync_show_episodes for a newly created show."""
    from datetime import UTC, datetime

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)

        async def _flush() -> None:
            obj = session.add.call_args[0][0]
            obj.id = 77
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        session.flush = AsyncMock(side_effect=_flush)
        session.add = MagicMock()
        yield session

    async def _fake_tmdb() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_session] = _new_session
    app.dependency_overrides[get_tmdb] = _fake_tmdb
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
            mock_orch = MagicMock()
            mock_orch.sync_show_episodes = AsyncMock()
            mock_orch_cls.return_value = mock_orch

            response = TestClient(app).post(
                "/api/shows",
                json={"tmdb_id": 2001, "title": "New Show", "media_type": "tv"},
            )
        assert response.status_code == 201
        mock_orch.sync_show_episodes.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()


def test_create_show_episode_sync_failure_does_not_abort_creation() -> None:
    """POST /api/shows returns 201 even when episode sync raises an exception."""
    from datetime import UTC, datetime

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)

        async def _flush() -> None:
            obj = session.add.call_args[0][0]
            obj.id = 78
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        session.flush = AsyncMock(side_effect=_flush)
        session.add = MagicMock()
        yield session

    async def _fake_tmdb() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_session] = _new_session
    app.dependency_overrides[get_tmdb] = _fake_tmdb
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
            mock_orch = MagicMock()
            mock_orch.sync_show_episodes = AsyncMock(side_effect=RuntimeError("TMDB down"))
            mock_orch_cls.return_value = mock_orch

            response = TestClient(app).post(
                "/api/shows",
                json={"tmdb_id": 2002, "title": "Another Show", "media_type": "tv"},
            )
        assert response.status_code == 201
    finally:
        app.dependency_overrides.clear()


def test_create_show_commits_after_sync_before_alias_generation() -> None:
    """The show and any synced episodes commit before alias generation runs.

    Regression test for a Cursor Bugbot finding on PR-04: sync_show_episodes
    now only flushes (the caller owns the commit boundary). Without an
    explicit commit right after a successful sync, a subsequent DB-level
    failure during alias generation would roll back the sync's flushed
    episodes too, even though sync itself succeeded -- both steps are meant
    to be independently best-effort. Asserts the actual call order rather
    than just the response, since a mocked session can't demonstrate data
    loss directly.
    """
    from datetime import UTC, datetime

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    call_order: list[str] = []

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)

        async def _flush() -> None:
            obj = session.add.call_args[0][0]
            obj.id = 80
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        async def _commit() -> None:
            call_order.append("commit")

        session.flush = AsyncMock(side_effect=_flush)
        session.commit = AsyncMock(side_effect=_commit)
        session.add = MagicMock()
        yield session

    async def _fake_tmdb() -> MagicMock:
        return MagicMock()

    async def _sync_show_episodes(*_args: object, **_kwargs: object) -> None:
        call_order.append("sync")

    async def _generate_aliases(*_args: object, **_kwargs: object) -> None:
        call_order.append("alias")

    app.dependency_overrides[get_session] = _new_session
    app.dependency_overrides[get_tmdb] = _fake_tmdb
    try:
        with (
            patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls,
            patch(
                "jidou.orchestrators.alias_orchestrator.generate_aliases",
                new_callable=AsyncMock,
                side_effect=_generate_aliases,
            ),
        ):
            mock_orch = MagicMock()
            mock_orch.sync_show_episodes = AsyncMock(side_effect=_sync_show_episodes)
            mock_orch_cls.return_value = mock_orch

            response = TestClient(app).post(
                "/api/shows",
                json={"tmdb_id": 2005, "title": "Commit Order Show", "media_type": "tv"},
            )

        assert response.status_code == 201
        # commit must land between sync and alias generation, not after both.
        assert call_order == ["sync", "commit", "alias"]
    finally:
        app.dependency_overrides.clear()


def test_create_show_skips_episode_sync_for_movies() -> None:
    """POST /api/shows with media_type=movie must not call sync_show_episodes."""
    from datetime import UTC, datetime

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)

        async def _flush() -> None:
            obj = session.add.call_args[0][0]
            obj.id = 79
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        session.flush = AsyncMock(side_effect=_flush)
        session.add = MagicMock()
        yield session

    async def _fake_tmdb() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_session] = _new_session
    app.dependency_overrides[get_tmdb] = _fake_tmdb
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
            mock_orch = MagicMock()
            mock_orch.sync_show_episodes = AsyncMock()
            mock_orch_cls.return_value = mock_orch

            response = TestClient(app).post(
                "/api/shows",
                json={"tmdb_id": 2003, "title": "Some Movie", "media_type": "movie"},
            )
        assert response.status_code == 201
        mock_orch.sync_show_episodes.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


def test_create_show_db_error_during_sync_propagates() -> None:
    """POST /api/shows propagates SQLAlchemyError from sync so the show is not silently lost."""
    from datetime import UTC, datetime

    from sqlalchemy.exc import OperationalError

    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)

        async def _flush() -> None:
            obj = session.add.call_args[0][0]
            obj.id = 80
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        session.flush = AsyncMock(side_effect=_flush)
        session.add = MagicMock()
        yield session

    async def _fake_tmdb() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_session] = _new_session
    app.dependency_overrides[get_tmdb] = _fake_tmdb
    try:
        with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls:
            mock_orch = MagicMock()
            mock_orch.sync_show_episodes = AsyncMock(
                side_effect=OperationalError("conn lost", None, None)
            )
            mock_orch_cls.return_value = mock_orch

            response = TestClient(app, raise_server_exceptions=False).post(
                "/api/shows",
                json={"tmdb_id": 2004, "title": "DB Fail Show", "media_type": "tv"},
            )
        assert response.status_code == 500
    finally:
        app.dependency_overrides.clear()


def test_create_show_respects_explicit_content_type() -> None:
    """POST /api/shows with an explicit content_type does not overwrite it."""
    from jidou.database import get_session

    async def _new_session() -> AsyncMock:
        session = AsyncMock()
        result_no_hit = MagicMock()
        result_no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_no_hit)

        async def _flush() -> None:
            obj = session.add.call_args[0][0]
            obj.id = 43
            from datetime import UTC, datetime

            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        session.flush = AsyncMock(side_effect=_flush)
        session.add = MagicMock()
        yield session

    app.dependency_overrides[get_session] = _new_session
    try:
        response = TestClient(app).post(
            "/api/shows",
            json={
                "tmdb_id": 1002,
                "title": "Avatar",
                "media_type": "tv",
                "genres": [{"id": 16, "name": "Animation"}],
                "original_language": "en",
                "origin_country": ["US"],
                "content_type": "tv",  # user explicitly set this; must not be overwritten
            },
        )
        assert response.status_code == 201
        assert response.json()["content_type"] == "tv"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/shows/{show_id}/episodes/{episode_id}/begin-rematch
# ---------------------------------------------------------------------------


def _make_tracked_episode(*, id: int = 10, show_id: int = 1) -> MagicMock:
    ep = _make_episode(id=id, show_id=show_id)
    ep.file_tracked = True
    ep.tracked_filename = "/media/shows/show/Season 01/show.s01e01.mkv"
    ep.tracked_source = "match"
    ep.file_tracked_at = None
    return ep


def test_begin_episode_rematch_returns_404_when_show_missing() -> None:
    """Returns 404 when the show does not exist."""
    from jidou.database import get_session

    async def _session() -> AsyncMock:
        session = AsyncMock()
        no_hit = MagicMock()
        no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=no_hit)
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post("/api/shows/9999/episodes/1/begin-rematch")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_begin_episode_rematch_returns_404_when_episode_missing() -> None:
    """Returns 404 when the episode does not exist."""
    from jidou.database import get_session

    show = _make_show(id=1)

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[show_result, ep_result])
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post("/api/shows/1/episodes/9999/begin-rematch")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_begin_episode_rematch_returns_422_when_not_tracked() -> None:
    """Returns 422 when the episode is not tracked."""
    from jidou.database import get_session

    show = _make_show(id=1)
    ep = _make_episode(id=10, show_id=1)
    ep.file_tracked = False

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        session.execute = AsyncMock(side_effect=[show_result, ep_result])
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post("/api/shows/1/episodes/10/begin-rematch")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_begin_episode_rematch_resets_backing_file() -> None:
    """With a backing DownloadedFile, returns it without changing its status.

    Status is intentionally NOT reset to DOWNLOADED — doing so would enrol the
    file in the match-orchestrator before the user confirms, creating a race.
    """
    from jidou.database import get_session
    from jidou.models.downloaded_file import DownloadedFile, FileStatus

    show = _make_show(id=1)
    ep = _make_tracked_episode(id=10, show_id=1)
    backing = MagicMock(spec=DownloadedFile)
    backing.id = 99
    backing.show_id = 1
    backing.episode_id = 10
    backing.original_filename = "show.s01e01.mkv"
    backing.remote_path = "/path/show.s01e01.mkv"
    backing.local_path = "/staging/show.s01e01.mkv"
    backing.file_size = 1_000_000
    backing.hash_sha256 = None
    backing.status = FileStatus.ROUTED
    backing.matched_by = None
    backing.error_message = None
    backing.parsed_show_name = None
    backing.parsed_season = 1
    backing.parsed_episode = 1
    backing.parsed_confidence = None
    backing.parsed_content_type = None
    from datetime import UTC, datetime

    backing.created_at = datetime.now(UTC)
    backing.updated_at = datetime.now(UTC)
    backing.show = None
    backing.episode = None

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = backing
        session.execute = AsyncMock(side_effect=[show_result, ep_result, file_result])
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post("/api/shows/1/episodes/10/begin-rematch")
        assert response.status_code == 200
        # Episode tracking must NOT be cleared by begin-rematch
        assert ep.file_tracked is True
        # Status must NOT be changed — keep ROUTED to avoid auto-match race
        assert backing.status == FileStatus.ROUTED
    finally:
        app.dependency_overrides.clear()


def test_begin_episode_rematch_returns_422_for_import_episode() -> None:
    """With no backing DownloadedFile, returns 422 directing caller to assign-import."""
    from jidou.database import get_session

    show = _make_show(id=1)
    ep = _make_tracked_episode(id=10, show_id=1)
    ep.tracked_source = "import"

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        no_backing = MagicMock()
        no_backing.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[show_result, ep_result, no_backing])
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post("/api/shows/1/episodes/10/begin-rematch")
        assert response.status_code == 422
        assert "assign-import" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/shows/{show_id}/episodes/{episode_id}/assign-import
# ---------------------------------------------------------------------------


def test_assign_import_returns_404_when_show_missing() -> None:
    """Returns 404 when the show does not exist."""
    from jidou.database import get_session

    async def _session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/9999/episodes/1/assign-import",
            json={"filename": "/media/show/ep.mkv"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_assign_import_returns_404_when_episode_missing() -> None:
    """Returns 404 when the target episode does not exist."""
    from jidou.database import get_session

    show = _make_show(id=1)

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[show_result, ep_result])
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/9999/assign-import",
            json={"filename": "/media/show/ep.mkv"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_assign_import_returns_422_when_filename_not_in_import_pool() -> None:
    """Returns 422 when the filename is not import-tracked by any episode in the show."""
    from jidou.database import get_session

    show = _make_show(id=1)
    ep = _make_tracked_episode(id=10, show_id=1)

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[show_result, ep_result, source_result])
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/assign-import",
            json={"filename": "/media/show/nonexistent.mkv"},
        )
        assert response.status_code == 422
        assert "import pool" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_assign_import_returns_422_when_target_is_download_backed() -> None:
    """Returns 422 when the target episode is tracked via a downloaded file."""
    from jidou.database import get_session

    show = _make_show(id=1)
    source_ep = _make_tracked_episode(id=5, show_id=1)
    source_ep.tracked_filename = "/media/show/ep05.mkv"
    source_ep.tracked_source = "import"
    # Target is match-backed — must not be overwritten by assign-import.
    target_ep = _make_tracked_episode(id=10, show_id=1)
    target_ep.tracked_source = "match"
    target_ep.tracked_filename = "/media/show/ep10.mkv"

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_ep
        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = source_ep
        session.execute = AsyncMock(side_effect=[show_result, target_result, source_result])
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/assign-import",
            json={"filename": "/media/show/ep05.mkv"},
        )
        assert response.status_code == 422
        assert "downloaded file" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_assign_import_swaps_when_target_already_tracked() -> None:
    """When both source and target hold import filenames, the two are swapped.

    This keeps the displaced filename in the pool so it can be reassigned
    in a subsequent operation — the pool never shrinks mid-session.
    """
    from jidou.database import get_session

    show = _make_show(id=1)
    source_ep = _make_tracked_episode(id=5, show_id=1)
    source_ep.tracked_filename = "/media/show/ep05.mkv"
    source_ep.tracked_source = "import"
    target_ep = _make_tracked_episode(id=10, show_id=1)
    target_ep.tracked_filename = "/media/show/ep10.mkv"
    target_ep.tracked_source = "import"

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_ep
        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = source_ep
        no_synthetic_file = MagicMock()
        no_synthetic_file.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(
            side_effect=[
                show_result,
                target_result,
                source_result,
                no_synthetic_file,  # resync for displaced filename -> source_ep
                no_synthetic_file,  # resync for payload.filename -> target_ep
            ]
        )
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/assign-import",
            json={"filename": "/media/show/ep05.mkv"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        # Target gets the requested filename
        assert target_ep.tracked_filename == "/media/show/ep05.mkv"
        assert target_ep.tracked_source == "import"
        assert target_ep.file_tracked is True
        # Source receives target's displaced filename (swap — keeps it in the pool)
        assert source_ep.tracked_filename == "/media/show/ep10.mkv"
        assert source_ep.tracked_source == "import"
        assert source_ep.file_tracked is True
    finally:
        app.dependency_overrides.clear()


def test_assign_import_repoints_synthetic_files_to_new_episodes() -> None:
    """Swapping filenames also repoints each synthetic DownloadedFile's episode_id.

    Without this, the display-only file created by path-import (see
    PathImportOrchestrator._create_synthetic_import_file) would keep pointing
    at whichever episode held the filename before reassignment, so the Files
    page would list it under the wrong episode.
    """
    from jidou.database import get_session

    show = _make_show(id=1)
    source_ep = _make_tracked_episode(id=5, show_id=1)
    source_ep.tracked_filename = "/media/show/ep05.mkv"
    source_ep.tracked_source = "import"
    target_ep = _make_tracked_episode(id=10, show_id=1)
    target_ep.tracked_filename = "/media/show/ep10.mkv"
    target_ep.tracked_source = "import"

    displaced_file = MagicMock(episode_id=10)  # currently on target_ep
    reassigned_file = MagicMock(episode_id=5)  # currently on source_ep

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_ep
        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = source_ep
        displaced_file_result = MagicMock()
        displaced_file_result.scalar_one_or_none.return_value = displaced_file
        reassigned_file_result = MagicMock()
        reassigned_file_result.scalar_one_or_none.return_value = reassigned_file
        session.execute = AsyncMock(
            side_effect=[
                show_result,
                target_result,
                source_result,
                displaced_file_result,  # resync for displaced ("ep10.mkv") -> source_ep
                reassigned_file_result,  # resync for payload ("ep05.mkv") -> target_ep
            ]
        )
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/assign-import",
            json={"filename": "/media/show/ep05.mkv"},
        )
        assert response.status_code == 200
        # The file for "ep10.mkv" (displaced back to source) now points at source_ep.
        assert displaced_file.episode_id == source_ep.id
        # The file for "ep05.mkv" (assigned to target) now points at target_ep.
        assert reassigned_file.episode_id == target_ep.id
    finally:
        app.dependency_overrides.clear()


def test_assign_import_clears_source_when_target_untracked() -> None:
    """When target is untracked, source is cleared (no filename to displace)."""
    from jidou.database import get_session

    show = _make_show(id=1)
    source_ep = _make_tracked_episode(id=5, show_id=1)
    source_ep.tracked_filename = "/media/show/ep05.mkv"
    source_ep.tracked_source = "import"
    target_ep = _make_tracked_episode(id=10, show_id=1)
    target_ep.file_tracked = False
    target_ep.tracked_filename = None
    target_ep.tracked_source = None

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_ep
        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = source_ep
        no_synthetic_file = MagicMock()
        no_synthetic_file.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(
            side_effect=[
                show_result,
                target_result,
                source_result,
                no_synthetic_file,  # resync for payload.filename -> target_ep
            ]
        )
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/assign-import",
            json={"filename": "/media/show/ep05.mkv"},
        )
        assert response.status_code == 200
        # Target receives the filename
        assert target_ep.tracked_filename == "/media/show/ep05.mkv"
        assert target_ep.file_tracked is True
        # Source is cleared (no displaced filename to give back)
        assert source_ep.file_tracked is False
        assert source_ep.tracked_filename is None
    finally:
        app.dependency_overrides.clear()


def test_assign_import_no_op_when_source_equals_target() -> None:
    """When the filename is already on the target episode, nothing changes."""
    from jidou.database import get_session

    show = _make_show(id=1)
    ep = _make_tracked_episode(id=10, show_id=1)
    ep.tracked_filename = "/media/show/ep10.mkv"
    ep.tracked_source = "import"

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = ep
        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = ep  # same episode
        no_synthetic_file = MagicMock()
        no_synthetic_file.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(
            side_effect=[
                show_result,
                target_result,
                source_result,
                no_synthetic_file,  # resync for payload.filename -> target_ep
            ]
        )
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/assign-import",
            json={"filename": "/media/show/ep10.mkv"},
        )
        assert response.status_code == 200
        # Episode tracking unchanged
        assert ep.file_tracked is True
        assert ep.tracked_filename == "/media/show/ep10.mkv"
    finally:
        app.dependency_overrides.clear()


def test_begin_episode_rematch_with_file_id_returns_404_when_not_found() -> None:
    """Returns 404 when the specified file_id is not linked to the episode."""
    from jidou.database import get_session

    show = _make_show(id=1)
    ep = _make_tracked_episode(id=10, show_id=1)

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[show_result, ep_result, file_result])
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post("/api/shows/1/episodes/10/begin-rematch?file_id=999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/shows/{show_id}/episodes/{episode_id}/link-file
# ---------------------------------------------------------------------------


def _make_linked_file(
    *, show_id: int = 1, episode_id: int = 10, raw_path: str = "/media/show/ep01.mkv"
) -> MagicMock:
    """Build a minimal synthetic DownloadedFile mock suitable for FileRead responses."""
    from datetime import UTC, datetime

    from jidou.models.downloaded_file import DownloadedFile, FileStatus

    f = MagicMock(spec=DownloadedFile)
    f.id = 55
    f.show_id = show_id
    f.episode_id = episode_id
    f.original_filename = "ep01.mkv"
    f.remote_path = f"synthetic-import://{raw_path}"
    f.local_path = raw_path
    f.file_size = 0
    f.hash_sha256 = None
    f.status = FileStatus.ROUTED
    f.matched_by = None
    f.error_message = None
    f.parsed_show_name = None
    f.parsed_season = None
    f.parsed_episode = None
    f.parsed_confidence = None
    f.parsed_content_type = None
    f.created_at = datetime.now(UTC)
    f.updated_at = datetime.now(UTC)
    f.show = None
    f.episode = None
    return f


def test_link_file_returns_404_when_show_missing() -> None:
    """Returns 404 when the show does not exist."""
    from jidou.database import get_session

    async def _session() -> AsyncMock:
        session = AsyncMock()
        no_hit = MagicMock()
        no_hit.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=no_hit)
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/9999/episodes/1/link-file",
            json={"path": "/media/show/ep01.mkv"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_link_file_returns_404_when_episode_missing() -> None:
    """Returns 404 when the episode does not exist."""
    from jidou.database import get_session

    show = _make_show(id=1)

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[show_result, ep_result])
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/9999/link-file",
            json={"path": "/media/show/ep01.mkv"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_link_file_returns_422_when_episode_already_tracked() -> None:
    """Returns 422 when the episode is already tracked by a file or import."""
    from jidou.database import get_session

    show = _make_show(id=1)
    ep = _make_tracked_episode(id=10, show_id=1)

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        session.execute = AsyncMock(side_effect=[show_result, ep_result])
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/link-file",
            json={"path": "/media/show/ep01.mkv"},
        )
        assert response.status_code == 422
        assert "already tracked" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_link_file_returns_422_when_path_does_not_exist(tmp_path: Path) -> None:
    """Returns 422 when the given path does not point to an existing file."""
    from jidou.database import get_session

    show = _make_show(id=1)
    ep = _make_episode(id=10, show_id=1)
    missing_path = str(tmp_path / "does-not-exist.mkv")

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        session.execute = AsyncMock(side_effect=[show_result, ep_result])
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/link-file",
            json={"path": missing_path},
        )
        assert response.status_code == 422
        assert "No file exists" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_link_file_creates_synthetic_file_and_tracks_episode(tmp_path: Path) -> None:
    """On success, marks the episode tracked (source=import) and returns the file."""
    from jidou.database import get_session

    show = _make_show(id=1)
    ep = _make_episode(id=10, show_id=1)
    real_file = tmp_path / "ep01.mkv"
    real_file.write_text("data")
    raw_path = str(real_file)

    linked = _make_linked_file(show_id=1, episode_id=10, raw_path=raw_path)

    async def _session() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        dedup_result = MagicMock()
        dedup_result.scalar_one_or_none.return_value = None
        refetch_result = MagicMock()
        refetch_result.scalar_one.return_value = linked
        session.execute = AsyncMock(
            side_effect=[show_result, ep_result, dedup_result, refetch_result]
        )
        nested_ctx = AsyncMock()
        nested_ctx.__aenter__.return_value = None
        nested_ctx.__aexit__.return_value = False
        session.begin_nested = MagicMock(return_value=nested_ctx)
        session.add = MagicMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).post(
            "/api/shows/1/episodes/10/link-file",
            json={"path": raw_path},
        )
        assert response.status_code == 200
        assert ep.file_tracked is True
        assert ep.tracked_source == "import"
        assert ep.tracked_filename == raw_path
        assert response.json()["id"] == linked.id
    finally:
        app.dependency_overrides.clear()
