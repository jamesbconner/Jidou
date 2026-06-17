"""Tests for WebSocket task progress endpoint and ConnectionManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from jidou.main import app


def test_websocket_connection() -> None:
    """Verify that a WebSocket connection is accepted."""
    client = TestClient(app)
    with client.websocket_connect("/ws/task-progress/test-task-id") as ws:
        assert ws is not None


def test_websocket_invalid_task_id() -> None:
    """Verify that WebSocket accepts any task ID (even nonexistent)."""
    client = TestClient(app)
    with client.websocket_connect("/ws/task-progress/nonexistent-task-id") as ws:
        assert ws is not None


# ---------------------------------------------------------------------------
# ConnectionManager unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_clients() -> None:
    """broadcast_to_task must send the message to every registered WebSocket."""
    from jidou.api.websocket.task_progress import ConnectionManager, connections

    manager = ConnectionManager()

    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws2 = AsyncMock()
    ws2.accept = AsyncMock()

    connections.clear()
    await manager.connect("task-1", ws1)
    await manager.connect("task-1", ws2)

    await manager.broadcast_to_task("task-1", {"type": "progress"})

    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()

    connections.clear()


@pytest.mark.asyncio
async def test_broadcast_prunes_stale_runtime_error() -> None:
    """A WebSocket that raises RuntimeError during send must be pruned."""
    from jidou.api.websocket.task_progress import ConnectionManager, connections

    manager = ConnectionManager()

    dead_ws = AsyncMock()
    dead_ws.accept = AsyncMock()
    dead_ws.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))

    live_ws = AsyncMock()
    live_ws.accept = AsyncMock()

    connections.clear()
    await manager.connect("task-2", dead_ws)
    await manager.connect("task-2", live_ws)

    await manager.broadcast_to_task("task-2", {"type": "progress"})

    # live_ws still receives the message
    live_ws.send_text.assert_called_once()
    # dead_ws removed from registry
    assert dead_ws not in connections.get("task-2", [])

    connections.clear()


@pytest.mark.asyncio
async def test_broadcast_copy_safe_from_concurrent_mutation() -> None:
    """Concurrent disconnect during broadcast must not skip clients."""
    from jidou.api.websocket.task_progress import ConnectionManager, connections

    manager = ConnectionManager()
    sent_to: list[object] = []

    async def send_and_disconnect(payload: str) -> None:
        sent_to.append("ws1")
        # Simulate concurrent disconnect of ws1 happening after ws1.send_text
        await manager.disconnect("task-3", ws1)

    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws1.send_text = AsyncMock(side_effect=send_and_disconnect)

    ws2 = AsyncMock()
    ws2.accept = AsyncMock()
    ws2.send_text = AsyncMock(side_effect=lambda p: sent_to.append("ws2"))

    connections.clear()
    await manager.connect("task-3", ws1)
    await manager.connect("task-3", ws2)

    await manager.broadcast_to_task("task-3", {"type": "progress"})

    # Both clients must have been sent to even though ws1 disconnected mid-loop
    assert "ws1" in sent_to
    assert "ws2" in sent_to

    connections.clear()


@pytest.mark.asyncio
async def test_disconnect_nonexistent_ws_is_safe() -> None:
    """disconnect() must not raise when the WebSocket is not in the registry."""
    from jidou.api.websocket.task_progress import ConnectionManager, connections

    manager = ConnectionManager()
    ws = AsyncMock()
    ws.accept = AsyncMock()

    connections.clear()
    # Disconnect a ws that was never connected — must not raise.
    await manager.disconnect("no-such-task", ws)
    connections.clear()


@pytest.mark.asyncio
async def test_disconnect_always_called_on_non_disconnect_exception() -> None:
    """The WebSocket handler must clean up on exceptions other than WebSocketDisconnect."""
    from fastapi import WebSocket

    from jidou.api.websocket.task_progress import connections, task_progress_websocket

    manager_mock = MagicMock()
    manager_mock.connect = AsyncMock()
    manager_mock.disconnect = AsyncMock()

    ws = AsyncMock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=RuntimeError("unexpected"))

    connections.clear()

    with (
        pytest.raises(RuntimeError),
        pytest.MonkeyPatch.context() as mp,
    ):
        import jidou.api.websocket.task_progress as ws_module

        mp.setattr(ws_module, "manager", manager_mock)
        await task_progress_websocket(ws, "task-err")

    manager_mock.disconnect.assert_called_once_with("task-err", ws)
    connections.clear()
