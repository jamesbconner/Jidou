"""Redis-backed cache for TMDB API responses, shared across all Jidou processes.

A single logical cache instance is used by every process — the FastAPI API
server and every Celery worker — so a response fetched by one process is
immediately visible to all the others. Entries expire via Redis's native TTL;
a sorted set tracks insertion order so the cache can enforce a soft entry-count
cap without needing Redis's own memory-based eviction policy configured.
"""

import hashlib
import json
import logging
import time
from typing import Any

from jidou.config import settings

logger = logging.getLogger(__name__)

_ENTRY_PREFIX = "jidou:tmdb_cache:entry:"
_LABEL_PREFIX = "jidou:tmdb_cache:label:"
_ORDER_ZSET = "jidou:tmdb_cache:order"

# Number of keys fetched per Redis SCAN iteration when enumerating entries.
_SCAN_COUNT = 500


class CacheBackend:
    """Redis-backed TTL cache for TMDB API responses.

    Args:
        redis_url: Redis connection URL. Required — this cache has no
            in-memory fallback since its entire purpose is cross-process
            sharing between the API server and Celery workers.
        maxsize: Soft cap on the number of live entries. When a write pushes
            the count over this limit, the oldest entries (by insertion
            order) are evicted first.
        ttl: Time-to-live in seconds for each entry.
    """

    def __init__(self, redis_url: str, maxsize: int = 25_000, ttl: int = 604_800) -> None:
        self._redis_url = redis_url
        self._maxsize = maxsize
        self._ttl = ttl

    def _get_redis(self) -> Any:
        """Create a Redis async client bound to the current event loop.

        A new client is created on every call rather than caching one, so the
        client is always bound to the running event loop. This mirrors
        :class:`~jidou.services.rate_limiter.RateLimiter` — Celery workers use
        ``asyncio.run()`` per task, and a cached client stays bound to the
        previous loop, raising ``RuntimeError`` on any subsequent task.
        """
        import redis.asyncio as aioredis

        return aioredis.from_url(self._redis_url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        """Retrieve a value from the cache.

        Args:
            key: The cache key.

        Returns:
            The cached value, or None if not found or expired.
        """
        r = self._get_redis()
        try:
            raw = await r.get(_ENTRY_PREFIX + key)
        finally:
            await r.aclose()
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, label: str | None = None) -> None:
        """Store a value in the cache and enforce the entry-count cap.

        Args:
            key: The cache key.
            value: The value to cache (must be JSON-serialisable).
            label: Optional human-readable label (e.g. TMDB endpoint path).
                   Stored with the same TTL as the value.
        """
        r = self._get_redis()
        try:
            payload = json.dumps(value)
            pipe = r.pipeline()
            pipe.set(_ENTRY_PREFIX + key, payload, ex=self._ttl)
            if label is not None:
                pipe.set(_LABEL_PREFIX + key, label, ex=self._ttl)
            pipe.zadd(_ORDER_ZSET, {key: time.time()})
            await pipe.execute()
            await self._enforce_maxsize(r)
        finally:
            await r.aclose()

    async def _enforce_maxsize(self, r: Any) -> None:
        """Evict the oldest entries (by insertion order) if over capacity.

        Args:
            r: An open Redis async client to reuse for eviction commands.
        """
        overflow = await r.zcard(_ORDER_ZSET) - self._maxsize
        if overflow <= 0:
            return
        oldest = await r.zpopmin(_ORDER_ZSET, overflow)
        if not oldest:
            return
        pipe = r.pipeline()
        for member, _score in oldest:
            pipe.delete(_ENTRY_PREFIX + member)
            pipe.delete(_LABEL_PREFIX + member)
        await pipe.execute()

    async def stats(self) -> dict[str, Any]:
        """Return cache statistics and the active, labelled entry list.

        Enumerates live entries via SCAN rather than the order-tracking
        sorted set, so the count always reflects Redis's own TTL expiry
        exactly — no separate pruning step is needed.

        Returns:
            Dictionary with count, capacity, TTL, and labelled entry list.
        """
        r = self._get_redis()
        try:
            entry_keys = await self._scan_keys(r, _ENTRY_PREFIX)
            entries: list[dict[str, str]] = []
            if entry_keys:
                short_keys = [k[len(_ENTRY_PREFIX) :] for k in entry_keys]
                labels = await r.mget([_LABEL_PREFIX + k for k in short_keys])
                entries = [
                    {"label": label, "key": key}
                    for key, label in zip(short_keys, labels, strict=True)
                    if label is not None
                ]
            return {
                "count": len(entry_keys),
                "maxsize": self._maxsize,
                "ttl_seconds": self._ttl,
                "entries": sorted(entries, key=lambda e: e["label"]),
            }
        finally:
            await r.aclose()

    async def flush(self) -> int:
        """Delete every cache entry, label, and the order-tracking sorted set.

        Returns:
            The number of entries removed.
        """
        r = self._get_redis()
        try:
            entry_keys = await self._scan_keys(r, _ENTRY_PREFIX)
            label_keys = await self._scan_keys(r, _LABEL_PREFIX)
            all_keys = entry_keys + label_keys + [_ORDER_ZSET]
            if all_keys:
                await r.delete(*all_keys)
            return len(entry_keys)
        finally:
            await r.aclose()

    @staticmethod
    async def _scan_keys(r: Any, prefix: str) -> list[str]:
        """Enumerate all keys under *prefix* via non-blocking SCAN.

        Args:
            r: An open Redis async client.
            prefix: Key prefix to match (``prefix + "*"``).

        Returns:
            List of matching keys.
        """
        keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = await r.scan(cursor=cursor, match=prefix + "*", count=_SCAN_COUNT)
            keys.extend(batch)
            if cursor == 0:
                break
        return keys

    @staticmethod
    def make_key(url: str) -> str:
        """Generate a cache key from a URL.

        Args:
            url: The API URL to cache.

        Returns:
            A deterministic cache key string.
        """
        return hashlib.sha256(url.encode()).hexdigest()


# Module-level singleton shared by all TMDB callers in this process — and, since
# it is Redis-backed, by every other Jidou process (API server, every Celery
# worker) too.
cache = CacheBackend(
    redis_url=settings.redis_url,
    maxsize=settings.tmdb_cache_maxsize,
    ttl=settings.tmdb_cache_ttl,
)
