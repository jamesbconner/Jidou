"""Tests for the /settings API routes."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from jidou.config import settings
from jidou.database import get_session
from jidou.main import app
from jidou.services.settings_service import (
    CALENDAR_ENABLED,
    DASHBOARD_PAGE_ENABLED,
    DISCOVER_ENABLED,
    METADATA_REFRESH_ENABLED,
    METADATA_REFRESH_HOURS,
    METADATA_REFRESH_LIMIT,
    RECENT_EPISODES_ENABLED,
    RECENT_EPISODES_PREFER_POSTERS,
    RECENT_MOVIES_ENABLED,
    SHOW_ADULT_CONTENT,
    SIMILAR_TITLES_COUNT,
    SIMILAR_TITLES_ENABLED,
    SIMILAR_TITLES_INCLUDE_EXTERNAL,
)

# The metadata-refresh fields default to the SHOW_METADATA_REFRESH_* env settings.
_REFRESH_DEFAULTS = {
    "metadata_refresh_schedule_enabled": settings.show_metadata_refresh_schedule_enabled,
    "metadata_refresh_schedule_hours": settings.show_metadata_refresh_schedule_hours,
    "metadata_refresh_limit_per_run": settings.show_metadata_refresh_limit_per_run,
}


def _session_override(execute_return: object) -> "type[AsyncMock]":
    """Session whose execute() always returns the given mock result."""

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=execute_return)
        session.flush = AsyncMock()
        yield session

    return _mock_session  # type: ignore[return-value]


def _empty_settings_result() -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    return result


class TestGetSettings:
    def test_returns_defaults_when_table_empty(self) -> None:
        """GET /settings with no stored rows returns the default values."""
        app.dependency_overrides[get_session] = _session_override(_empty_settings_result())
        try:
            resp = TestClient(app).get("/api/settings")
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
        finally:
            app.dependency_overrides.clear()

    def test_returns_stored_value(self) -> None:
        """GET /settings reflects a previously stored value."""
        row = MagicMock()
        row.key = "dashboard.show_adult_content"
        row.value = True
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]

        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/settings")
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": True,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
        finally:
            app.dependency_overrides.clear()

    def test_returns_stored_calendar_enabled_value(self) -> None:
        """GET /settings reflects a previously stored calendar_enabled=False."""
        row = MagicMock()
        row.key = "dashboard.calendar_enabled"
        row.value = False
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]

        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/settings")
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": False,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
        finally:
            app.dependency_overrides.clear()

    def test_returns_stored_discover_enabled_value(self) -> None:
        """GET /settings reflects a previously stored discover_enabled=False."""
        row = MagicMock()
        row.key = "dashboard.discover_enabled"
        row.value = False
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]

        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/settings")
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": False,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
        finally:
            app.dependency_overrides.clear()

    def test_returns_stored_dashboard_page_enabled_value(self) -> None:
        """GET /settings reflects a previously stored dashboard_page_enabled=False."""
        row = MagicMock()
        row.key = "pages.dashboard_enabled"
        row.value = False
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]

        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/settings")
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": False,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
        finally:
            app.dependency_overrides.clear()

    def test_returns_stored_recent_episodes_enabled_value(self) -> None:
        """GET /settings reflects a previously stored recent_episodes_enabled=False."""
        row = MagicMock()
        row.key = "dashboard.recent_episodes_enabled"
        row.value = False
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]

        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/settings")
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": False,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
        finally:
            app.dependency_overrides.clear()

    def test_returns_stored_recent_movies_enabled_value(self) -> None:
        """GET /settings reflects a previously stored recent_movies_enabled=False."""
        row = MagicMock()
        row.key = "dashboard.recent_movies_enabled"
        row.value = False
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]

        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/settings")
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": False,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
        finally:
            app.dependency_overrides.clear()

    def test_returns_stored_recent_episodes_prefer_posters_value(self) -> None:
        """GET /settings reflects a previously stored recent_episodes_prefer_posters=True."""
        row = MagicMock()
        row.key = "dashboard.recent_episodes_prefer_posters"
        row.value = True
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]

        app.dependency_overrides[get_session] = _session_override(result)
        try:
            resp = TestClient(app).get("/api/settings")
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": True,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
        finally:
            app.dependency_overrides.clear()


class TestUpdateSettings:
    def test_patch_updates_show_adult_content(self) -> None:
        """PATCH /settings with show_adult_content applies the update and returns state."""
        row = MagicMock()
        row.key = "dashboard.show_adult_content"
        row.value = True
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={"show_adult_content": True})
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": True,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
            # First execute() call is the upsert; second is the re-fetch in get_all_settings.
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_updates_calendar_enabled(self) -> None:
        """PATCH /settings with calendar_enabled applies the update and returns state."""
        row = MagicMock()
        row.key = "dashboard.calendar_enabled"
        row.value = False
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={"calendar_enabled": False})
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": False,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_updates_discover_enabled(self) -> None:
        """PATCH /settings with discover_enabled applies the update and returns state."""
        row = MagicMock()
        row.key = "dashboard.discover_enabled"
        row.value = False
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={"discover_enabled": False})
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": False,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_updates_dashboard_page_enabled(self) -> None:
        """PATCH /settings with dashboard_page_enabled applies the update and returns state."""
        row = MagicMock()
        row.key = "pages.dashboard_enabled"
        row.value = False
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={"dashboard_page_enabled": False})
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": False,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_updates_recent_episodes_enabled(self) -> None:
        """PATCH /settings with recent_episodes_enabled applies the update and returns state."""
        row = MagicMock()
        row.key = "dashboard.recent_episodes_enabled"
        row.value = False
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={"recent_episodes_enabled": False})
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": False,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_updates_recent_movies_enabled(self) -> None:
        """PATCH /settings with recent_movies_enabled applies the update and returns state."""
        row = MagicMock()
        row.key = "dashboard.recent_movies_enabled"
        row.value = False
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={"recent_movies_enabled": False})
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": False,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_updates_recent_episodes_prefer_posters(self) -> None:
        """PATCH /settings with recent_episodes_prefer_posters applies the update."""
        row = MagicMock()
        row.key = "dashboard.recent_episodes_prefer_posters"
        row.value = True
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch(
                "/api/settings", json={"recent_episodes_prefer_posters": True}
            )
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": True,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_updates_similar_titles_count(self) -> None:
        """PATCH /settings with similar_titles_count applies the update and returns state."""
        row = MagicMock()
        row.key = "recommendations.similar_titles_count"
        row.value = 25
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={"similar_titles_count": 25})
            assert resp.status_code == 200
            assert resp.json()["similar_titles_count"] == 25
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_updates_similar_titles_include_external(self) -> None:
        """PATCH /settings with similar_titles_include_external=False is applied."""
        row = MagicMock()
        row.key = "recommendations.similar_titles_include_external"
        row.value = False
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = [row]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None, result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch(
                "/api/settings", json={"similar_titles_include_external": False}
            )
            assert resp.status_code == 200
            assert resp.json()["similar_titles_include_external"] is False
            assert session.execute.await_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_patch_similar_titles_count_out_of_range_returns_422(self) -> None:
        """PATCH /settings rejects a similar_titles_count above the schema bound."""
        app.dependency_overrides[get_session] = _session_override(_empty_settings_result())
        try:
            resp = TestClient(app).patch("/api/settings", json={"similar_titles_count": 999})
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_patch_empty_body_is_a_noop(self) -> None:
        """PATCH /settings with an empty body does not write and just returns current state."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_empty_settings_result())
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={})
            assert resp.status_code == 200
            assert resp.json() == {
                "show_adult_content": False,
                "calendar_enabled": True,
                "discover_enabled": True,
                "dashboard_page_enabled": True,
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
                "recent_episodes_prefer_posters": False,
                "similar_titles_enabled": True,
                "similar_titles_count": 12,
                "similar_titles_include_external": True,
                **_REFRESH_DEFAULTS,
            }
            # Only the get_all_settings read — no upsert executed.
            assert session.execute.await_count == 1
        finally:
            app.dependency_overrides.clear()

    def test_patch_wrong_type_returns_422(self) -> None:
        """PATCH /settings with a non-boolean show_adult_content returns 422."""
        app.dependency_overrides[get_session] = _session_override(_empty_settings_result())
        try:
            # Pydantic's default bool coercion accepts strings like "yes"/"no",
            # so this must be a value with no such coercion path.
            resp = TestClient(app).patch("/api/settings", json={"show_adult_content": "banana"})
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_patch_all_fields_upserts_each_once(self) -> None:
        """A PATCH carrying every field issues one upsert per field, then one re-fetch."""
        payload = {
            "show_adult_content": True,
            "calendar_enabled": False,
            "discover_enabled": False,
            "dashboard_page_enabled": False,
            "recent_episodes_enabled": False,
            "recent_movies_enabled": False,
            "recent_episodes_prefer_posters": True,
            "similar_titles_enabled": False,
            "similar_titles_count": 5,
            "similar_titles_include_external": False,
        }
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[None] * len(payload) + [result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json=payload)
            assert resp.status_code == 200
            assert session.execute.await_count == len(payload) + 1
            session.flush.assert_awaited()
        finally:
            app.dependency_overrides.clear()

    def test_patch_empty_body_writes_nothing(self) -> None:
        """An empty PATCH performs no upsert and no flush; it only re-reads state."""
        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[result_after])
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            resp = TestClient(app).patch("/api/settings", json={})
            assert resp.status_code == 200
            assert session.execute.await_count == 1
            session.flush.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()


