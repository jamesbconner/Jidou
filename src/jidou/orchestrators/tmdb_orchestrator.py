"""Orchestrator for syncing TMDB show/episode metadata into the database."""

import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.show import Show
from jidou.services.episode_group_mapping import (
    fetch_group_breakdowns,
    flatten_for_absolute_numbering,
    to_storage_map,
)
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import fetch_episode_groups_list

logger = logging.getLogger(__name__)


@dataclass
class TMDBSyncResult:
    """Result of a TMDB episode sync operation."""

    shows_synced: int
    episodes_upserted: int
    episodes_skipped: int


@dataclass
class EpisodeGroupApplyResult:
    """Result of switching a show's episode catalog to a TMDB episode_group."""

    episodes_added: int
    episodes_removed: int
    orphaned_file_count: int


def _flatten_episode_group(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a TMDB episode_group detail into an ordered, renumbered episode list.

    Sub-groups become seasons (using the sub-group's own ``order``); episodes
    within a sub-group are renumbered 1..N by their own ``order`` field. This
    treats the applied group as an authoritative structure in its own right --
    unlike :func:`~jidou.services.episode_group_mapping.fetch_group_breakdowns`,
    which only ever resolves (season, episode) pairs back to TMDB's native
    numbering for file-matching remap purposes.

    Args:
        detail: Raw response from :meth:`TMDBService.get_episode_group`.

    Returns:
        Episode dicts (TMDB's own fields plus overridden ``season_number``/
        ``episode_number``, and an added ``absolute_episode_number`` running
        across the whole group regardless of sub-group boundary), in
        insertion order. Specials (native ``season_number == 0``) are
        excluded, consistent with
        :func:`~jidou.services.episode_group_mapping._extract_sub_groups`.
    """
    flattened: list[dict[str, Any]] = []
    sub_groups = sorted(
        (g for g in detail.get("groups", []) if g.get("order") is not None),
        key=lambda g: g["order"],
    )
    absolute_number = 0
    for sub_group in sub_groups:
        season_number = sub_group["order"]
        episodes = [
            ep for ep in sub_group.get("episodes", []) if (ep.get("season_number") or 0) > 0
        ]
        episodes.sort(key=lambda ep: ep.get("order", 0))
        for position, ep_data in enumerate(episodes, start=1):
            absolute_number += 1
            flattened.append(
                {
                    **ep_data,
                    "season_number": season_number,
                    "episode_number": position,
                    "absolute_episode_number": absolute_number,
                }
            )
    return flattened


def _parse_air_date(raw_date: str | None) -> date | None:
    """Parse a TMDB ``air_date`` string, tolerating malformed values.

    Args:
        raw_date: Raw ``air_date`` field from a TMDB episode object, or None.

    Returns:
        The parsed date, or None if *raw_date* is absent or unparseable.
    """
    if not raw_date:
        return None
    with contextlib.suppress(ValueError):
        return date.fromisoformat(raw_date)
    return None


def _update_last_air_date(show: Show, episodes: Iterable[Episode]) -> None:
    """Set show.last_air_date from the newest already-aired episode in *episodes*.

    Leaves *show* untouched if none of *episodes* have aired yet -- a show
    with no aired episodes in the synced set (e.g. unreleased, or every
    episode already accounted for elsewhere) must not have a previously
    known last_air_date clobbered with nothing. The Shows-page "Recently
    Aired" sort reads this column directly, so every path that touches a
    show's episode set (native sync, active-group refresh, or a full group
    apply) must keep it current.

    Args:
        show: Show ORM object to update in place.
        episodes: Episode rows to consider.
    """
    today = date.today()
    aired_dates = [
        ep.air_date for ep in episodes if ep.air_date is not None and ep.air_date <= today
    ]
    if aired_dates:
        show.last_air_date = max(aired_dates).isoformat()


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

        Skips season 0 (specials). Marks show.cached = True on completion,
        and refreshes show.last_air_date from the newest already-aired
        episode in the synced set (Shows-page "Recently Aired" sort reads
        this column directly, so it must track routine episode syncs, not
        just a full TMDB rematch). Flushes but does not commit — the caller
        owns the transaction boundary. A caller processing multiple shows in
        one session (e.g. :meth:`sync_all_shows`) must commit after each show
        itself if it wants a later show's failure to leave earlier successes
        durable.

        Args:
            show: Show ORM object to sync.
            on_progress: Optional async callback(current, total, message).

        Returns:
            TMDBSyncResult with counts.

        Raises:
            ValueError: If *show* is a movie -- TMDB has no
                ``/tv/{id}/season`` structure for movies, so this would
                otherwise just 404 against the endpoint below.
        """
        if show.media_type == "movie":
            raise ValueError(
                f"sync_show_episodes called on a movie (show id={show.id}): "
                "movies have no TMDB /tv/{id}/season structure"
            )
        if show.active_episode_group_id is not None:
            # A manually applied episode_group (see apply_episode_group)
            # replaces the native season/episode structure outright -- a
            # routine sync must refresh *that* group's current data, not
            # silently revert the show back to its native 24-episode catalog.
            return await self._refresh_active_group_episodes(show)
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

                air_date = _parse_air_date(ep_data.get("air_date"))
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

        _update_last_air_date(show, episodes_by_key.values())

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

    async def _refresh_active_group_episodes(self, show: Show) -> TMDBSyncResult:
        """Upsert-refresh episodes from a show's already-applied active_episode_group_id.

        Non-destructive counterpart to :meth:`apply_episode_group`: called by
        :meth:`sync_show_episodes` once a group is active, so a routine "Sync
        Episodes" click just refreshes metadata (name/overview/air_date/etc.)
        in place. Does not purge or renumber -- that one-time transition only
        happens in :meth:`apply_episode_group`, when the group is first
        chosen or changed.

        Args:
            show: Show ORM object whose ``active_episode_group_id`` is set.

        Returns:
            TMDBSyncResult with upsert/skip counts.

        Raises:
            ValueError: If ``show.active_episode_group_id`` is unset -- callers
                (currently only :meth:`sync_show_episodes`) must check this first.
        """
        if show.active_episode_group_id is None:
            raise ValueError(
                f"_refresh_active_group_episodes called on show id={show.id} with no "
                "active_episode_group_id set"
            )
        detail = await self.tmdb.get_episode_group(show.active_episode_group_id)
        flattened = _flatten_episode_group(detail)

        episodes_upserted = 0
        episodes_skipped = 0
        touched: list[Episode] = []
        for ep_data in flattened:
            tmdb_ep_id: int | None = ep_data.get("id")
            if not tmdb_ep_id:
                continue

            stmt = select(Episode).where(Episode.tmdb_id == tmdb_ep_id)
            existing = (await self.session.execute(stmt)).scalar_one_or_none()
            air_date = _parse_air_date(ep_data.get("air_date"))

            if existing is not None:
                existing.season_number = ep_data["season_number"]
                existing.episode_number = ep_data["episode_number"]
                existing.name = ep_data.get("name", existing.name)
                existing.overview = ep_data.get("overview")
                existing.air_date = air_date
                existing.runtime = ep_data.get("runtime")
                existing.episode_type = ep_data.get("episode_type")
                existing.still_path = ep_data.get("still_path")
                existing.absolute_episode_number = ep_data.get("absolute_episode_number")
                touched.append(existing)
                episodes_skipped += 1
            else:
                new_ep = Episode(
                    show_id=show.id,
                    tmdb_id=tmdb_ep_id,
                    season_number=ep_data["season_number"],
                    episode_number=ep_data["episode_number"],
                    name=ep_data.get("name", ""),
                    overview=ep_data.get("overview"),
                    air_date=air_date,
                    runtime=ep_data.get("runtime"),
                    episode_type=ep_data.get("episode_type"),
                    still_path=ep_data.get("still_path"),
                    absolute_episode_number=ep_data.get("absolute_episode_number"),
                )
                self.session.add(new_ep)
                touched.append(new_ep)
                episodes_upserted += 1

        if episodes_upserted + episodes_skipped > 0:
            show.cached = True
        show.active_episode_group_name = detail.get("name")
        _update_last_air_date(show, touched)
        await self.session.flush()
        return TMDBSyncResult(
            shows_synced=1,
            episodes_upserted=episodes_upserted,
            episodes_skipped=episodes_skipped,
        )

    async def apply_episode_group(self, show: Show, group_id: str) -> EpisodeGroupApplyResult:
        """Switch *show*'s episode catalog to a specific TMDB episode_group's structure.

        Destructive: every existing Episode row for *show* is deleted and
        replaced with the group's own episodes, renumbered by sub-group order
        (see :func:`_flatten_episode_group`). Tracking state cannot be carried
        over the switch -- the new rows are unrelated database records even
        when their (season, episode) numbers happen to coincide with the old
        ones -- so every previously tracked episode is persisted as an
        ``OrphanedTrackingRecord`` (the same Data Quality mechanism used
        after a show rematch, see ``ShowRematchOrchestrator``) rather than
        silently dropped or mismatched to the wrong episode.

        ``episode_group_map`` (the orthogonal type-6/2 auto-pick remap used
        for file-matching) is reset to None, since it was computed against
        the now-deleted native structure and would otherwise misresolve a
        declared season/episode against episodes that no longer exist.

        Args:
            show: Show ORM object to switch.
            group_id: TMDB episode_group ID (an entry's ``id`` field from
                ``TMDBService.get_episode_groups``).

        Returns:
            Counts of the change, for the API response.

        Raises:
            ValueError: If *show* is a movie -- movies have no TMDB
                episode_groups structure.
        """
        if show.media_type == "movie":
            raise ValueError(
                f"apply_episode_group called on a movie (show id={show.id}): "
                "movies have no TMDB episode_groups"
            )

        detail = await self.tmdb.get_episode_group(group_id)
        flattened = _flatten_episode_group(detail)

        orphaned_file_count = await self._orphan_tracked_episodes(show.id)
        episodes_removed = (
            await self.session.scalar(
                select(func.count()).select_from(Episode).where(Episode.show_id == show.id)
            )
            or 0
        )
        await self.session.execute(
            Episode.__table__.delete().where(Episode.show_id == show.id)  # type: ignore[attr-defined]
        )
        await self.session.flush()

        new_episodes: list[Episode] = []
        for ep_data in flattened:
            new_ep = Episode(
                show_id=show.id,
                tmdb_id=ep_data["id"],
                season_number=ep_data["season_number"],
                episode_number=ep_data["episode_number"],
                name=ep_data.get("name", ""),
                overview=ep_data.get("overview"),
                air_date=_parse_air_date(ep_data.get("air_date")),
                runtime=ep_data.get("runtime"),
                episode_type=ep_data.get("episode_type"),
                still_path=ep_data.get("still_path"),
                absolute_episode_number=ep_data.get("absolute_episode_number"),
            )
            self.session.add(new_ep)
            new_episodes.append(new_ep)

        show.active_episode_group_id = group_id
        show.active_episode_group_name = detail.get("name")
        show.episode_group_map = None
        show.cached = True
        _update_last_air_date(show, new_episodes)

        await self.session.flush()

        logger.info(
            "Applied episode_group %s to show id=%d: %d removed, %d added, %d file(s) orphaned",
            group_id,
            show.id,
            episodes_removed,
            len(flattened),
            orphaned_file_count,
        )
        return EpisodeGroupApplyResult(
            episodes_added=len(flattened),
            episodes_removed=episodes_removed,
            orphaned_file_count=orphaned_file_count,
        )

    async def _orphan_tracked_episodes(self, show_id: int) -> int:
        """Persist every tracked or watched episode as an OrphanedTrackingRecord before a purge.

        Mirrors the "unrecoverable" branch of
        ``ShowRematchOrchestrator._restore_tracking_and_relink``: a
        DownloadedFile-backed match keeps its ``downloaded_file_id`` (so the
        file, still on disk, can be manually relinked via the Data Quality
        surface); a filename-only import (no DownloadedFile row) is recorded
        without one. Also catches watched-only episodes (``watched=True`` but
        ``file_tracked=False``) -- a plain ``file_tracked`` filter would drop
        watch history for those with no record at all, since
        ``OrphanedTrackingRecord`` has no separate "watched" flag; being
        recorded (rather than silently vanishing) at least surfaces the loss
        via the Data Quality surface even though watch state itself can't be
        automatically restored on resolution.

        Args:
            show_id: DB primary key of the show whose tracked episodes are
                about to be deleted.

        Returns:
            Number of ``OrphanedTrackingRecord`` rows created.
        """
        stmt = select(Episode).where(
            Episode.show_id == show_id,
            (Episode.file_tracked.is_(True)) | (Episode.watched.is_(True)),
        )
        tracked = (await self.session.execute(stmt)).scalars().all()
        if not tracked:
            return 0

        file_stmt = select(DownloadedFile).where(
            DownloadedFile.episode_id.in_([ep.id for ep in tracked])
        )
        files_by_episode_id = {
            f.episode_id: f for f in (await self.session.execute(file_stmt)).scalars().all()
        }

        for ep in tracked:
            backing_file = files_by_episode_id.get(ep.id)
            self.session.add(
                OrphanedTrackingRecord(
                    show_id=show_id,
                    tracked_filename=ep.tracked_filename,
                    tracked_source=ep.tracked_source or "match",
                    old_season_number=ep.season_number,
                    old_episode_number=ep.episode_number,
                    downloaded_file_id=backing_file.id if backing_file else None,
                )
            )
        return len(tracked)

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
        - ``show.active_episode_group_id`` is set. The type-6/2 auto-pick
          remap this backfills is only meaningful for translating a
          filename's declared season/episode into TMDB's *native*
          numbering -- once a manual group is applied, ``Episode.season_
          number``/``episode_number`` are that group's own numbering, and
          rebuilding a remap against the (now-irrelevant) native structure
          would let file-matching resolve a declared season/episode to
          whatever episode happens to occupy that native (season, episode)
          pair, which is no longer the applied catalog at all.
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
        if show.active_episode_group_id is not None:
            return
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
                show.episode_groups = await fetch_episode_groups_list(self.tmdb, show.tmdb_id)
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
        Movies are excluded — TMDB has no ``/tv/{id}/season`` structure for
        them, so they would just 404 against the endpoint this method calls.

        Args:
            on_progress: Optional async callback(current, total, message).

        Returns:
            Aggregated TMDBSyncResult across all shows.
        """
        no_episodes = ~exists(select(Episode).where(Episode.show_id == Show.id))
        stmt = select(Show).where(
            Show.media_type != "movie",
            (Show.cached == False) | no_episodes,  # noqa: E712
        )
        shows = list((await self.session.execute(stmt)).scalars().all())

        total = len(shows)
        combined = TMDBSyncResult(shows_synced=0, episodes_upserted=0, episodes_skipped=0)

        for idx, show in enumerate(shows, 1):
            # Captured before any mutation/rollback below could expire it --
            # see the begin_nested() comment for why bare attribute access
            # on `show` inside an except block is otherwise unsafe.
            show_id = show.id
            if on_progress:
                await on_progress(idx, total, f"Syncing {show.title}")
            try:
                # Run each show's work in a SAVEPOINT: a failure inside only
                # rolls back to it, leaving the rest of the session's identity
                # map intact. A plain self.session.rollback() here would
                # expire every already-loaded Show in `shows`, and the next
                # iteration's bare attribute access (e.g. show.tmdb_id,
                # evaluated before any surrounding await) would then trigger
                # an implicit lazy-reload outside the async greenlet bridge —
                # raising sqlalchemy.exc.MissingGreenlet instead of the
                # original error. The SAVEPOINT rollback also expires *this*
                # show if it was mutated before the failure (e.g.
                # show.cached = True in sync_show_episodes), which is why
                # this except block logs show_id, not show.id.
                async with self.session.begin_nested():
                    result = await self.sync_show_episodes(show)
            except Exception:
                logger.exception("Failed to sync TMDB data for show id=%d", show_id)
                continue

            combined.shows_synced += result.shows_synced
            combined.episodes_upserted += result.episodes_upserted
            combined.episodes_skipped += result.episodes_skipped
            try:
                # Commit per show so a later show's failure only rolls back
                # its own partial work, not every show already synced in
                # this batch (sync_show_episodes itself only flushes). This
                # needs its own rollback on failure -- unlike the SAVEPOINT
                # above, an uncaught commit() failure leaves the session
                # unusable for every subsequent show in this loop.
                await self.session.commit()
            except Exception:
                logger.exception("Failed to commit synced TMDB data for show id=%d", show_id)
                await self.session.rollback()

        return combined
