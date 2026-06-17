"""Tests for the token-bucket rate limiter."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from jidou.services.rate_limiter import RateLimiter

# ---------------------------------------------------------------------------
# In-memory (local) path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_acquire_yields() -> None:
    """acquire() must yield without error when rate limit is not exceeded."""
    limiter = RateLimiter(rate=100.0)
    async with limiter.acquire():
        pass  # verifies it yields correctly


@pytest.mark.asyncio
async def test_rate_limiter_updates_last_call() -> None:
    """acquire() must record the call timestamp for the in-memory path."""
    limiter = RateLimiter(rate=100.0)
    before = time.monotonic()
    async with limiter.acquire():
        pass
    assert limiter._last_call >= before


@pytest.mark.asyncio
async def test_rate_limiter_enforces_interval() -> None:
    """acquire() must wait when called faster than the configured rate."""
    limiter = RateLimiter(rate=20.0)  # 1 call per 50 ms

    timestamps: list[float] = []
    async with limiter.acquire():
        timestamps.append(time.monotonic())
    async with limiter.acquire():
        timestamps.append(time.monotonic())

    gap = timestamps[1] - timestamps[0]
    assert gap >= 0.04, f"Rate limiter did not enforce interval: {gap:.3f}s"


@pytest.mark.asyncio
async def test_rate_limiter_sequential_calls_complete() -> None:
    """Multiple sequential acquires must all complete without deadlock."""
    limiter = RateLimiter(rate=1000.0)  # very fast — no sleep
    for _ in range(5):
        async with limiter.acquire():
            pass


# ---------------------------------------------------------------------------
# Redis path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_redis_acquires_slot() -> None:
    """Redis path must acquire the slot when SET NX succeeds."""
    limiter = RateLimiter(rate=0.5, redis_url="redis://localhost:6379", key="test")
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        async with limiter.acquire():
            pass

    mock_redis.set.assert_called_once()
    call_kwargs = mock_redis.set.call_args
    assert call_kwargs.kwargs.get("nx") is True


@pytest.mark.asyncio
async def test_rate_limiter_redis_waits_when_slot_occupied() -> None:
    """Redis path must sleep until TTL expires when SET NX fails."""
    limiter = RateLimiter(rate=0.5, redis_url="redis://localhost:6379", key="test")
    mock_redis = AsyncMock()
    # First attempt: slot occupied; second: acquired.
    mock_redis.set = AsyncMock(side_effect=[None, True])
    mock_redis.pttl = AsyncMock(return_value=50)  # 50 ms remaining

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        async with limiter.acquire():
            pass

    mock_sleep.assert_called_once_with(0.05)


@pytest.mark.asyncio
async def test_rate_limiter_redis_retries_on_expired_pttl() -> None:
    """Redis path must retry immediately when PTTL returns -1 (key just expired)."""
    limiter = RateLimiter(rate=0.5, redis_url="redis://localhost:6379", key="test")
    mock_redis = AsyncMock()
    # First SET fails; PTTL returns -1 (expired); second SET succeeds.
    mock_redis.set = AsyncMock(side_effect=[None, True])
    mock_redis.pttl = AsyncMock(return_value=-1)

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        async with limiter.acquire():
            pass

    # No sleep because pttl < 0 → immediate retry.
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_rate_limiter_redis_warning_on_long_wait(caplog: pytest.LogCaptureFixture) -> None:
    """Redis path must log a WARNING when wait exceeds 1 second."""
    import logging

    limiter = RateLimiter(rate=0.5, redis_url="redis://localhost:6379", key="test")
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(side_effect=[None, True])
    mock_redis.pttl = AsyncMock(return_value=1500)  # 1.5 s remaining

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("asyncio.sleep", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING, logger="jidou.services.rate_limiter"),
    ):
        async with limiter.acquire():
            pass

    assert any("high pressure" in record.message for record in caplog.records)
