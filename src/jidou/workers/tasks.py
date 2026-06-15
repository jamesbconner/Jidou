"""Background tasks for periodic TMDB data synchronization."""

import asyncio
import logging

from celery import shared_task

from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

tmdb = TMDBService()


@shared_task  # type: ignore
def fetch_trending_shows_task() -> int:
    """Fetch trending shows from TMDB and cache them locally.

    Returns:
        The number of shows fetched.
    """
    logger.info("Starting trending shows sync task")
    try:
        count = asyncio.run(_fetch_trending())
        logger.info("Trending shows sync completed: %d shows fetched", count)
        return count
    except Exception:
        logger.exception("Trending shows sync task failed")
        raise


async def _fetch_trending() -> int:
    """Async helper for the trending shows fetch."""
    result = await tmdb.get_trending(media_type="multi", time_window="day")
    return result.get("total_results", 0)  # type: ignore
