"""Tests for the shared Redis session helper."""

from unittest.mock import AsyncMock, patch

import pytest

from jidou.services.redis_conn import TASK_PROGRESS_CHANNEL, redis_session


def test_task_progress_channel_name_is_stable() -> None:
    """The channel name is part of the worker/API wire contract."""
    assert TASK_PROGRESS_CHANNEL == "task_progress"


@pytest.mark.asyncio
async def test_redis_session_yields_client_and_closes() -> None:
    """The client is yielded, then closed once on normal exit."""
    client = AsyncMock()
    with patch("redis.asyncio.from_url", return_value=client) as from_url:
        async with redis_session("redis://x/0") as r:
            assert r is client
            client.aclose.assert_not_awaited()
    from_url.assert_called_once_with("redis://x/0", decode_responses=False)
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_session_passes_decode_responses() -> None:
    """decode_responses is forwarded to from_url."""
    with patch("redis.asyncio.from_url", return_value=AsyncMock()) as from_url:
        async with redis_session("redis://x/0", decode_responses=True):
            pass
    from_url.assert_called_once_with("redis://x/0", decode_responses=True)


@pytest.mark.asyncio
async def test_redis_session_closes_on_exception() -> None:
    """An exception inside the block still closes the client and propagates."""
    client = AsyncMock()
    with (
        patch("redis.asyncio.from_url", return_value=client),
        pytest.raises(RuntimeError, match="boom"),
    ):
        async with redis_session("redis://x/0"):
            raise RuntimeError("boom")
    client.aclose.assert_awaited_once()
