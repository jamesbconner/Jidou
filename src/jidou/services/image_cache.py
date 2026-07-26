"""Disk-backed cache for TMDB poster/backdrop image bytes.

Storage is defined behind :class:`ImageCacheBackend` so the concrete
implementation can be swapped (e.g. for a self-hosted S3-compatible store)
without touching callers — see :func:`create_image_cache_backend`.
"""

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from jidou.config import Settings, settings

logger = logging.getLogger(__name__)


class ImageCacheBackend(Protocol):
    """Storage interface for cached TMDB image bytes."""

    async def get(self, size: str, filename: str) -> bytes | None:
        """Return cached image bytes for *size*/*filename*, or None on a miss."""
        ...

    async def put(self, size: str, filename: str, data: bytes) -> None:
        """Store *data* under *size*/*filename*."""
        ...

    async def purge_older_than(self, cutoff: datetime, *, dry_run: bool = False) -> int:
        """Delete cached files last modified before *cutoff*.

        Args:
            cutoff: Timezone-aware cutoff; files with an mtime before this
                are deleted.
            dry_run: When True, log what would be deleted without deleting
                anything.

        Returns:
            The number of files deleted (or that would be deleted, in
            ``dry_run`` mode).
        """
        ...


class DiskImageCacheBackend:
    """Stores image bytes on local disk at ``{base_path}/{size}/{filename}``.

    The layout mirrors TMDB's own image URL shape 1:1, which keeps the
    mapping trivial — size is restricted by the caller to a small whitelist
    and filenames are TMDB's own short hashes, so directory fan-out stays
    bounded without any hashing/bucketing scheme.

    Args:
        base_path: Root directory for cached image files.
    """

    def __init__(self, base_path: str) -> None:
        self._base_path = Path(base_path)

    def _safe_path(self, size: str, filename: str) -> Path:
        """Resolve *size*/*filename* to a path guaranteed to stay under base_path.

        Defense-in-depth beyond the route layer's own size/filename
        validation — a backend should never write or read outside its own
        root regardless of what a caller passes in.

        Raises:
            ValueError: If the resolved path would escape ``base_path``.
        """
        base = self._base_path.resolve()
        candidate = (base / size / filename).resolve()
        if candidate != base and base not in candidate.parents:
            raise ValueError(f"Path escapes image cache root: {size}/{filename}")
        return candidate

    async def get(self, size: str, filename: str) -> bytes | None:
        """Read cached bytes from disk, or None if the file doesn't exist."""
        path = self._safe_path(size, filename)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None

    async def put(self, size: str, filename: str, data: bytes) -> None:
        """Write *data* to disk, creating the size subdirectory if needed."""
        path = self._safe_path(size, filename)
        await asyncio.to_thread(self._write, path, data)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        """Write *data* to *path* atomically via a temp file + rename.

        A crash, OOM-kill, or full disk mid-write must never leave a
        partial file at *path* -- ``get()`` has no way to distinguish a
        truncated file from a valid one, so a non-atomic write would let a
        corrupt image get served (and browser-cached) indefinitely.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp_path.write_bytes(data)
            os.replace(tmp_path, path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    async def purge_older_than(self, cutoff: datetime, *, dry_run: bool = False) -> int:
        """Delete cached files last modified before *cutoff*.

        Args:
            cutoff: Timezone-aware cutoff; files with an mtime before this
                are deleted.
            dry_run: When True, log what would be deleted without deleting
                anything.

        Returns:
            The number of files deleted (or that would be deleted, in
            ``dry_run`` mode).
        """
        return await asyncio.to_thread(self._purge_older_than, cutoff, dry_run)

    def _purge_older_than(self, cutoff: datetime, dry_run: bool = False) -> int:
        if not self._base_path.exists():
            return 0
        deleted = 0
        for path in self._base_path.rglob("*"):
            try:
                if not path.is_file():
                    continue
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except FileNotFoundError:
                # Removed by a concurrent purge (or manual cleanup) between
                # this walk listing it and stat-ing it -- not this run's job.
                continue
            if mtime >= cutoff:
                continue
            if dry_run:
                logger.info("Image cache purge (dry run): would delete %s (mtime=%s)", path, mtime)
            else:
                try:
                    path.unlink()
                except FileNotFoundError:
                    # Same race as above, just later in the same iteration.
                    continue
            deleted += 1
        return deleted


def create_image_cache_backend(config: Settings) -> ImageCacheBackend | None:
    """Instantiate the configured :class:`ImageCacheBackend`.

    Image caching is a non-critical convenience, not core functionality (see
    module docstring) -- an unsupported ``image_cache_backend`` value is
    logged as a warning rather than raised, so a config typo doesn't take
    down the whole API/worker/beat process at import time.

    Args:
        config: Application settings; reads ``image_cache_backend`` and
            ``image_cache_path``.

    Returns:
        A backend instance for the configured type, or None if
        ``image_cache_backend`` names an unsupported type.
    """
    backend_type = config.image_cache_backend
    if backend_type == "disk":
        return DiskImageCacheBackend(base_path=config.image_cache_path)
    logger.warning(
        "Unsupported image_cache_backend %r; image caching is disabled for this process",
        backend_type,
    )
    return None


# Module-level singleton shared by the images route and the purge task.
# Callers must handle None -- see create_image_cache_backend's docstring.
image_cache_backend: ImageCacheBackend | None = create_image_cache_backend(settings)
