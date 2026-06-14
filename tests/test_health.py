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
