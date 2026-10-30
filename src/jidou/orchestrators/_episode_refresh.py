"""Refreshing a show's episode rows from TMDB on demand, for the parse/match step."""

import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)


class EpisodeRefresher(Protocol):
    """Brings a show's episode rows up to date with the metadata source."""

    async def refresh_episodes(self, show: Show) -> bool:
        """Refresh *show*'s episode rows.

        Args:
            show: The show whose episodes to refresh.

        Returns:
            True when the refresh added episodes the database did not have;
            False when nothing new arrived or the refresh failed.
        """
        ...


class TMDBEpisodeRefresher:
    """:class:`EpisodeRefresher` backed by a live (cache-bypassing) TMDB episode sync.

    The sync runs in a SAVEPOINT so a failure discards only the refresh and
    leaves the caller's other pending work in the session intact. Failures are
    logged and reported as "nothing new" rather than raised, since a TMDB
    outage must not turn every unresolved file into an ERROR.

    Args:
        session: Active async SQLAlchemy session shared with the caller.
        tmdb: Configured TMDBService instance.
    """

    def __init__(self, session: AsyncSession, tmdb: TMDBService) -> None:
        self.session = session
        self.tmdb = tmdb

    async def refresh_episodes(self, show: Show) -> bool:
        """Re-sync *show*'s episodes from TMDB, bypassing the response cache.

        Args:
            show: The show whose episodes to refresh.

        Returns:
            True when the sync upserted at least one new episode row.
        """
        # Read before the sync: a rolled-back savepoint can expire the show, and
        # reading an expired attribute in an async session raises MissingGreenlet.
        show_id, title = show.id, show.title
        try:
            async with self.session.begin_nested():
                result = await TMDBOrchestrator(self.session, self.tmdb).sync_show_episodes(
                    show, bypass_cache=True
                )
        except Exception:
            # Reload first so the caller can keep reading the show's attributes.
            await self.session.refresh(show)
            logger.warning(
                "Episode refresh failed for show id=%s (%r); continuing with existing episodes",
                show_id,
                title,
                exc_info=True,
            )
            return False
        logger.info(
            "Episode refresh for show id=%s (%r): %d new episode(s)",
            show_id,
            title,
            result.episodes_upserted,
        )
        return result.episodes_upserted > 0
