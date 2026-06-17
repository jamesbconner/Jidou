"""Rate limiter for external API calls.

Provides a token-bucket rate limiter with an optional Redis backend so limits
are enforced across all Celery workers and the API process simultaneously.
Falls back to an in-process asyncio.Lock when no Redis URL is supplied
(useful for tests and single-process deployments).
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from jidou.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket rate limiter for external API calls.

    When *redis_url* is provided the slot is acquired via a Redis key with a
    millisecond TTL, ensuring all processes share the same window.  Without a
    Redis URL the limiter falls back to an asyncio.Lock (in-process only).

    Args:
        rate: Maximum calls per second (default 0.5 = 1 call per 2 s).
        redis_url: Optional Redis URL for cross-process enforcement.
        key: Logical name for this limiter; used as the Redis key suffix.
    """

    def __init__(
        self,
        rate: float = 0.5,
        redis_url: str | None = None,
        key: str = "default",
    ) -> None:
        self._window = 1.0 / rate
        self._redis_url = redis_url
        self._redis_key = f"rate_limit:{key}"
        # In-memory fallback state (also used when redis_url is None)
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    def _get_redis(self) -> Any:
        """Create a Redis async client bound to the current event loop.

        A new client is created on every call rather than caching one, so the
        client is always bound to the running event loop.  This is required for
        Celery workers that use ``asyncio.run()`` per task — a cached client
        stays bound to the previous loop and raises ``RuntimeError`` on any
        subsequent task in the same worker process.
        """
        import redis.asyncio as aioredis

        return aioredis.from_url(self._redis_url)

    # Extra headroom so the Redis key outlives any in-flight HTTP request.
    # TMDB calls have a 10s timeout; 15s gives a safe margin.
    _HOLD_BUFFER_MS: int = 15_000

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[None]:
        """Acquire permission to make one API call.

        Serialises callers via the asyncio lock so that only one caller can
        wait on the slot at a time.  The lock is held for the duration of the
        caller's critical section to prevent bursts.

        For Redis mode the key TTL is set to ``window + _HOLD_BUFFER_MS`` so
        it cannot expire while the request is still in flight.  After the
        request completes the key is reset to ``window_ms`` so the next caller
        waits the correct minimum gap from *call completion* (not call start).

        Yields:
            None after the rate-limit window has been respected.
        """
        async with self._lock:
            if self._redis_url is not None:
                await self._wait_redis()
            else:
                await self._wait_local()
            try:
                yield
            finally:
                if self._redis_url is not None:
                    # Reset TTL to just the window gap measured from now so
                    # the next caller waits the correct inter-call interval.
                    r = self._get_redis()
                    await r.set(self._redis_key, "1", px=int(self._window * 1000))
                else:
                    self._last_call = time.monotonic()

    async def _wait_local(self) -> None:
        """Enforce rate limit using monotonic clock (in-process only)."""
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._window:
            wait_time = self._window - elapsed
            logger.debug("Rate limiter [local]: waiting %.3fs", wait_time)
            await asyncio.sleep(wait_time)

    async def _wait_redis(self) -> None:
        """Enforce rate limit via a Redis key with millisecond TTL.

        Uses SET … NX PX to atomically acquire the slot.  The key TTL is
        ``window_ms + _HOLD_BUFFER_MS`` so it survives the full HTTP request.
        After the request completes :meth:`acquire` resets the key to
        ``window_ms`` so subsequent callers observe the correct gap.

        Waiters sleep at most ``window_ms`` per iteration so they wake up
        promptly after the owner resets the TTL on completion.
        """
        r = self._get_redis()
        window_ms = int(self._window * 1000)
        hold_ms = window_ms + self._HOLD_BUFFER_MS
        while True:
            ok = await r.set(self._redis_key, "1", px=hold_ms, nx=True)
            if ok:
                return
            pttl: int = await r.pttl(self._redis_key)
            if pttl < 0:
                # Key vanished between SET and PTTL — retry immediately.
                continue
            # Cap sleep to window_ms: the owner resets the key to window_ms on
            # completion, so we don't need to sleep the full hold_ms.
            wait_s = min(pttl, window_ms) / 1000.0
            if wait_s > 1.0:
                logger.warning(
                    "Rate limiter [redis] high pressure on %s — waiting %.2fs",
                    self._redis_key,
                    wait_s,
                )
            else:
                logger.debug(
                    "Rate limiter [redis]: slot occupied on %s, waiting %.3fs",
                    self._redis_key,
                    wait_s,
                )
            await asyncio.sleep(wait_s)


# Module-level singleton shared by all TMDB callers in this process.
# Workers have their own copy that coordinates with peers via Redis.
rate_limiter = RateLimiter(
    rate=settings.tmdb_rate_limit_per_second,
    # Use `or None` so an empty REDIS_URL env var falls back to in-memory mode.
    # settings.redis_url always has a non-empty default, so without this guard
    # the in-memory path would never be reachable.
    redis_url=settings.redis_url or None,
    key="tmdb",
)
