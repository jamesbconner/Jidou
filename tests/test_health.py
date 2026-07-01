"""Tests for health check endpoint."""

from fastapi.testclient import TestClient

from jidou.main import app


def test_health_endpoint_structure() -> None:
    """Test that health endpoint returns expected structure."""
    with TestClient(app) as client:
        response = client.get("/api/health")

    # Response should be JSON
    assert response.headers["content-type"].startswith("application/json")

    # Body should have expected keys
    body = response.json()
    assert "status" in body
    assert "timestamp" in body
    assert "services" in body

    # Services dict should exist
    services = body["services"]
    assert "postgres" in services
    assert "redis" in services
    assert "tmdb" in services


def test_health_check_status_values() -> None:
    """Test that health status is one of the expected values."""
    with TestClient(app) as client:
        response = client.get("/api/health")

    body = response.json()
    assert body["status"] in {"healthy", "degraded"}


def test_health_redis_ping_failure_marks_degraded() -> None:
    """Redis ping failure is caught and reported as degraded."""
    from unittest.mock import AsyncMock, patch

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis unreachable"))
    mock_redis.aclose = AsyncMock()

    with patch("redis.asyncio.from_url", return_value=mock_redis), TestClient(app) as client:
        response = client.get("/api/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["redis"]["status"] == "unhealthy"


def test_health_redis_client_creation_failure_marks_degraded() -> None:
    """Redis client creation failure is caught and reported as degraded."""
    from unittest.mock import patch

    with (
        patch("redis.asyncio.from_url", side_effect=OSError("Cannot connect")),
        TestClient(app) as client,
    ):
        response = client.get("/api/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["redis"]["status"] == "unhealthy"
