"""Tests for the /shows API routes."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.episode import Episode
from jidou.models.show import Show


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
    s.genres = None
    s.origin_country = None
    s.last_air_date = None
    s.last_episode_to_air = None
    s.next_episode_to_air = None
    s.homepage = None
    s.external_ids = None
    s.episode_groups = None
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
    ep.created_at = datetime.now(UTC)
    ep.updated_at = datetime.now(UTC)
    return ep


def _session_override(
    single: MagicMock | None = None,
    many: list[MagicMock] | None = None,
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
        # list_shows returns (show, ep_count) tuples via .all()
        result.all.return_value = [(item, 0, 0) for item in items]
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
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
        """First execute returns the show; second returns episodes."""
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show

        ep_result = MagicMock()
        ep_result.scalars.return_value.all.return_value = [episode]

        session.execute = AsyncMock(side_effect=[show_result, ep_result])
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _two_query_session
    try:
        response = TestClient(app).get("/api/shows/1/episodes")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["episode_number"] == 1
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


def _rematch_session(show: MagicMock, conflict: MagicMock | None = None) -> "type[AsyncMock]":
    """Return a session override for rematch tests.

    Yields a session whose execute calls return:
      1. show lookup
      2. conflict check (only when show.tmdb_id differs from payload)
      3. episode bulk-delete result (unused)
    """

    async def _mock() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        conflict_result = MagicMock()
        conflict_result.scalar_one_or_none.return_value = conflict
        delete_result = MagicMock()
        session.execute = AsyncMock(side_effect=[show_result, conflict_result, delete_result])
        session.flush = AsyncMock()
        yield session

    return _mock  # type: ignore[return-value]


def test_rematch_show_returns_200_on_success() -> None:
    """POST /{id}/rematch replaces metadata and syncs episodes; returns 200."""
    from jidou.api.routes.shows import get_tmdb
    from jidou.database import get_session

    show = _make_show(id=1, tmdb_id=100)
    tmdb_mock = AsyncMock()
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
    tmdb_mock = AsyncMock()
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
    tmdb_mock = AsyncMock()
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
    tmdb_mock = AsyncMock()
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
    tmdb_mock = AsyncMock()
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

    tmdb_mock = AsyncMock()
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
