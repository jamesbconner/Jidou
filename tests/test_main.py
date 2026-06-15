"""Tests for FastAPI app and main entry point."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from jidou.main import app

HEALTH_MODULE = sys.modules["jidou.api.health"]


def test_main_runs() -> None:
    """Test that the app starts and responds to healthy requests.

    Mocks DB and Redis health checks so the endpoint returns 200 in CI
    where no live dependencies are available.
    """
    # Mock the DB engine execute to simulate a healthy postgres
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    # Mock redis ping to simulate healthy redis
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.close = AsyncMock()

    # Patch the health module's references (engine is read-only on AsyncEngine)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)

    with (
        patch.object(HEALTH_MODULE, "engine", mock_engine),
        patch.object(
            HEALTH_MODULE,
            "aioredis",
            MagicMock(from_url=MagicMock(return_value=mock_redis)),
        ),
        TestClient(app) as client,
    ):
        response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "services" in data


def test_health_degraded_returns_503() -> None:
    """Test that degraded dependencies return HTTP 503."""
    # Force DB check to fail by raising an exception
    failing_conn = MagicMock()
    failing_conn.execute = AsyncMock(side_effect=Exception("connection refused"))
    failing_conn.__aenter__ = AsyncMock(return_value=failing_conn)
    failing_conn.__aexit__ = AsyncMock(return_value=False)

    failing_engine = MagicMock()
    failing_engine.connect = MagicMock(return_value=failing_conn)

    with (
        patch.object(HEALTH_MODULE, "engine", failing_engine),
        TestClient(app) as client,
    ):
        response = client.get("/api/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
