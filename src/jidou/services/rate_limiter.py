"""Rate limiter for external API calls."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from jidou.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter for external API calls.

    Enforces a maximum of `rate` calls per second globally across
    all API clients to avoid hitting rate limits.
    """

    def __init__(self, rate: float = 0.5) -> None:
        """Initialize the rate limiter.

        Args:
            rate: Maximum calls per second. Default 0.5 (1 call per 2s).
        """
        self._interval = 1.0 / rate
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[None]:
        """Acquire permission to make an API call.

        Holds the lock for the duration of the caller's request so that
        concurrent calls cannot start while a previous request is still
        in flight.

        Yields:
            None after ensuring the rate limit is respected.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._interval:
                wait_time = self._interval - elapsed
                logger.debug("Rate limiter: waiting %.2fs", wait_time)
                await asyncio.sleep(wait_time)
            try:
                yield
            finally:
                # Update after the request completes so the interval is
                # measured from when the previous request finished, not
                # when it started.
                self._last_call = time.monotonic()


# Module-level rate limiter instance
rate_limiter = RateLimiter(rate=settings.tmdb_rate_limit_per_second)
