"""Celery task for pruning stale entries from the on-disk TMDB image cache."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from celery import shared_task

from jidou.config import settings
from jidou.services.image_cache import image_cache_backend

logger = logging.getLogger(__name__)

_PURGE_LOCK_KEY = "jidou:image_cache_purge:lock"
# Generous ceiling for one purge run so a crashed/killed worker doesn't wedge
# the lock forever -- a full disk walk should never realistically take this long.
_PURGE_LOCK_TTL_SECONDS = 3600


@shared_task  # type: ignore[untyped-decorator]
def purge_stale_images_task(dry_run: bool = False) -> dict[str, int]:
    """Delete cached image files older than ``settings.image_cache_retention_days``.

    Args:
        dry_run: When True, log what would be deleted without deleting
            anything.

    Returns:
        Dict with a ``purged`` count, for observability in worker logs.
    """
    return asyncio.run(_purge_stale_images(dry_run=dry_run))


async def _purge_stale_images(dry_run: bool = False) -> dict[str, int]:
    """Compute the retention cutoff and delegate deletion to the cache backend.

    Guarded by a Redis lock (SET NX PX) so a manually-triggered run that
    overlaps the scheduled beat run is skipped rather than racing it --
    concurrent unlinks of the same file are already handled defensively in
    the backend, but there's no reason to do the same disk walk twice.
    """
    if image_cache_backend is None:
        logger.warning("Image cache backend not configured; skipping purge")
        return {"purged": 0}

    r = aioredis.from_url(settings.redis_url)
    try:
        acquired = await r.set(_PURGE_LOCK_KEY, "1", nx=True, ex=_PURGE_LOCK_TTL_SECONDS)
        if not acquired:
            logger.info("Image cache purge already in progress; skipping this run")
            return {"purged": 0}
        try:
            cutoff = datetime.now(UTC) - timedelta(days=settings.image_cache_retention_days)
            purged = await image_cache_backend.purge_older_than(cutoff, dry_run=dry_run)
            logger.info(
                "Image cache purge%s: %s %d file(s) older than %s",
                " (dry run)" if dry_run else "",
                "would remove" if dry_run else "removed",
                purged,
                cutoff.isoformat(),
            )
            return {"purged": purged}
        finally:
            await r.delete(_PURGE_LOCK_KEY)
    finally:
        await r.aclose()
