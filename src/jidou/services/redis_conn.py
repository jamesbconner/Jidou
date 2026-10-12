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


@asynccontextmanager
async def redis_try_lock(url: str, key: str, ttl_seconds: int) -> AsyncIterator[bool]:
    """Try to take a best-effort Redis lock for one unit of work.

    Issues ``SET key "1" NX EX ttl_seconds``. The lock is only released (``DEL``)
    when this caller acquired it, so a run that lost the race never deletes the
    winner's lock. The TTL bounds how long a crashed holder can wedge the lock.
    Errors from Redis (including it being down) propagate to the caller, and the
    client is always closed.

    Args:
        url: Redis connection URL.
        key: Lock key.
        ttl_seconds: Expiry applied to the lock when acquired.

    Yields:
        True when the lock was acquired, False when another holder has it.
    """
    async with redis_session(url) as client:
        acquired = bool(await client.set(key, "1", nx=True, ex=ttl_seconds))
        try:
            yield acquired
        finally:
            # Only the holder may release; a loser deleting would free the winner's lock.
            if acquired:
                await client.delete(key)
