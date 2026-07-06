"""Tests for the /dashboard API routes."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from jidou.api.routes.dashboard import _build_recent_episodes_stmt, _build_recent_shows_stmt
from jidou.database import get_session
from jidou.main import app


def _compile(stmt: object) -> tuple[str, dict[str, object]]:
    """Compile a statement against the postgresql dialect for SQL assertions."""
    compiled = stmt.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    return str(compiled), dict(compiled.params)


# ---------------------------------------------------------------------------
# _build_recent_shows_stmt
# ---------------------------------------------------------------------------


class TestBuildRecentShowsStmt:
    def test_tracked_sort_orders_by_created_at(self) -> None:
        sql, _ = _compile(_build_recent_shows_stmt("tracked", None, None, True, 12))
        assert "ORDER BY shows.created_at DESC" in sql

    def test_release_sort_orders_by_release_date_nulls_last(self) -> None:
        sql, _ = _compile(_build_recent_shows_stmt("release", None, None, True, 12))
        assert "ORDER BY shows.release_date DESC NULLS LAST" in sql

    def test_content_type_filter_applied_when_given(self) -> None:
        sql, params = _compile(_build_recent_shows_stmt("tracked", "anime", None, True, 12))
        assert "shows.content_type = " in sql
        assert params["content_type_1"] == "anime"

    def test_no_where_clause_when_all_filters_absent(self) -> None:
        # select(Show) always SELECTs the content_type/genres/adult columns,
        # so absence of a filter must be checked via the WHERE clause, not
        # bare substring presence.
        sql, _ = _compile(_build_recent_shows_stmt("tracked", None, None, True, 12))
        assert "WHERE" not in sql

    def test_genre_filter_uses_jsonb_containment(self) -> None:
        sql, params = _compile(_build_recent_shows_stmt("tracked", None, "Action", True, 12))
        assert "shows.genres @>" in sql
        assert params["genres_1"] == [{"name": "Action"}]

    def test_adult_clause_present_when_include_adult_false(self) -> None:
        sql, _ = _compile(_build_recent_shows_stmt("tracked", None, None, False, 12))
        assert "shows.adult IS NOT true" in sql

    def test_adult_clause_absent_when_include_adult_true(self) -> None:
        sql, _ = _compile(_build_recent_shows_stmt("tracked", None, None, True, 12))
        assert "adult IS NOT" not in sql

    def test_limit_propagated(self) -> None:
        _, params = _compile(_build_recent_shows_stmt("tracked", None, None, True, 37))
        assert params["param_1"] == 37


# ---------------------------------------------------------------------------
# _build_recent_episodes_stmt
# ---------------------------------------------------------------------------


class TestBuildRecentEpisodesStmt:
    def test_only_tracked_episodes_included(self) -> None:
        sql, _ = _compile(_build_recent_episodes_stmt("tracked", None, None, True, 12))
        assert "episodes.file_tracked" in sql

    def test_joins_show_table(self) -> None:
        sql, _ = _compile(_build_recent_episodes_stmt("tracked", None, None, True, 12))
        assert "JOIN shows ON episodes.show_id = shows.id" in sql

    def test_tracked_sort_orders_by_file_tracked_at(self) -> None:
        sql, _ = _compile(_build_recent_episodes_stmt("tracked", None, None, True, 12))
        assert "ORDER BY episodes.file_tracked_at DESC NULLS LAST" in sql

    def test_release_sort_orders_by_air_date(self) -> None:
        sql, _ = _compile(_build_recent_episodes_stmt("release", None, None, True, 12))
        assert "ORDER BY episodes.air_date DESC NULLS LAST" in sql

    def test_content_type_filter_on_joined_show(self) -> None:
        sql, params = _compile(_build_recent_episodes_stmt("tracked", "tv", None, True, 12))
        assert "shows.content_type = " in sql
        assert params["content_type_1"] == "tv"

    def test_genre_filter_on_joined_show(self) -> None:
        sql, params = _compile(_build_recent_episodes_stmt("tracked", None, "Drama", True, 12))
        assert "shows.genres @>" in sql
        assert params["genres_1"] == [{"name": "Drama"}]

    def test_adult_clause_present_when_include_adult_false(self) -> None:
        sql, _ = _compile(_build_recent_episodes_stmt("tracked", None, None, False, 12))
        assert "shows.adult IS NOT true" in sql

    def test_limit_propagated(self) -> None:
        _, params = _compile(_build_recent_episodes_stmt("tracked", None, None, True, 5))
        assert params["param_1"] == 5


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def _session_override(execute_return: object) -> "type[AsyncMock]":
    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=execute_return)
        yield session

    return _mock_session  # type: ignore[return-value]


class TestGetRecentShows:
    def test_returns_empty_list(self) -> None:
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        app.dependency_overrides[get_session] = _session_override(result)
        try:
            with patch(
                "jidou.api.routes.dashboard.get_show_adult_content",
                AsyncMock(return_value=False),
            ):
                resp = TestClient(app).get("/api/dashboard/recent-shows")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides.clear()

    def test_invalid_sort_returns_422(self) -> None:
        app.dependency_overrides[get_session] = _session_override(MagicMock())
        try:
            resp = TestClient(app).get("/api/dashboard/recent-shows?sort=bogus")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_limit_zero_returns_422(self) -> None:
        app.dependency_overrides[get_session] = _session_override(MagicMock())
        try:
            resp = TestClient(app).get("/api/dashboard/recent-shows?limit=0")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_limit_over_max_returns_422(self) -> None:
        app.dependency_overrides[get_session] = _session_override(MagicMock())
        try:
            resp = TestClient(app).get("/api/dashboard/recent-shows?limit=999")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_consults_adult_content_setting(self) -> None:
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        app.dependency_overrides[get_session] = _session_override(result)
        mock_get_adult = AsyncMock(return_value=False)
        try:
            with patch("jidou.api.routes.dashboard.get_show_adult_content", mock_get_adult):
                TestClient(app).get("/api/dashboard/recent-shows")
            mock_get_adult.assert_awaited_once()
        finally:
            app.dependency_overrides.clear()


class TestGetRecentEpisodes:
    def test_returns_empty_list(self) -> None:
        result = MagicMock()
        result.all.return_value = []
        app.dependency_overrides[get_session] = _session_override(result)
        try:
            with patch(
                "jidou.api.routes.dashboard.get_show_adult_content",
                AsyncMock(return_value=False),
            ):
                resp = TestClient(app).get("/api/dashboard/recent-episodes")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides.clear()

    def test_maps_episode_and_show_pair_to_schema(self) -> None:
        from datetime import UTC, date, datetime

        ep = MagicMock()
        ep.id = 1
        ep.show_id = 42
        ep.season_number = 1
        ep.episode_number = 3
        ep.name = "Pilot"
        ep.overview = "First episode"
        ep.air_date = date(2024, 1, 1)
        ep.file_tracked_at = datetime(2024, 6, 1, tzinfo=UTC)
        ep.still_path = "/still.jpg"
        ep.runtime = 24

        show = MagicMock()
        show.id = 42
        show.title = "Test Show"
        show.content_type = "anime"
        show.media_type = "tv"
        show.poster_path = "/poster.jpg"
        show.vote_average = 8.1
        show.genres = [{"id": 16, "name": "Animation"}]
        show.adult = False

        result = MagicMock()
        result.all.return_value = [(ep, show)]
        app.dependency_overrides[get_session] = _session_override(result)
        try:
            with patch(
                "jidou.api.routes.dashboard.get_show_adult_content",
                AsyncMock(return_value=False),
            ):
                resp = TestClient(app).get("/api/dashboard/recent-episodes")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body) == 1
            assert body[0]["name"] == "Pilot"
            assert body[0]["show"]["title"] == "Test Show"
        finally:
            app.dependency_overrides.clear()

    def test_invalid_sort_returns_422(self) -> None:
        app.dependency_overrides[get_session] = _session_override(MagicMock())
        try:
            resp = TestClient(app).get("/api/dashboard/recent-episodes?sort=bogus")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestGetDashboardGenres:
    def test_returns_sorted_genre_list(self) -> None:
        result = MagicMock()
        result.all.return_value = [("Action",), ("Drama",)]
        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/dashboard/genres")
            assert resp.status_code == 200
            assert resp.json() == ["Action", "Drama"]
        finally:
            app.dependency_overrides.clear()

    def test_returns_empty_list_when_no_genres(self) -> None:
        result = MagicMock()
        result.all.return_value = []
        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/dashboard/genres")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides.clear()
