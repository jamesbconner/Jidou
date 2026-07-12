"""Tests for the Redis-backed CacheBackend service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.cache import CacheBackend


def _mock_redis() -> AsyncMock:
    """Build a mock Redis client with pipeline() returning a builder-pattern mock.

    Pipeline builder methods (set/zadd/delete) are synchronous — they queue a
    command and return the pipeline for chaining, matching redis.asyncio's real
    API — only execute() is awaited.
    """
    r = AsyncMock()
    pipe = MagicMock()
    pipe.set = MagicMock(return_value=pipe)
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.delete = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    r.pipeline = MagicMock(return_value=pipe)
    r.zcard = AsyncMock(return_value=0)
    r.zpopmin = AsyncMock(return_value=[])
    r.scan = AsyncMock(return_value=(0, []))
    r.mget = AsyncMock(return_value=[])
    return r


@pytest.mark.asyncio
async def test_get_returns_none_on_miss() -> None:
    """get() returns None when the Redis key doesn't exist."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.get = AsyncMock(return_value=None)

    with patch("redis.asyncio.from_url", return_value=r):
        result = await cache.get("missing")

    assert result is None


@pytest.mark.asyncio
async def test_get_deserializes_cached_json() -> None:
    """get() JSON-decodes the raw Redis value on a hit."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.get = AsyncMock(return_value='{"foo": "bar"}')

    with patch("redis.asyncio.from_url", return_value=r):
        result = await cache.get("key1")

    assert result == {"foo": "bar"}
    r.get.assert_called_once_with("jidou:tmdb_cache:entry:key1")


@pytest.mark.asyncio
async def test_get_client_closed_after_call() -> None:
    """The Redis client is closed after get(), success or not."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.get = AsyncMock(return_value=None)

    with patch("redis.asyncio.from_url", return_value=r):
        await cache.get("key1")

    r.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_set_writes_entry_and_label_with_ttl() -> None:
    """set() pipelines a TTL'd SET for the value and label, plus a ZADD."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()

    with patch("redis.asyncio.from_url", return_value=r):
        await cache.set("key1", {"a": 1}, label="TMDB:999")

    pipe = r.pipeline()
    assert pipe.set.call_args_list[0].args[0] == "jidou:tmdb_cache:entry:key1"
    assert pipe.set.call_args_list[0].kwargs["ex"] == 60
    assert pipe.set.call_args_list[1].args[0] == "jidou:tmdb_cache:label:key1"
    assert pipe.set.call_args_list[1].args[1] == "TMDB:999"
    pipe.zadd.assert_called_once()
    assert pipe.zadd.call_args.args[0] == "jidou:tmdb_cache:order"


@pytest.mark.asyncio
async def test_set_ttl_override_applies_to_entry_and_label() -> None:
    """A per-call ttl= overrides the cache's configured default for both
    the entry and label SET calls, so they always expire together."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=604_800)
    r = _mock_redis()

    with patch("redis.asyncio.from_url", return_value=r):
        await cache.set("key1", {"a": 1}, label="TMDB:/trending/tv/day", ttl=3_600)

    pipe = r.pipeline()
    assert pipe.set.call_args_list[0].kwargs["ex"] == 3_600
    assert pipe.set.call_args_list[1].kwargs["ex"] == 3_600


@pytest.mark.asyncio
async def test_set_without_ttl_override_uses_configured_default() -> None:
    """Omitting ttl= falls back to the cache's configured default TTL."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=604_800)
    r = _mock_redis()

    with patch("redis.asyncio.from_url", return_value=r):
        await cache.set("key1", {"a": 1}, label="TMDB:/tv/999")

    pipe = r.pipeline()
    assert pipe.set.call_args_list[0].kwargs["ex"] == 604_800


@pytest.mark.asyncio
async def test_set_without_label_skips_label_write() -> None:
    """set() with no label only writes the value SET, not a label SET."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()

    with patch("redis.asyncio.from_url", return_value=r):
        await cache.set("key1", "value1")

    pipe = r.pipeline()
    assert pipe.set.call_count == 1


