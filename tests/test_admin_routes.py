"""Tests for the /admin API routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.main import app


def _session_override_with_counts(counts: list[int]) -> "type[AsyncMock]":
    """Return a session override that returns a sequence of scalar counts."""

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        results = []
        for count in counts:
            r = MagicMock()
            r.scalar_one.return_value = count
            results.append(r)
        session.execute = AsyncMock(side_effect=results)
        yield session

    return _mock_session  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /api/admin/stats
# ---------------------------------------------------------------------------


def test_get_stats_returns_table_counts() -> None:
    """GET /api/admin/stats returns a dict of table row counts."""
    from jidou.database import get_session

    # 5 tables queried in order: shows, episodes, downloaded_files, watchlist, background_tasks
    app.dependency_overrides[get_session] = _session_override_with_counts([3, 12, 7, 2, 5])
    try:
        response = TestClient(app).get("/api/admin/stats")
        assert response.status_code == 200
        body = response.json()
        assert body["shows"] == 3
        assert body["episodes"] == 12
        assert body["downloaded_files"] == 7
        assert body["watchlist"] == 2
        assert body["background_tasks"] == 5
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/admin/cache/flush
# ---------------------------------------------------------------------------


def test_flush_cache_returns_ok_and_count() -> None:
    """POST /api/admin/cache/flush clears the in-memory cache."""
    response = TestClient(app).post("/api/admin/cache/flush")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert isinstance(body["cleared"], int)


@pytest.mark.asyncio
async def test_flush_cache_cleared_count_matches_populated_cache() -> None:
    """Flushing a cache with N items reports cleared=N."""
    from jidou.services.cache import cache

    # Populate the cache with 2 known entries
    await cache.set("k1", "v1")
    await cache.set("k2", "v2")

    response = TestClient(app).post("/api/admin/cache/flush")
    body = response.json()
    assert body["ok"] is True
    # After flush the cache should be empty
    assert await cache.get("k1") is None


# ---------------------------------------------------------------------------
# GET /api/admin/health
# ---------------------------------------------------------------------------


def test_health_returns_healthy_true_when_all_pass() -> None:
    """GET /api/admin/health reports healthy=True when DB and Redis pass."""
    from jidou.database import get_session

    async def _ok_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one.return_value = 1
        session.execute = AsyncMock(return_value=result)
        yield session

    mock_r = AsyncMock()
    mock_r.ping = AsyncMock()
    mock_r.aclose = AsyncMock()

    app.dependency_overrides[get_session] = _ok_session
    try:
        with (
            patch("jidou.api.routes.admin.settings") as mock_settings,
            patch("redis.asyncio.from_url", return_value=mock_r),
        ):
            mock_settings.redis_url = "redis://localhost:6379/0"
            mock_settings.tmdb_api_key = "set"
            response = TestClient(app).get("/api/admin/health")
        assert response.status_code == 200
        body = response.json()
        assert "healthy" in body
        assert "services" in body
    finally:
        app.dependency_overrides.clear()


def test_health_returns_healthy_false_when_db_fails() -> None:
    """GET /api/admin/health reports healthy=False when DB is unreachable."""
    from jidou.database import get_session

    async def _failing_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=ConnectionRefusedError("db down"))
        yield session

    app.dependency_overrides[get_session] = _failing_session
    try:
        with patch("jidou.api.routes.admin.settings") as mock_settings:
            mock_settings.redis_url = ""
            mock_settings.tmdb_api_key = None
            response = TestClient(app).get("/api/admin/health")
        assert response.status_code == 200
        body = response.json()
        assert body["healthy"] is False
        assert body["services"]["database"]["ok"] is False
    finally:
        app.dependency_overrides.clear()
