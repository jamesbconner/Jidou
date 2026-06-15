"""Background tasks for periodic TMDB data synchronization."""

import asyncio
import logging

from celery import shared_task
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
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
    """Fetch trending TV shows from TMDB and upsert them into the database.

    Creates its own engine/session so it is independent of the
    FastAPI process's module-level engine and safe to call inside
    asyncio.run() without stale-pool errors.
    """
    # Build a task-local engine so the connection pool is tied to the
    # event loop created by asyncio.run() in the caller.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        result = await tmdb.get_trending(media_type="tv", time_window="day")
        trending_items = result.get("results", [])

        upserted = 0
        async with session_factory() as session:
            for item in trending_items:
                tmdb_id = item.get("id")
                if tmdb_id is None:
                    continue

                # Use ON CONFLICT DO UPDATE (true upsert) to avoid
                # select-then-insert race conditions when multiple
                # workers run concurrently.
                ins = insert(Show).values(
                    tmdb_id=tmdb_id,
                    title=item.get("name") or item.get("title", ""),
                    overview=item.get("overview"),
                    media_type="tv",
                    poster_path=item.get("poster_path"),
                    backdrop_path=item.get("backdrop_path"),
                    vote_average=item.get("vote_average"),
                    vote_count=item.get("vote_count") or 0,
                    release_date=item.get("first_air_date"),
                    original_language=item.get("original_language"),
                    cached=True,
                )
                stmt = ins.on_conflict_do_update(
                    index_elements=["tmdb_id"],
                    set_={
                        "title": ins.excluded.title,
                        "overview": ins.excluded.overview,
                        "media_type": ins.excluded.media_type,
                        "poster_path": ins.excluded.poster_path,
                        "backdrop_path": ins.excluded.backdrop_path,
                        "vote_average": ins.excluded.vote_average,
                        "vote_count": ins.excluded.vote_count,
                        "release_date": ins.excluded.release_date,
                        "original_language": ins.excluded.original_language,
                        "cached": ins.excluded.cached,
                    },
                )

                await session.execute(stmt)
                upserted += 1

            await session.commit()

        return upserted
    finally:
        await engine.dispose()
