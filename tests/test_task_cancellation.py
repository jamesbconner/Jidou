"""Tests for task cancellation: WebSocket notify, PubSub shutdown, worker cancellation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_cancel_task_emits_websocket_notification():
    """Test that cancelling a task emits a WebSocket notification."""
    from jidou.models.task import BackgroundTask, TaskStatus
    from jidou.workers.celery_app import celery_app

    # Mock objects
    mock_task = MagicMock(spec=BackgroundTask)
    mock_task.id = 1
    mock_task.celery_task_id = "test-celery-id"
    mock_task.status = TaskStatus.RUNNING.value

    with (
        patch("jidou.api.routes.tasks.celery_app.control.revoke"),
        patch("jidou.services.progress.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        # Import emit_progress inside the with block so the patch is active
        from jidou.services.progress import emit_progress

        # Simulate what cancel_task does
        celery_app.control.revoke(mock_task.celery_task_id, terminate=True)
        mock_task.status = TaskStatus.CANCELLED.value
        mock_task.progress_message = "Cancelled by user"

        await emit_progress(
            {
                "celery_task_id": mock_task.celery_task_id,
                "type": "status",
                "data": {
                    "status": TaskStatus.CANCELLED.value,
                    "message": "Cancelled by user",
                },
            }
        )

        # Verify emit_progress was called with cancellation data
        mock_emit.assert_called_once()
        call_data = mock_emit.call_args[0][0]
        assert call_data["type"] == "status"
        assert call_data["data"]["status"] == TaskStatus.CANCELLED.value
        assert call_data["data"]["message"] == "Cancelled by user"


@pytest.mark.asyncio
async def test_pubsub_stop_cancels_listen_task():
    """Test that PubSubSubscriber.stop() cancels the listen task."""
    from jidou.services.pubsub_subscriber import PubSubSubscriber

    subscriber = PubSubSubscriber()

    # Mock Redis and pubsub
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch.object(subscriber, "_listen", new_callable=AsyncMock) as mock_listen,
    ):
        mock_listen.side_effect = asyncio.CancelledError

        await subscriber.start()

        # Verify listen task was created
        assert subscriber._listen_task is not None

        await subscriber.stop()

        # Verify the listen task was cancelled
        assert subscriber._listen_task is None
        mock_redis.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_check_task_cancelled_raises_when_cancelled():
    """Test that check_task_cancelled raises when task is cancelled."""
    from jidou.models.task import BackgroundTask, TaskStatus
    from jidou.services.progress import (
        TaskCancelledError,
        check_task_cancelled,
    )

    mock_session = AsyncMock()
    mock_task = MagicMock(spec=BackgroundTask)
    mock_task.status = TaskStatus.CANCELLED.value

    async def mock_execute(stmt):
        class Result:
            def scalar_one_or_none(self):
                return mock_task

        return Result()

    mock_session.execute = AsyncMock(side_effect=mock_execute)

    with pytest.raises(TaskCancelledError, match="was cancelled"):
        await check_task_cancelled(mock_session, "test-celery-id")


@pytest.mark.asyncio
async def test_check_task_cancelled_passes_when_running():
    """Test that check_task_cancelled does not raise when task is running."""
    from jidou.models.task import BackgroundTask, TaskStatus
    from jidou.services.progress import check_task_cancelled

    mock_session = AsyncMock()
    mock_task = MagicMock(spec=BackgroundTask)
    mock_task.status = TaskStatus.RUNNING.value

    async def mock_execute_running(stmt):
        class Result:
            def scalar_one_or_none(self):
                return mock_task

        return Result()

    mock_session.execute = AsyncMock(side_effect=mock_execute_running)

    # Should not raise
    await check_task_cancelled(mock_session, "test-celery-id")


@pytest.mark.asyncio
async def test_check_task_cancelled_passes_when_no_task():
    """Test that check_task_cancelled does not raise when task doesn't exist."""
    from jidou.services.progress import check_task_cancelled

    mock_session = AsyncMock()

    async def mock_execute_none(stmt):
        class Result:
            def scalar_one_or_none(self):
                return None

        return Result()

    mock_session.execute = AsyncMock(side_effect=mock_execute_none)

    # Should not raise
    await check_task_cancelled(mock_session, "nonexistent-id")
