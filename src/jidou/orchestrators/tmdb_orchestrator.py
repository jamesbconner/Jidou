"""Orchestrator for syncing TMDB show/episode metadata into the database."""

import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)


@dataclass
class TMDBSyncResult:
    """Result of a TMDB episode sync operation."""

    shows_synced: int
    episodes_upserted: int
    episodes_skipped: int


class TMDBOrchestrator:
    """Fetch TMDB season/episode data and upsert Episode rows.

    Args:
        session: Active async SQLAlchemy session.
        tmdb: Configured TMDBService instance.
    """

    def __init__(self, session: AsyncSession, tmdb: TMDBService) -> None:
        self.session = session
        self.tmdb = tmdb

    async def sync_show_episodes(
        self,
        show: Show,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> TMDBSyncResult:
        """Fetch all seasons and episodes for one show and upsert Episode rows.

        Skips season 0 (specials). Marks show.cached = True on completion.

        Args:
            show: Show ORM object to sync.
            on_progress: Optional async callback(current, total, message).

        Returns:
            TMDBSyncResult with counts.
        """
        show_data = await self.tmdb.get_show_seasons(show.tmdb_id)
        seasons = [
            s for s in show_data.get("seasons", [])
            if s.get("season_number", 0) > 0
        ]

        total = len(seasons)
        episodes_upserted = 0
        episodes_skipped = 0

        for idx, season in enumerate(seasons, 1):
            season_num = season["season_number"]
            if on_progress:
                await on_progress(idx, total, f"Fetching S{season_num:02d} of {show.title}")

            season_data = await self.tmdb.get_season_details(show.tmdb_id, season_num)

            for ep_data in season_data.get("episodes", []):
                tmdb_ep_id: int | None = ep_data.get("id")
                if not tmdb_ep_id:
                    continue

                stmt = select(Episode).where(Episode.tmdb_id == tmdb_ep_id)
                existing = (await self.session.execute(stmt)).scalar_one_or_none()

                air_date: date | None = None
                raw_date = ep_data.get("air_date")
                if raw_date:
                    with contextlib.suppress(ValueError):
                        air_date = date.fromisoformat(raw_date)

                if existing is not None:
                    existing.name = ep_data.get("name", existing.name)
                    existing.overview = ep_data.get("overview")
                    existing.air_date = air_date
                    existing.runtime = ep_data.get("runtime")
                    episodes_skipped += 1
                else:
                    new_ep = Episode(
                        show_id=show.id,
                        tmdb_id=tmdb_ep_id,
                        season_number=season_num,
                        episode_number=ep_data.get("episode_number", 0),
                        name=ep_data.get("name", ""),
                        overview=ep_data.get("overview"),
                        air_date=air_date,
                        runtime=ep_data.get("runtime"),
                    )
                    self.session.add(new_ep)
                    episodes_upserted += 1

        await self.session.flush()
        show.cached = True
        await self.session.commit()

        logger.info(
            "TMDB sync complete for %r: %d upserted, %d skipped",
            show.title,
            episodes_upserted,
            episodes_skipped,
        )
        return TMDBSyncResult(
            shows_synced=1,
            episodes_upserted=episodes_upserted,
            episodes_skipped=episodes_skipped,
        )

    async def sync_all_shows(
        self,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> TMDBSyncResult:
        """Sync episodes for all shows where cached=False.

        Args:
            on_progress: Optional async callback(current, total, message).

        Returns:
            Aggregated TMDBSyncResult across all shows.
        """
        stmt = select(Show).where(Show.cached == False)  # noqa: E712
        shows = list((await self.session.execute(stmt)).scalars().all())

        total = len(shows)
        combined = TMDBSyncResult(shows_synced=0, episodes_upserted=0, episodes_skipped=0)

        for idx, show in enumerate(shows, 1):
            if on_progress:
                await on_progress(idx, total, f"Syncing {show.title}")
            try:
                result = await self.sync_show_episodes(show)
                combined.shows_synced += result.shows_synced
                combined.episodes_upserted += result.episodes_upserted
                combined.episodes_skipped += result.episodes_skipped
            except Exception:
                logger.exception("Failed to sync TMDB data for show id=%d", show.id)

        return combined
