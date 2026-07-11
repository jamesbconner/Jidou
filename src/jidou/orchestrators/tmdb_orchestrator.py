"""Orchestrator for syncing TMDB show/episode metadata into the database."""

import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import cast

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.services.episode_group_mapping import (
    fetch_group_breakdowns,
    flatten_for_absolute_numbering,
    to_storage_map,
)
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
        Flushes but does not commit — the caller owns the transaction
        boundary. A caller processing multiple shows in one session (e.g.
        :meth:`sync_all_shows`) must commit after each show itself if it
        wants a later show's failure to leave earlier successes durable.

        Args:
            show: Show ORM object to sync.
            on_progress: Optional async callback(current, total, message).

        Returns:
            TMDBSyncResult with counts.
        """
        show_data = await self.tmdb.get_show_seasons(show.tmdb_id)
        seasons = [s for s in show_data.get("seasons", []) if s.get("season_number", 0) > 0]

        total = len(seasons)
        episodes_upserted = 0
        episodes_skipped = 0
        # Keyed for the absolute_episode_number backfill below -- avoids a
        # second round-trip query for rows we just upserted in this session.
        episodes_by_key: dict[tuple[int, int], Episode] = {}

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

                episode_num = ep_data.get("episode_number", 0)

                if existing is not None:
                    existing.name = ep_data.get("name", existing.name)
                    existing.overview = ep_data.get("overview")
                    existing.air_date = air_date
                    existing.runtime = ep_data.get("runtime")
                    existing.episode_type = ep_data.get("episode_type")
                    existing.still_path = ep_data.get("still_path")
                    episodes_by_key[(season_num, episode_num)] = existing
                    episodes_skipped += 1
                else:
                    new_ep = Episode(
                        show_id=show.id,
                        tmdb_id=tmdb_ep_id,
                        season_number=season_num,
                        episode_number=episode_num,
                        name=ep_data.get("name", ""),
                        overview=ep_data.get("overview"),
                        air_date=air_date,
                        runtime=ep_data.get("runtime"),
                        episode_type=ep_data.get("episode_type"),
                        still_path=ep_data.get("still_path"),
                    )
                    self.session.add(new_ep)
                    episodes_by_key[(season_num, episode_num)] = new_ep
                    episodes_upserted += 1

        if episodes_upserted + episodes_skipped > 0:
            show.cached = True

        await self._apply_episode_group_map(show, episodes_by_key.values())
        await self.session.flush()

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

    async def sync_episode_group_map(self, show: Show) -> None:
        """Backfill episode_group_map/absolute_episode_number for an already-synced show.

        Lighter than :meth:`sync_show_episodes`: fetches only the
        episode_groups breakdown, not the full season/episode data, so it's
        safe for a caller (e.g. path-import resolving a show it found
        already in the DB) to call on every touch of a show whose episodes
        exist but whose ``episode_group_map`` was never built -- most
        commonly a show synced before this feature existed.

        Args:
            show: Show ORM object whose episodes are already present in the DB.
        """
        stmt = select(Episode).where(Episode.show_id == show.id)
        episodes = (await self.session.execute(stmt)).scalars().all()
        await self._apply_episode_group_map(show, episodes)
        await self.session.flush()

    async def ensure_episode_group_map(self, show: Show) -> None:
        """Ensure a show's episode_group_map is populated if episodes exist.

        No-op when:
        - ``show.episode_group_map`` is already set (even ``{}`` meaning
          "checked, nothing found" — see :func:`to_storage_map`).
        - The show has no episodes yet (a full :meth:`sync_show_episodes`
          is needed first; this method won't trigger one).

        Otherwise calls :meth:`sync_episode_group_map` to backfill. Failures
        are logged and swallowed — this is best-effort enrichment, not a
        hard requirement for the caller to proceed.

        Args:
            show: Show ORM object to check and potentially backfill.
        """
        if show.episode_group_map is not None:
            return

        ep_count = await self.session.scalar(
            select(func.count()).select_from(Episode).where(Episode.show_id == show.id)
        )
        if not ep_count:
            return

        try:
            await self.sync_episode_group_map(show)
        except Exception:
            logger.warning(
                "episode_group_map backfill failed for show id=%d; "
                "episode matching will proceed without cour/season remap",
                show.id,
                exc_info=True,
            )

    async def _apply_episode_group_map(self, show: Show, episodes: Iterable[Episode]) -> None:
        """Fetch episode_groups and store the map, backfilling absolute_episode_number.

        Best-effort: resolves type-6/type-2 episode_groups into a season/cour
        remap for path-import's cour-vs-absolute mismatch handling, and uses
        the same fetch to backfill ``Episode.absolute_episode_number`` where
        it's known. A fetch failure must not abort an otherwise-successful
        episode sync -- and must not overwrite a previously-successful map
        with nothing, so a failure leaves *show* and *episodes* untouched
        rather than clearing their existing data.

        ``show.episode_groups`` is normally populated by
        :func:`~jidou.services.tmdb_mapping.fetch_show_metadata` when a show
        is created, but not every creation path uses it (e.g. adding a show
        directly from a TMDB search card). ``None`` means "never checked" and
        is fetched here on demand; ``[]`` means "checked, TMDB reports none"
        and is left alone to avoid re-fetching it on every sync.

        Args:
            show: Show ORM object to update ``episode_group_map`` on.
            episodes: Episode rows belonging to *show* to backfill
                ``absolute_episode_number`` on. Must reflect the show's
                full current episode set for a successful fetch to clear
                stale absolute numbers correctly -- a partial set would
                leave omitted episodes with whatever they had before.
        """
        if show.episode_groups is None:
            try:
                groups_response = await self.tmdb.get_episode_groups(show.tmdb_id)
                show.episode_groups = list(groups_response.get("results") or [])
            except Exception:
                logger.warning(
                    "Failed to fetch episode_groups summary for show id=%s; leaving existing "
                    "episode_group_map and absolute_episode_number data untouched",
                    show.id,
                    exc_info=True,
                )
                return

        try:
            breakdowns = await fetch_group_breakdowns(self.tmdb, show.episode_groups)
        except Exception:
            logger.warning(
                "Failed to fetch episode_group breakdowns for show id=%s; leaving existing "
                "episode_group_map and absolute_episode_number data untouched",
                show.id,
                exc_info=True,
            )
            return

        # dict is invariant in its value type, so the precisely-typed
        # StoredGroupMap needs a cast to satisfy the looser JSONB column type.
        show.episode_group_map = cast(dict[str, object], to_storage_map(breakdowns))
        flattened = flatten_for_absolute_numbering(breakdowns)
        for ep in episodes:
            ep.absolute_episode_number = flattened.get((ep.season_number, ep.episode_number))

    async def sync_all_shows(
        self,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> TMDBSyncResult:
        """Sync episodes for all shows where cached=False or episodes don't exist.

        Ensures shows without episode data get synced even if cached flag was set by
        other code (e.g., trending task) that doesn't populate episodes.

        Args:
            on_progress: Optional async callback(current, total, message).

        Returns:
            Aggregated TMDBSyncResult across all shows.
        """
        no_episodes = ~exists(select(Episode).where(Episode.show_id == Show.id))
        stmt = select(Show).where((Show.cached == False) | no_episodes)  # noqa: E712
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
                # Commit per show so a later show's failure only rolls back
                # its own partial work, not every show already synced in
                # this batch (sync_show_episodes itself only flushes).
                await self.session.commit()
            except Exception:
                logger.exception("Failed to sync TMDB data for show id=%d", show.id)
                await self.session.rollback()

        return combined
