"""Tests for the image cache purge Celery task."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from jidou.workers.image_cache_tasks import _purge_stale_images, purge_stale_images_task


def _mock_redis(*, lock_acquired: bool = True) -> AsyncMock:
    """Build a mock Redis client for the purge task's overlap-guard lock."""
    r = AsyncMock()
    r.set = AsyncMock(return_value=lock_acquired)
    r.delete = AsyncMock()
    r.aclose = AsyncMock()
    return r


@pytest.mark.asyncio
async def test_purge_stale_images_uses_configured_retention() -> None:
    """The cutoff passed to the backend is now() minus the configured retention."""
    mock_purge = AsyncMock(return_value=3)
    r = _mock_redis()

    with (
        patch("jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than", mock_purge),
        patch("jidou.workers.image_cache_tasks.settings.image_cache_retention_days", 90),
        patch("redis.asyncio.from_url", return_value=r),
    ):
        before = datetime.now(UTC) - timedelta(days=90)
        result = await _purge_stale_images()
        after = datetime.now(UTC) - timedelta(days=90)

    mock_purge.assert_called_once()
    (cutoff,) = mock_purge.call_args.args
    assert before <= cutoff <= after
    assert mock_purge.call_args.kwargs == {"dry_run": False}
    assert result == {"purged": 3}


@pytest.mark.asyncio
async def test_purge_stale_images_dry_run_is_threaded_through() -> None:
    """dry_run=True on the task reaches the backend call."""
    mock_purge = AsyncMock(return_value=7)
    r = _mock_redis()

    with (
        patch("jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than", mock_purge),
        patch("redis.asyncio.from_url", return_value=r),
    ):
        result = await _purge_stale_images(dry_run=True)

    assert mock_purge.call_args.kwargs == {"dry_run": True}
    assert result == {"purged": 7}


@pytest.mark.asyncio
async def test_purge_stale_images_skips_when_lock_already_held() -> None:
    """An overlapping run (lock already held) is skipped, not raced."""
    mock_purge = AsyncMock(return_value=99)
    r = _mock_redis(lock_acquired=False)

    with (
        patch("jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than", mock_purge),
        patch("redis.asyncio.from_url", return_value=r),
    ):
        result = await _purge_stale_images()

    mock_purge.assert_not_called()
    assert result == {"purged": 0}


@pytest.mark.asyncio
async def test_purge_stale_images_releases_lock_after_run() -> None:
    """The lock is always released, success or failure."""
    mock_purge = AsyncMock(return_value=1)
    r = _mock_redis()

    with (
        patch("jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than", mock_purge),
        patch("redis.asyncio.from_url", return_value=r),
    ):
        await _purge_stale_images()

    r.delete.assert_awaited_once()
    r.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_stale_images_skips_when_backend_not_configured() -> None:
    """A None backend (graceful-init fallback) is a no-op, not a crash."""
    with patch("jidou.workers.image_cache_tasks.image_cache_backend", None):
        result = await _purge_stale_images()

    assert result == {"purged": 0}


def test_purge_stale_images_task_runs_the_async_body() -> None:
    """The Celery task wrapper drives _purge_stale_images via asyncio.run."""
    with patch(
        "jidou.workers.image_cache_tasks._purge_stale_images",
        AsyncMock(return_value={"purged": 5}),
    ) as mock_purge:
        result = purge_stale_images_task()

    mock_purge.assert_called_once_with(dry_run=False)
    assert result == {"purged": 5}


def test_purge_stale_images_task_forwards_dry_run() -> None:
    """The Celery task wrapper passes dry_run through to the async body."""
    with patch(
        "jidou.workers.image_cache_tasks._purge_stale_images",
        AsyncMock(return_value={"purged": 0}),
    ) as mock_purge:
        purge_stale_images_task(dry_run=True)

    mock_purge.assert_called_once_with(dry_run=True)


@pytest.mark.asyncio
async def test_purge_stale_images_acquires_lock_with_key_and_ttl() -> None:
    """The lock is SET NX EX with the pinned key and one-hour TTL (wire contract)."""
    r = _mock_redis()

    with (
        patch(
            "jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than",
            AsyncMock(return_value=0),
        ),
        patch("redis.asyncio.from_url", return_value=r),
    ):
        await _purge_stale_images()

    r.set.assert_awaited_once_with("jidou:image_cache_purge:lock", "1", nx=True, ex=3600)
    r.delete.assert_awaited_once_with("jidou:image_cache_purge:lock")


@pytest.mark.asyncio
async def test_purge_stale_images_lock_held_does_not_delete_and_closes() -> None:
    """A held lock is never deleted by the loser, and the client is still closed."""
    r = _mock_redis(lock_acquired=False)

    with (
        patch(
            "jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than",
            AsyncMock(return_value=1),
        ),
        patch("redis.asyncio.from_url", return_value=r),
    ):
        await _purge_stale_images()

    r.delete.assert_not_awaited()
    r.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_stale_images_releases_lock_when_purge_raises() -> None:
    """A failing purge propagates, but the lock is released and the client closed."""
    r = _mock_redis()

    with (
        patch(
            "jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than",
            AsyncMock(side_effect=OSError("disk gone")),
        ),
        patch("redis.asyncio.from_url", return_value=r),
        pytest.raises(OSError, match="disk gone"),
    ):
        await _purge_stale_images()

    r.delete.assert_awaited_once_with("jidou:image_cache_purge:lock")
    r.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_stale_images_redis_down_propagates_without_delete() -> None:
    """If the lock SET itself fails (Redis down) the error propagates; no DEL; client closed."""
    r = _mock_redis()
    r.set = AsyncMock(side_effect=ConnectionError("redis down"))
    purge = AsyncMock(return_value=0)

    with (
        patch("jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than", purge),
        patch("redis.asyncio.from_url", return_value=r),
        pytest.raises(ConnectionError, match="redis down"),
    ):
        await _purge_stale_images()

    purge.assert_not_awaited()
    r.delete.assert_not_awaited()
    r.aclose.assert_awaited_once()
