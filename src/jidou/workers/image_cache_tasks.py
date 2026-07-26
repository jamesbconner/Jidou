"""Celery task for pruning stale entries from the on-disk TMDB image cache."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from celery import shared_task

from jidou.config import settings
from jidou.services.image_cache import image_cache_backend

logger = logging.getLogger(__name__)


@shared_task  # type: ignore[untyped-decorator]
def purge_stale_images_task() -> dict[str, int]:
    """Delete cached image files older than ``settings.image_cache_retention_days``.

    Returns:
        Dict with a ``purged`` count, for observability in worker logs.
    """
    return asyncio.run(_purge_stale_images())


async def _purge_stale_images() -> dict[str, int]:
    """Compute the retention cutoff and delegate deletion to the cache backend."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.image_cache_retention_days)
    purged = await image_cache_backend.purge_older_than(cutoff)
    logger.info("Image cache purge: removed %d file(s) older than %s", purged, cutoff.isoformat())
    return {"purged": purged}
