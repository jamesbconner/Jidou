"""Cache abstraction for TMDB API responses."""

import asyncio
import hashlib
import logging
from typing import Any

from cachetools import TTLCache

from jidou.config import settings

logger = logging.getLogger(__name__)


class CacheBackend:
    """In-memory TTL cache for development. Swap for Redis in production."""

    def __init__(self, maxsize: int = 1000, ttl: int = 86400) -> None:
        """Initialize the cache backend.

        Args:
            maxsize: Maximum number of entries in the cache.
            ttl: Time-to-live in seconds for each entry.
        """
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = asyncio.Lock()
        self._labels: dict[str, str] = {}

    async def get(self, key: str) -> Any | None:
        """Retrieve a value from the cache.

        Args:
            key: The cache key.

        Returns:
            The cached value, or None if not found.
        """
        async with self._lock:
            return self._cache.get(key)

    async def set(self, key: str, value: Any) -> None:
        """Store a value in the cache.

        Args:
            key: The cache key.
            value: The value to cache.
        """
        async with self._lock:
            self._cache[key] = value

    def register(self, key: str, label: str) -> None:
        """Associate a human-readable label with a cache key.

        Args:
            key: The cache key (SHA-256 hash).
            label: A descriptive label, e.g. the TMDB endpoint path.
        """
        self._labels[key] = label

    async def stats(self) -> dict[str, Any]:
        """Return cache statistics and active entry list for admin introspection.

        Returns:
            Dictionary with count, capacity, TTL, and labelled entry list.
        """
        async with self._lock:
            active_keys = set(self._cache.keys())
            entries = [
                {"label": self._labels[key], "key": key}
                for key in active_keys
                if key in self._labels
            ]
        return {
            "count": len(active_keys),
            "maxsize": self._cache.maxsize,
            "ttl_seconds": self._cache.ttl,
            "entries": sorted(entries, key=lambda e: e["label"]),
        }

    @staticmethod
    def make_key(url: str) -> str:
        """Generate a cache key from a URL.

        Args:
            url: The API URL to cache.

        Returns:
            A deterministic cache key string.
        """
        return hashlib.sha256(url.encode()).hexdigest()


# Module-level cache instance
cache = CacheBackend(ttl=settings.tmdb_cache_ttl)
