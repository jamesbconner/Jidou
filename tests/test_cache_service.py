"""Tests for the CacheBackend service."""

import pytest

from jidou.services.cache import CacheBackend


@pytest.mark.asyncio
async def test_cache_stats_empty() -> None:
    """stats() on an empty cache returns zero count and empty entries."""
    cache = CacheBackend(maxsize=100, ttl=60)
    stats = await cache.stats()
    assert stats["count"] == 0
    assert stats["entries"] == []
    assert stats["maxsize"] == 100
    assert stats["ttl_seconds"] == 60


@pytest.mark.asyncio
async def test_cache_stats_with_labelled_entry() -> None:
    """stats() returns the stored entry label and pruned count."""
    cache = CacheBackend(maxsize=100, ttl=60)
    await cache.set("key1", "value1", label="TMDB:999")
    stats = await cache.stats()
    assert stats["count"] == 1
    assert stats["entries"][0]["label"] == "TMDB:999"


@pytest.mark.asyncio
async def test_cache_stats_prunes_evicted_labels() -> None:
    """stats() removes stale keys from _labels that were evicted by TTL/capacity."""
    cache = CacheBackend(maxsize=2, ttl=60)
    await cache.set("key1", "v1", label="L1")
    await cache.set("key2", "v2", label="L2")
    # Force eviction by overflowing the cache (LRU evicts key1 when capacity=2 and key3 added)
    await cache.set("key3", "v3", label="L3")
    stats = await cache.stats()
    # After eviction, entries should only contain live keys
    live_labels = {e["label"] for e in stats["entries"]}
    assert "L1" not in live_labels  # evicted
    assert {"L2", "L3"}.issubset(live_labels)
