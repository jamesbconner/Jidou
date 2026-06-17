"""WebSocket endpoint for real-time task progress."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

# In-memory connection registry keyed by celery_task_id
# In production, use Redis PubSub with fan-out instead of in-memory.
connections: dict[str, list[WebSocket]] = {}


# Type alias for progress messages
ProgressMessage = dict[str, object]


class ConnectionManager:
    """Manage WebSocket connections for task progress streams."""

    async def connect(self, celery_task_id: str, ws: WebSocket) -> None:
        """Accept a connection and register it for the given task."""
        await ws.accept()
        connections.setdefault(celery_task_id, []).append(ws)
        logger.info("WebSocket connected for task %s", celery_task_id)

    async def disconnect(self, celery_task_id: str, ws: WebSocket) -> None:
        """Remove a WebSocket connection for a task."""
        task_conns = connections.get(celery_task_id, [])
        if ws in task_conns:
            task_conns.remove(ws)
        if not task_conns:
            connections.pop(celery_task_id, None)
        logger.info("WebSocket disconnected for task %s", celery_task_id)

    async def broadcast_to_task(self, celery_task_id: str, message: ProgressMessage) -> None:
        """Send a JSON message to all WS clients watching a task."""
        # Snapshot the list so concurrent disconnect() calls cannot shift
        # indices mid-iteration and cause skipped clients.
        task_conns = list(connections.get(celery_task_id, []))
        payload = json.dumps(message)
        disconnected: list[WebSocket] = []

        for ws in task_conns:
            try:
                await ws.send_text(payload)
            except (RuntimeError, OSError):
                disconnected.append(ws)

        for ws in disconnected:
            await self.disconnect(celery_task_id, ws)

        if disconnected:
            logger.info(
                "Pruned %s stale WS connection(s) for task %s",
                len(disconnected),
                celery_task_id,
            )


manager = ConnectionManager()


@router.websocket("/task-progress/{celery_task_id}")
async def task_progress_websocket(
    websocket: WebSocket,
    celery_task_id: str,
) -> None:
    """WebSocket endpoint for real-time task progress.

    Clients connect to ``/ws/task-progress/{celery_task_id}`` and receive
    JSON messages as the Celery task advances:

    .. code-block:: json

        {"type": "progress", "data": {"current": 5, "total": 20, "message": "Scanning..."}}
        {"type": "file_update", "data": {"filename": "S01E01.mp4", "action": "matched"}}
        {"type": "complete", "data": {"summary": {...}}}
        {"type": "error", "data": {"error": "Connection refused"}}
    """
    await manager.connect(celery_task_id, websocket)
    try:
        while True:
            # Keep the connection alive; we don't expect client messages here.
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(celery_task_id, websocket)
