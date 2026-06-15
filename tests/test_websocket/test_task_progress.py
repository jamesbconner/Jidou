"""Tests for WebSocket task progress endpoint."""

from fastapi.testclient import TestClient

from jidou.main import app


def test_websocket_connection() -> None:
    """Verify that a WebSocket connection is accepted."""
    client = TestClient(app)
    with client.websocket_connect("/ws/task-progress/test-task-id") as ws:
        # Connection should be established
        assert ws is not None


def test_websocket_invalid_task_id() -> None:
    """Verify that WebSocket accepts any task ID (even nonexistent)."""
    client = TestClient(app)
    with client.websocket_connect("/ws/task-progress/nonexistent-task-id") as ws:
        # Connection should still be established; messages won't be sent
        assert ws is not None
