"""Tests for FastAPI app and main entry point."""

from fastapi.testclient import TestClient

from jidou.main import app


def test_main_runs() -> None:
    """Test that the app starts and responds to requests."""
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"healthy", "degraded"}
    assert "services" in data
