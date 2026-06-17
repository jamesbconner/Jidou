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
        # Lazy Redis client — created on first use
        self._redis: Any = None

    def _get_redis(self) -> Any:
        """Return (and lazily create) the Redis async client."""
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[None]:
        """Acquire permission to make one API call.

        Serialises callers via the asyncio lock so that only one caller can
        wait on the slot at a time.  The lock is held for the duration of the
        caller's critical section to prevent bursts.

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
                if self._redis_url is None:
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

        Uses SET … NX PX to atomically acquire the slot.  If the slot is
        taken, reads the remaining TTL and sleeps until it expires.
        """
        r = self._get_redis()
        window_ms = int(self._window * 1000)
        while True:
            ok = await r.set(self._redis_key, "1", px=window_ms, nx=True)
            if ok:
                return
            pttl: int = await r.pttl(self._redis_key)
            if pttl < 0:
                # Key vanished between SET and PTTL — retry immediately.
                continue
            wait_s = pttl / 1000.0
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
    redis_url=settings.redis_url,
    key="tmdb",
)
