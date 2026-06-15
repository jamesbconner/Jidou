"""Background tasks for periodic TMDB data synchronization."""

import asyncio
import logging

from celery import shared_task
from sqlalchemy import select

from jidou.database import async_session_factory
from jidou.models.show import Show
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

tmdb = TMDBService()


@shared_task  # type: ignore
def fetch_trending_shows_task() -> int:
    """Fetch trending shows from TMDB and persist them to PostgreSQL.

    Returns:
        The number of shows upserted.
    """
    logger.info("Starting trending shows sync task")
    try:
        count = asyncio.run(_fetch_trending())
        logger.info("Trending shows sync completed: %d shows upserted", count)
        return count
    except Exception:
        logger.exception("Trending shows sync task failed")
        raise


async def _fetch_trending() -> int:
    """Fetch trending TV shows from TMDB and upsert them into the database."""
    result = await tmdb.get_trending(media_type="tv", time_window="day")
    trending_items = result.get("results", [])

    upserted = 0
    async with async_session_factory() as session:
        for item in trending_items:
            tmdb_id = item.get("id")
            if tmdb_id is None:
                continue

            # Check if show already exists
            stmt = select(Show).where(Show.tmdb_id == tmdb_id)
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing is not None:
                # Update existing show
                existing.title = item.get("name") or item.get("title", "")
                existing.overview = item.get("overview")
                existing.media_type = "tv"
                existing.poster_path = item.get("poster_path")
                existing.backdrop_path = item.get("backdrop_path")
                existing.vote_average = item.get("vote_average")
                existing.vote_count = item.get("vote_count", 0)
                existing.release_date = item.get("first_air_date")
                existing.original_language = item.get("original_language")
                existing.cached = True
            else:
                # Insert new show
                new_show = Show(
                    tmdb_id=tmdb_id,
                    title=item.get("name") or item.get("title", ""),
                    overview=item.get("overview"),
                    media_type="tv",
                    poster_path=item.get("poster_path"),
                    backdrop_path=item.get("backdrop_path"),
                    vote_average=item.get("vote_average"),
                    vote_count=item.get("vote_count", 0),
                    release_date=item.get("first_air_date"),
                    original_language=item.get("original_language"),
                    cached=True,
                )
                session.add(new_show)

            upserted += 1

        await session.commit()

    return upserted
