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


@pytest.mark.asyncio
async def test_listen_returns_when_not_initialized() -> None:
    """_listen returns immediately and logs error when redis/pubsub is None."""
    subscriber = PubSubSubscriber()
    subscriber._running = True  # ensure outer loop is entered
    # _redis and _pubsub remain None — should log and return without blocking
    await subscriber._listen()


@pytest.mark.asyncio
async def test_listen_skips_non_message_type() -> None:
    """_listen continues without broadcasting for subscribe-type messages."""
    subscriber = PubSubSubscriber()

    call_count = 0

    async def fake_get_message(**_kwargs: object) -> dict[str, object] | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"type": "subscribe", "data": None}
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
        await asyncio.sleep(0.05)
        await subscriber.stop()

    mock_manager.broadcast_to_task.assert_not_called()


@pytest.mark.asyncio
async def test_listen_skips_message_missing_task_id() -> None:
    """_listen logs a warning and continues when celery_task_id is absent."""
    import json

    subscriber = PubSubSubscriber()

    call_count = 0

    async def fake_get_message(**_kwargs: object) -> dict[str, object] | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"type": "message", "data": json.dumps({"status": "no_task_id_here"})}
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
        await asyncio.sleep(0.05)
        await subscriber.stop()

    mock_manager.broadcast_to_task.assert_not_called()


@pytest.mark.asyncio
async def test_listen_cancelled_error_is_reraised() -> None:
    """asyncio.CancelledError propagates out of _listen so the task is cleaned up."""
    subscriber = PubSubSubscriber()

    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = AsyncMock(side_effect=asyncio.CancelledError())
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        subscriber._redis = mock_redis
        subscriber._pubsub = mock_pubsub
        subscriber._running = True
        with pytest.raises(asyncio.CancelledError):
            await subscriber._listen()


@pytest.mark.asyncio
async def test_listen_exception_triggers_resubscribe_and_continues() -> None:
    """Generic exception in _listen logs, sleeps, and re-subscribes on failure."""
    subscriber = PubSubSubscriber()

    call_count = 0

    async def fake_get_message(**_kwargs: object) -> dict[str, object] | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("Redis dropped")
        subscriber._running = False
        return None

    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = AsyncMock(side_effect=fake_get_message)
    # Re-subscribe also fails to cover lines 102-103
    mock_pubsub.subscribe = AsyncMock(side_effect=OSError("Re-subscribe failed"))
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    # Inject state directly; call _listen() as a coroutine to avoid timing issues
    subscriber._redis = mock_redis
    subscriber._pubsub = mock_pubsub
    subscriber._running = True

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("jidou.services.pubsub_subscriber.manager") as mock_manager,
    ):
        mock_manager.broadcast_to_task = AsyncMock()
        await subscriber._listen()
