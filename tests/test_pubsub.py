"""Tests for PubSubSubscriber service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.pubsub_subscriber import PubSubSubscriber


@pytest.mark.asyncio
async def test_stop_before_start_is_safe() -> None:
    """stop() must not raise when called before start() — nothing to clean up."""
    subscriber = PubSubSubscriber()
    await subscriber.stop()  # _listen_task, _pubsub, _redis are all None


@pytest.mark.asyncio
async def test_listen_processes_valid_message() -> None:
    """_listen must broadcast valid JSON messages to WebSocket clients."""
    subscriber = PubSubSubscriber()

    import json

    message = {
        "type": "message",
        "data": json.dumps({"celery_task_id": "task-abc", "type": "progress"}),
    }

    # Sequence: one real message, then stop
    call_count = 0

    async def fake_get_message(**_kwargs: object) -> dict[str, object] | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return message
        subscriber._running = False
        return None

    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = AsyncMock(side_effect=fake_get_message)
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("jidou.services.pubsub_subscriber.manager") as mock_manager,
    ):
        mock_manager.broadcast_to_task = AsyncMock()
        await subscriber.start()
        # Allow the background task to process the message before stopping.
        await asyncio.sleep(0.05)
        await subscriber.stop()

    mock_manager.broadcast_to_task.assert_called_once_with(
        "task-abc",
        {"celery_task_id": "task-abc", "type": "progress"},
    )


@pytest.mark.asyncio
async def test_listen_skips_invalid_json() -> None:
    """_listen must not raise on malformed JSON — log and continue."""
    subscriber = PubSubSubscriber()

    bad_message = {"type": "message", "data": "not valid json{{{"}

    call_count = 0

    async def fake_get_message(**_kwargs: object) -> dict[str, object] | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return bad_message
        subscriber._running = False
        return None

    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = AsyncMock(side_effect=fake_get_message)
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        await subscriber.start()
        await asyncio.sleep(0.05)
        await subscriber.stop()
    # No exception means the subscriber swallowed the JSON error correctly.
