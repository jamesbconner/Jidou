"""Background tasks for periodic TMDB data synchronization."""

import logging

from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

tmdb = TMDBService()


async def fetch_trending_shows_task() -> int:
    """Fetch trending shows from TMDB and cache them locally.

    Returns:
        The number of shows fetched.
    """
    logger.info("Starting trending shows sync task")
    try:
        result = await tmdb.get_trending(media_type="multi", time_window="day")
        count: int = result.get("total_results", 0)
        logger.info("Trending shows sync completed: %d shows fetched", count)
        return count
    except Exception:
        logger.exception("Trending shows sync task failed")
        raise
