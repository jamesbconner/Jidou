"""Tests for the disk-backed image cache service."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jidou.config import Settings
from jidou.services.image_cache import DiskImageCacheBackend, create_image_cache_backend


@pytest.fixture
def backend(tmp_path: Path) -> DiskImageCacheBackend:
    """A DiskImageCacheBackend rooted at a fresh temp directory."""
    return DiskImageCacheBackend(base_path=str(tmp_path))


@pytest.mark.asyncio
async def test_get_returns_none_on_miss(backend: DiskImageCacheBackend) -> None:
    """get() returns None when no cached file exists."""
    assert await backend.get("w300", "missing.jpg") is None


@pytest.mark.asyncio
async def test_put_then_get_round_trips_bytes(backend: DiskImageCacheBackend) -> None:
    """put() writes bytes that a subsequent get() reads back unchanged."""
    await backend.put("w300", "abc123.jpg", b"fake-jpeg-bytes")

    result = await backend.get("w300", "abc123.jpg")

    assert result == b"fake-jpeg-bytes"


@pytest.mark.asyncio
async def test_put_creates_size_subdirectory(
    backend: DiskImageCacheBackend, tmp_path: Path
) -> None:
    """put() creates the {size}/ subdirectory on demand."""
    await backend.put("w185", "def456.png", b"png-bytes")

    assert (tmp_path / "w185" / "def456.png").read_bytes() == b"png-bytes"


def test_safe_path_rejects_traversal(backend: DiskImageCacheBackend) -> None:
    """_safe_path raises ValueError for a filename that would escape base_path."""
    with pytest.raises(ValueError, match="escapes"):
        backend._safe_path("w300", "../../etc/passwd")


@pytest.mark.asyncio
async def test_purge_older_than_deletes_only_stale_files(
    backend: DiskImageCacheBackend, tmp_path: Path
) -> None:
    """purge_older_than deletes files with mtime before cutoff, across size subdirs."""
    now = datetime.now(UTC)
    old_file = tmp_path / "w92" / "old.jpg"
    new_file = tmp_path / "w300" / "new.jpg"
    old_file.parent.mkdir(parents=True)
    new_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")

    old_timestamp = (now - timedelta(days=200)).timestamp()
    os.utime(old_file, (old_timestamp, old_timestamp))

    cutoff = now - timedelta(days=180)
    deleted = await backend.purge_older_than(cutoff)

    assert deleted == 1
    assert not old_file.exists()
    assert new_file.exists()


@pytest.mark.asyncio
async def test_purge_older_than_on_missing_base_path_returns_zero(tmp_path: Path) -> None:
    """purge_older_than on a never-written cache directory is a no-op."""
    backend = DiskImageCacheBackend(base_path=str(tmp_path / "never-created"))

    assert await backend.purge_older_than(datetime.now(UTC)) == 0


def test_create_image_cache_backend_defaults_to_disk() -> None:
    """The factory returns a DiskImageCacheBackend for the default 'disk' setting."""
    config = Settings(image_cache_backend="disk", image_cache_path="/tmp/images")

    result = create_image_cache_backend(config)

    assert isinstance(result, DiskImageCacheBackend)
    assert result._base_path == Path("/tmp/images")


def test_create_image_cache_backend_returns_none_for_unsupported_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unsupported backend type logs a warning and returns None rather than
    raising -- image caching is non-critical, so a config typo must not crash
    the whole API/worker/beat process at import time.
    """
    config = Settings(image_cache_backend="garage")

    with caplog.at_level("WARNING"):
        result = create_image_cache_backend(config)

    assert result is None
    assert "garage" in caplog.text


@pytest.mark.asyncio
async def test_put_write_is_atomic_no_partial_file_left_on_failure(
    backend: DiskImageCacheBackend, tmp_path: Path
) -> None:
    """A failure during the write must not leave a partial/temp file behind
    at the final path or in the target directory.
    """
    from unittest.mock import patch

    with (
        patch("pathlib.Path.write_bytes", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        await backend.put("w300", "abc123.jpg", b"data")

    assert not (tmp_path / "w300" / "abc123.jpg").exists()
    assert list((tmp_path / "w300").glob("*.tmp")) == []


@pytest.mark.asyncio
async def test_purge_older_than_dry_run_does_not_delete(
    backend: DiskImageCacheBackend, tmp_path: Path
) -> None:
    """dry_run=True reports what would be deleted without deleting it."""
    now = datetime.now(UTC)
    old_file = tmp_path / "w92" / "old.jpg"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    old_timestamp = (now - timedelta(days=200)).timestamp()
    os.utime(old_file, (old_timestamp, old_timestamp))

    cutoff = now - timedelta(days=180)
    deleted = await backend.purge_older_than(cutoff, dry_run=True)

    assert deleted == 1
    assert old_file.exists()


@pytest.mark.asyncio
async def test_purge_older_than_survives_concurrent_removal(
    backend: DiskImageCacheBackend, tmp_path: Path
) -> None:
    """A file removed between the directory walk and the unlink call (e.g. by
    an overlapping purge run) must not crash the whole purge -- it's just
    skipped.
    """
    now = datetime.now(UTC)
    old_file = tmp_path / "w92" / "old.jpg"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    old_timestamp = (now - timedelta(days=200)).timestamp()
    os.utime(old_file, (old_timestamp, old_timestamp))

    real_unlink = Path.unlink

    def _unlink_then_raise(self: Path, *args: object, **kwargs: object) -> None:
        real_unlink(self)
        raise FileNotFoundError("already gone")

    from unittest.mock import patch

    with patch("pathlib.Path.unlink", _unlink_then_raise):
        # Must not raise -- that's the actual regression under test.
        deleted = await backend.purge_older_than(now - timedelta(days=180))

    # Not counted in this run's tally (the race means it's ambiguous whether
    # this run or a concurrent one "did" the deleting) -- what matters is the
    # file is genuinely gone and the FileNotFoundError didn't propagate.
    assert deleted == 0
    assert not old_file.exists()
