"""Tests for the /settings API routes."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from jidou.database import get_session
from jidou.main import app


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
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
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
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
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
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
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
                "recent_episodes_enabled": False,
                "recent_movies_enabled": True,
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
                "recent_episodes_enabled": True,
                "recent_movies_enabled": False,
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
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
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
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
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
                "recent_episodes_enabled": False,
                "recent_movies_enabled": True,
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
                "recent_episodes_enabled": True,
                "recent_movies_enabled": False,
            }
            assert session.execute.await_count == 2
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
                "recent_episodes_enabled": True,
                "recent_movies_enabled": True,
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