class TestPatchCharacterization:
    """Pin the PATCH write plan (keys, values, order) independent of how it is implemented."""

    @staticmethod
    def _patch(json_body: dict[str, object]) -> tuple[int, list[tuple[str, object]], AsyncMock]:
        from unittest.mock import patch

        calls: list[tuple[str, object]] = []

        async def _fake_set(_session: object, key: str, value: object) -> None:
            calls.append((key, value))

        result_after = MagicMock()
        result_after.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_after)
        session.flush = AsyncMock()

        async def _mock_session() -> AsyncMock:
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            with patch("jidou.api.routes.settings.set_setting", _fake_set):
                resp = TestClient(app).patch("/api/settings", json=json_body)
        finally:
            app.dependency_overrides.clear()
        return resp.status_code, calls, session

    def test_all_fields_written_in_declared_order_with_expected_keys(self) -> None:
        status, calls, _ = self._patch(
            {
                "similar_titles_include_external": False,
                "similar_titles_count": 5,
                "similar_titles_enabled": False,
                "recent_episodes_prefer_posters": True,
                "recent_movies_enabled": False,
                "recent_episodes_enabled": False,
                "dashboard_page_enabled": False,
                "discover_enabled": False,
                "calendar_enabled": False,
                "show_adult_content": True,
                "metadata_refresh_limit_per_run": 25,
                "metadata_refresh_schedule_hours": "16, 4",
                "metadata_refresh_schedule_enabled": False,
            }
        )
        assert status == 200
        assert calls == [
            (SHOW_ADULT_CONTENT, True),
            (CALENDAR_ENABLED, False),
            (DISCOVER_ENABLED, False),
            (DASHBOARD_PAGE_ENABLED, False),
            (RECENT_EPISODES_ENABLED, False),
            (RECENT_MOVIES_ENABLED, False),
            (RECENT_EPISODES_PREFER_POSTERS, True),
            (SIMILAR_TITLES_ENABLED, False),
            (SIMILAR_TITLES_COUNT, 5),
            (SIMILAR_TITLES_INCLUDE_EXTERNAL, False),
            (METADATA_REFRESH_ENABLED, False),
            (METADATA_REFRESH_HOURS, "4,16"),  # normalised before it is stored
            (METADATA_REFRESH_LIMIT, 25),
        ]

    def test_partial_body_writes_only_present_fields(self) -> None:
        status, calls, session = self._patch({"discover_enabled": False, "similar_titles_count": 3})
        assert status == 200
        assert calls == [(DISCOVER_ENABLED, False), (SIMILAR_TITLES_COUNT, 3)]
        session.flush.assert_awaited()

    def test_explicit_null_is_written_as_null(self) -> None:
        status, calls, _ = self._patch({"calendar_enabled": None})
        assert status == 200
        assert calls == [(CALENDAR_ENABLED, None)]

    def test_unknown_field_is_rejected_without_writes(self) -> None:
        status, calls, session = self._patch({"bogus": True})
        assert status == 422
        assert calls == []
        session.flush.assert_not_awaited()

    def test_out_of_range_count_is_rejected_without_writes(self) -> None:
        status, calls, session = self._patch({"calendar_enabled": False, "similar_titles_count": 0})
        assert status == 422
        assert calls == []
        session.flush.assert_not_awaited()


