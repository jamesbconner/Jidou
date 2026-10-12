"""Shared Redis connection helpers for the services layer.

Cache, rate limiter and progress emission all follow the same lifecycle: open a
short-lived client, use it, always close it. This module owns that lifecycle
(and the pub/sub channel name) so each caller does not repeat the
``try/finally aclose`` boilerplate.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

import redis.asyncio as aioredis

# Channel on which Celery workers publish task progress and the API's
# subscriber listens; both sides must agree on this single name.
TASK_PROGRESS_CHANNEL: Final = "task_progress"


@asynccontextmanager
async def redis_session(
    url: str, *, decode_responses: bool = False
) -> AsyncIterator[aioredis.Redis]:
    """Open a Redis client for one unit of work and always close it.

    A new client is created on every call rather than cached, so it is bound to
    the running event loop. Celery workers use ``asyncio.run()`` per task, and a
    cached client stays bound to the previous loop, raising ``RuntimeError`` on
    any subsequent task.

    ``aioredis.from_url`` is resolved at call time (not import time) so tests
    that patch ``redis.asyncio.from_url`` keep working.

    Args:
        url: Redis connection URL.
        decode_responses: Whether the client returns ``str`` instead of ``bytes``.

    Yields:
        The open Redis client.
    """
    client = aioredis.from_url(url, decode_responses=decode_responses)
    try:
        yield client
    finally:
        await client.aclose()
