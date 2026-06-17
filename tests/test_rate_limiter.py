"""Tests for the token-bucket rate limiter."""

import time

import pytest

from jidou.services.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_acquire_yields() -> None:
    """acquire() must yield without error when rate limit is not exceeded."""
    limiter = RateLimiter(rate=100.0)  # 100 calls/sec — no sleep needed
    async with limiter.acquire():
        pass  # Just verifying it yields correctly


@pytest.mark.asyncio
async def test_rate_limiter_updates_last_call() -> None:
    """acquire() must update _last_call after each use."""
    limiter = RateLimiter(rate=100.0)
    before = time.monotonic()
    async with limiter.acquire():
        pass
    assert limiter._last_call >= before


@pytest.mark.asyncio
async def test_rate_limiter_enforces_interval() -> None:
    """acquire() must wait when called faster than the configured rate."""
    limiter = RateLimiter(rate=20.0)  # 1 call per 50ms

    calls: list[float] = []
    async with limiter.acquire():
        calls.append(time.monotonic())
    async with limiter.acquire():
        calls.append(time.monotonic())

    gap = calls[1] - calls[0]
    # Gap must be at least the limiter interval (50ms), with 10ms tolerance.
    assert gap >= 0.04, f"Rate limiter did not enforce interval: {gap:.3f}s"


@pytest.mark.asyncio
async def test_rate_limiter_sequential_calls() -> None:
    """Multiple sequential acquires must all complete without deadlock."""
    limiter = RateLimiter(rate=1000.0)  # very fast — no sleep
    for _ in range(5):
        async with limiter.acquire():
            pass
