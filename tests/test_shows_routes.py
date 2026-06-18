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
    remote_path: str | None = None,
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
    s.remote_path = remote_path
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
        result.scalar_one_or_none.return_value = single
        result.scalars.return_value.all.return_value = many or ([single] if single else [])
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


def test_update_paths_returns_updated_show() -> None:
    """PUT /api/shows/{id}/paths returns the show with updated paths."""
    from jidou.database import get_session

    show = _make_show(id=1)
    app.dependency_overrides[get_session] = _session_override(single=show)
    try:
        response = TestClient(app).put(
            "/api/shows/1/paths",
            json={"remote_path": "/shows/test", "local_path": "/media/test"},
        )
        assert response.status_code == 200
        # Path fields are set on the mock object by the route handler
        # so the response reflects whatever the mock has now.
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
            json={"remote_path": "/x"},
        )
        assert response.status_code == 404
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