class TestMetadataRefreshPatch:
    """Validation and write plan for the metadata-refresh schedule fields."""

    # The helper clears every dependency override when it finishes, so each test
    # makes exactly one request.
    _patch = staticmethod(TestPatchCharacterization._patch)

    @pytest.mark.parametrize(
        ("field", "value", "key", "stored"),
        [
            ("metadata_refresh_schedule_enabled", False, METADATA_REFRESH_ENABLED, False),
            ("metadata_refresh_limit_per_run", 30, METADATA_REFRESH_LIMIT, 30),
            ("metadata_refresh_limit_per_run", 1, METADATA_REFRESH_LIMIT, 1),
            ("metadata_refresh_limit_per_run", 500, METADATA_REFRESH_LIMIT, 500),
            # Hours are normalised before they are stored.
            ("metadata_refresh_schedule_hours", " 16, 04 ,4", METADATA_REFRESH_HOURS, "4,16"),
            ("metadata_refresh_schedule_hours", "4", METADATA_REFRESH_HOURS, "4"),
        ],
    )
    def test_each_field_is_written_to_its_own_key(
        self, field: str, value: object, key: str, stored: object
    ) -> None:
        status, calls, _ = self._patch({field: value})
        assert (status, calls) == (200, [(key, stored)])

    def test_response_reports_the_effective_hours_not_a_hand_edited_bad_value(self) -> None:
        row = MagicMock()
        row.key = METADATA_REFRESH_HOURS
        row.value = "99,nonsense"
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        app.dependency_overrides[get_session] = _session_override(result)
        try:
            body = TestClient(app).get("/api/settings").json()
        finally:
            app.dependency_overrides.clear()
        assert (
            body["metadata_refresh_schedule_hours"] == settings.show_metadata_refresh_schedule_hours
        )

    def test_stored_hours_are_reflected_in_the_response(self) -> None:
        row = MagicMock()
        row.key = METADATA_REFRESH_HOURS
        row.value = "6, 18"
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        app.dependency_overrides[get_session] = _session_override(result)
        try:
            body = TestClient(app).get("/api/settings").json()
        finally:
            app.dependency_overrides.clear()
        assert body["metadata_refresh_schedule_hours"] == "6,18"

    @pytest.mark.parametrize("bad", ["", "   ", "25", "a", "4;16", "-1"])
    def test_invalid_hours_are_rejected_without_writes(self, bad: str) -> None:
        status, calls, session = self._patch({"metadata_refresh_schedule_hours": bad})
        assert status == 422
        assert calls == []
        session.flush.assert_not_awaited()

    @pytest.mark.parametrize("bad", [0, -1, 501, "many"])
    def test_out_of_range_limit_is_rejected_without_writes(self, bad: object) -> None:
        status, calls, session = self._patch({"metadata_refresh_limit_per_run": bad})
        assert status == 422
        assert calls == []
        session.flush.assert_not_awaited()


def test_patch_field_map_covers_every_field() -> None:
    """Every AppSettingsPatch field maps to a settings key (none can be silently dropped)."""
    from jidou.api.routes.settings import _PATCH_FIELD_TO_KEY
    from jidou.schemas.settings_schema import AppSettingsPatch

    assert set(AppSettingsPatch.model_fields)
    assert set(_PATCH_FIELD_TO_KEY) == set(AppSettingsPatch.model_fields)
    assert len(set(_PATCH_FIELD_TO_KEY.values())) == len(_PATCH_FIELD_TO_KEY)