@pytest.mark.asyncio
async def test_set_evicts_oldest_live_entry_when_over_maxsize() -> None:
    """set() evicts an oldest candidate via ZPOPMIN when it's confirmed still live."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=2, ttl=60)
    r = _mock_redis()
    r.zcard = AsyncMock(return_value=3)  # one over capacity
    r.zpopmin = AsyncMock(return_value=[("oldest_key", 1.0)])
    # execute() is called 3 times: the write pipeline, the EXISTS-check
    # pipeline (oldest_key is still live), then the delete pipeline.
    r.pipeline().execute.side_effect = [[], [1], []]

    with patch("redis.asyncio.from_url", return_value=r):
        await cache.set("key3", "v3")

    r.zpopmin.assert_called_once_with("jidou:tmdb_cache:order", 1)
    pipe = r.pipeline()
    delete_calls = list(pipe.delete.call_args_list)
    assert delete_calls[0].args[0] == "jidou:tmdb_cache:entry:oldest_key"
    assert delete_calls[1].args[0] == "jidou:tmdb_cache:label:oldest_key"


@pytest.mark.asyncio
async def test_set_skips_deleting_ghost_zset_members() -> None:
    """A popped candidate whose entry key already expired (a "ghost") is not deleted.

    Regression test: ZCARD on the order zset can overcount because expired
    entry/label keys leave ghost members behind (TTL expiry on one key
    doesn't prune a separate zset). Without the EXISTS check, evicting
    "overflow" candidates could delete real, still-live entries to make up
    for a count inflated by ghosts.
    """
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=2, ttl=60)
    r = _mock_redis()
    r.zcard = AsyncMock(return_value=3)
    r.zpopmin = AsyncMock(return_value=[("ghost_key", 1.0)])
    # EXISTS reports the ghost's entry key is gone (already TTL-expired).
    r.pipeline().execute.side_effect = [[], [0], []]

    with patch("redis.asyncio.from_url", return_value=r):
        await cache.set("key3", "v3")

    pipe = r.pipeline()
    assert pipe.delete.call_count == 0


@pytest.mark.asyncio
async def test_set_no_eviction_when_under_maxsize() -> None:
    """set() does not call ZPOPMIN when under the configured cap."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.zcard = AsyncMock(return_value=5)

    with patch("redis.asyncio.from_url", return_value=r):
        await cache.set("key1", "v1")

    r.zpopmin.assert_not_called()


@pytest.mark.asyncio
async def test_stats_empty_cache() -> None:
    """stats() on an empty cache returns zero count and empty entries."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()

    with patch("redis.asyncio.from_url", return_value=r):
        stats = await cache.stats()

    assert stats == {"count": 0, "maxsize": 100, "ttl_seconds": 60, "entries": []}


@pytest.mark.asyncio
async def test_stats_returns_labelled_entries() -> None:
    """stats() reports count and labels for live (SCAN-discovered) entries."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.scan = AsyncMock(return_value=(0, ["jidou:tmdb_cache:entry:key1"]))
    r.mget = AsyncMock(return_value=["TMDB:999"])

    with patch("redis.asyncio.from_url", return_value=r):
        stats = await cache.stats()

    assert stats["count"] == 1
    assert stats["entries"] == [{"label": "TMDB:999", "key": "key1"}]


@pytest.mark.asyncio
async def test_stats_omits_entries_with_no_label() -> None:
    """An entry whose label key expired/was never set is counted but not listed."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.scan = AsyncMock(return_value=(0, ["jidou:tmdb_cache:entry:key1"]))
    r.mget = AsyncMock(return_value=[None])

    with patch("redis.asyncio.from_url", return_value=r):
        stats = await cache.stats()

    assert stats["count"] == 1
    assert stats["entries"] == []


@pytest.mark.asyncio
async def test_stats_scan_paginates_across_multiple_cursors() -> None:
    """SCAN loop follows a non-zero cursor until it returns to 0."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.scan = AsyncMock(
        side_effect=[
            (7, ["jidou:tmdb_cache:entry:key1"]),
            (0, ["jidou:tmdb_cache:entry:key2"]),
        ]
    )
    r.mget = AsyncMock(return_value=["L1", "L2"])

    with patch("redis.asyncio.from_url", return_value=r):
        stats = await cache.stats()

    assert stats["count"] == 2
    assert r.scan.call_count == 2


@pytest.mark.asyncio
async def test_flush_deletes_all_matched_keys_and_returns_entry_count() -> None:
    """flush() deletes every entry/label key plus the order zset, returns entry count."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.scan = AsyncMock(
        side_effect=[
            (0, ["jidou:tmdb_cache:entry:key1", "jidou:tmdb_cache:entry:key2"]),
            (0, ["jidou:tmdb_cache:label:key1"]),
        ]
    )
    r.delete = AsyncMock()

    with patch("redis.asyncio.from_url", return_value=r):
        cleared = await cache.flush()

    assert cleared == 2
    r.delete.assert_called_once_with(
        "jidou:tmdb_cache:entry:key1",
        "jidou:tmdb_cache:entry:key2",
        "jidou:tmdb_cache:label:key1",
        "jidou:tmdb_cache:order",
    )


@pytest.mark.asyncio
async def test_flush_empty_cache_reports_zero_cleared() -> None:
    """flush() on an already-empty cache reports cleared=0 (still clears the order zset)."""
    cache = CacheBackend(redis_url="redis://localhost:6379", maxsize=100, ttl=60)
    r = _mock_redis()
    r.delete = AsyncMock()

    with patch("redis.asyncio.from_url", return_value=r):
        cleared = await cache.flush()

    assert cleared == 0
    r.delete.assert_called_once_with("jidou:tmdb_cache:order")


def test_make_key_is_deterministic_sha256() -> None:
    """make_key() returns a stable sha256 hex digest for the same URL."""
    key1 = CacheBackend.make_key("https://api.themoviedb.org/3/tv/123")
    key2 = CacheBackend.make_key("https://api.themoviedb.org/3/tv/123")
    assert key1 == key2
    assert len(key1) == 64
