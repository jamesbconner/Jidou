"""Tests for the POST /shows/{show_id}/rss-stub API route."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from jidou.database import get_session
from jidou.main import app
from jidou.models.rss import RssSubscription
from jidou.models.show import Show


def _make_show(*, id: int = 1, title: str = "Test Show") -> MagicMock:
    s = MagicMock(spec=Show)
    s.id = id
    s.title = title
    return s


def _make_rss_sub(
    *,
    id: int = 1,
    show_id: int = 1,
    name: str = "Test Show",
    active: bool = False,
    enabled_in_config: bool = False,
    remote_key: str | None = None,
) -> MagicMock:
    sub = MagicMock(spec=RssSubscription)
    sub.id = id
    sub.remote_key = remote_key
    sub.feed_id = None
    sub.show_id = show_id
    sub.name = name
    sub.regex_include = None
    sub.regex_exclude = None
    sub.regex_include_ignorecase = True
    sub.regex_exclude_ignorecase = True
    sub.download_location = None
    sub.move_completed = None
    sub.active = active
    sub.enabled_in_config = enabled_in_config
    sub.label = None
    sub.last_match = None
    sub.extra_config = None
    sub.feed = None
    sub.show = None
    sub.created_at = datetime.now(UTC)
    sub.updated_at = datetime.now(UTC)
    return sub


def _session_override(show_lookup_result: MagicMock | None) -> object:
    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = show_lookup_result
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        yield session

    return _mock_session


def test_create_rss_stub_returns_404_for_missing_show() -> None:
    """POST /shows/{id}/rss-stub returns 404 when the show doesn't exist."""
    app.dependency_overrides[get_session] = _session_override(None)
    try:
        response = TestClient(app).post("/api/shows/999/rss-stub")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_create_rss_stub_creates_new_stub_when_none_exists() -> None:
    """POST /shows/{id}/rss-stub creates and returns a fresh inactive stub."""
    show = _make_show(id=1, title="Attack on Titan")
    stub = _make_rss_sub(id=5, show_id=1, name="Attack on Titan", active=False)

    app.dependency_overrides[get_session] = _session_override(show)
    try:
        with patch(
            "jidou.api.routes.shows.ensure_rss_stub", AsyncMock(return_value=stub)
        ) as mock_ensure:
            response = TestClient(app).post("/api/shows/1/rss-stub")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 5
            assert data["show_id"] == 1
            assert data["active"] is False
            mock_ensure.assert_awaited_once()
            assert mock_ensure.await_args.args[1] == 1
            assert mock_ensure.await_args.args[2] == "Attack on Titan"
    finally:
        app.dependency_overrides.clear()


def test_create_rss_stub_returns_existing_linked_subscription() -> None:
    """POST /shows/{id}/rss-stub returns an already-linked subscription unchanged."""
    show = _make_show(id=2, title="Dan Da Dan")
    existing = _make_rss_sub(id=9, show_id=2, name="Dan Da Dan", active=True, remote_key="abc123")

    app.dependency_overrides[get_session] = _session_override(show)
    try:
        with patch("jidou.api.routes.shows.ensure_rss_stub", AsyncMock(return_value=existing)):
            response = TestClient(app).post("/api/shows/2/rss-stub")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 9
            assert data["active"] is True
            assert data["remote_key"] == "abc123"
    finally:
        app.dependency_overrides.clear()
