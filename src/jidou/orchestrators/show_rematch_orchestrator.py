"""Orchestrator for re-matching a show to a different TMDB entry."""

import logging
import re
from datetime import datetime
from typing import Any, TypedDict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.show import Show
from jidou.schemas.show_schema import RematchRequest
from jidou.services.episode_tracking import mark_episode_tracked
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


class TrackingSnapshot(TypedDict):
    """Tracking state captured from an Episode before the rematch bulk-delete."""

    tracked_filename: str | None
    tracked_source: str | None
    file_tracked_at: datetime | None


class ShowRematchOrchestrator:
    """Orchestrate re-matching a show to a different TMDB entry.

    Decomposes the operation into discrete, independently testable phases:

    1. Fetch updated TMDB metadata.
    2. Apply metadata to the Show row.
    3. Snapshot current episode tracking state.
    4. Purge old episodes and stale orphan records.
    5. Sync fresh episodes from TMDB (TV only).
    6. Restore tracking state and re-link DownloadedFile rows (TV + preserve_tracking only).

    Args:
        session: Active async SQLAlchemy session.
        tmdb: TMDB service instance.
    """

    def __init__(self, session: AsyncSession, tmdb: TMDBService) -> None:
        self.session = session
        self.tmdb = tmdb

    async def rematch(self, show: Show, payload: RematchRequest) -> Show:
        """Execute the full rematch pipeline and return the updated Show.

        Args:
            show: The Show ORM object to re-match.
            payload: Rematch request containing the new tmdb_id and options.

        Returns:
            The updated Show record.

        Raises:
            HTTPException: 502 if TMDB details or episode sync fails.
        """
        data = await self._fetch_tmdb_details(payload)
        self._apply_tmdb_metadata(show, payload, data)

        old_tracking = await self._snapshot_tracking(show.id, payload)

        await self._purge_episodes(show.id)

        if payload.media_type != "movie":
            await self._sync_new_episodes(show)

            if payload.preserve_tracking:
                await self._restore_tracking_and_relink(show.id, old_tracking)

        await self.session.refresh(show)
        return show

    async def _fetch_tmdb_details(self, payload: RematchRequest) -> dict[str, Any]:
        """Fetch show details from TMDB for the target tmdb_id.

        Args:
            payload: Rematch request with tmdb_id and media_type.

        Returns:
            Raw TMDB detail dict.

        Raises:
            HTTPException: 502 on any TMDB error.
        """
        try:
            return await self.tmdb.get_details(payload.tmdb_id, media_type=payload.media_type)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Failed to fetch TMDB details") from exc

    def _apply_tmdb_metadata(
        self, show: Show, payload: RematchRequest, data: dict[str, Any]
    ) -> None:
        """Update all TMDB-sourced fields on *show*; preserve user-managed ones.

        Args:
            show: Show ORM object to mutate in place.
            payload: Rematch request (provides tmdb_id and media_type).
            data: Raw TMDB detail response.
        """
        # TV uses "name" + "first_air_date"; movies use "title" + "release_date".
        title: str = data.get("name") or data.get("title") or show.title
        release_date: str | None = data.get("first_air_date") or data.get("release_date")
        ep_runtimes: list[int] = data.get("episode_run_time") or []

        show.tmdb_id = payload.tmdb_id
        show.media_type = payload.media_type
        show.title = title
        show.overview = data.get("overview")
        show.poster_path = data.get("poster_path")
        show.backdrop_path = data.get("backdrop_path")
        show.vote_average = data.get("vote_average")
        show.vote_count = data.get("vote_count", 0)
        show.release_date = release_date
        show.original_language = data.get("original_language")
        show.sys_name = _INVALID_FS_CHARS.sub("_", title).strip()
        show.genres = data.get("genres") or []
        # TV uses origin_country (ISO list); movies use production_countries (objects).
        tv_countries: list[str] = data.get("origin_country") or []
        movie_countries: list[str] = [
            c["iso_3166_1"] for c in (data.get("production_countries") or []) if "iso_3166_1" in c
        ]
        show.origin_country = tv_countries or movie_countries
        show.last_air_date = data.get("last_air_date")
        show.last_episode_to_air = data.get("last_episode_to_air")
        show.next_episode_to_air = data.get("next_episode_to_air")
        show.homepage = data.get("homepage")
        show.status = data.get("status")
        show.in_production = data.get("in_production")
        show.number_of_seasons = data.get("number_of_seasons")
        show.number_of_episodes = data.get("number_of_episodes")
        show.networks = data.get("networks") or []
        show.show_type = data.get("type")
        show.runtime = data.get("runtime") or (ep_runtimes[0] if ep_runtimes else None)
        show.tagline = data.get("tagline")
        show.external_ids = data.get("external_ids")
        show.episode_groups = data.get("episode_groups") or []

    async def _snapshot_tracking(
        self,
        show_id: int,
        payload: RematchRequest,
    ) -> dict[tuple[int, int], TrackingSnapshot]:
        """Capture tracking state of all tracked episodes before the bulk delete.

        Args:
            show_id: DB primary key of the show.
            payload: Rematch request; snapshot is skipped for movies or when
                preserve_tracking is False.

        Returns:
            Mapping of (season, episode) → TrackingSnapshot for each tracked episode,
            or an empty dict when snapshotting is not applicable.
        """
        if not payload.preserve_tracking or payload.media_type == "movie":
            return {}

        stmt = select(Episode).where(
            Episode.show_id == show_id,
            Episode.file_tracked.is_(True),
        )
        tracked_eps = (await self.session.execute(stmt)).scalars().all()
        snapshot: dict[tuple[int, int], TrackingSnapshot] = {
            (ep.season_number, ep.episode_number): TrackingSnapshot(
                tracked_filename=ep.tracked_filename,
                tracked_source=ep.tracked_source,
                file_tracked_at=ep.file_tracked_at,
            )
            for ep in tracked_eps
        }
        logger.debug(
            "Tracking snapshot: show id=%d captured %d tracked episode(s)",
            show_id,
            len(snapshot),
        )
        return snapshot

    async def _purge_episodes(self, show_id: int) -> None:
        """Delete all episodes and stale orphan records for *show_id*.

        Args:
            show_id: DB primary key of the show whose episodes should be purged.
        """
        await self.session.execute(
            Episode.__table__.delete().where(  # type: ignore[attr-defined]
                Episode.show_id == show_id
            )
        )
        await self.session.flush()

        # Always purge stale orphan rows regardless of media_type so that rematching
        # a TV show as a movie (or repeated rematches) never leaves ghost DQ entries.
        await self.session.execute(
            OrphanedTrackingRecord.__table__.delete().where(  # type: ignore[attr-defined]
                OrphanedTrackingRecord.show_id == show_id
            )
        )

    async def _sync_new_episodes(self, show: Show) -> None:
        """Sync fresh episodes from TMDB for *show*.

        Args:
            show: Show ORM object whose episodes should be populated.

        Raises:
            HTTPException: 502 if the TMDB episode sync fails.
        """
        from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator

        try:
            await TMDBOrchestrator(self.session, self.tmdb).sync_show_episodes(show)
        except Exception as exc:
            logger.exception("Episode sync failed after rematch for show id=%d", show.id)
            raise HTTPException(
                status_code=502, detail="TMDB episode sync failed; rematch aborted"
            ) from exc

        logger.info(
            "Re-matched show id=%d → tmdb_id=%d title=%r", show.id, show.tmdb_id, show.title
        )

    async def _restore_tracking_and_relink(
        self,
        show_id: int,
        old_tracking: dict[tuple[int, int], TrackingSnapshot],
    ) -> None:
        """Restore episode tracking and re-link DownloadedFile rows after sync.

        Phase 2 — restore tracking flags on new episodes that match a
        (season, episode) key from the snapshot.

        Phase 3 — re-link DownloadedFile rows whose episode_id was SET NULL
        by cascade delete.  Files with no matching new episode are persisted
        as OrphanedTrackingRecord rows.

        Args:
            show_id: DB primary key of the show.
            old_tracking: Snapshot from :meth:`_snapshot_tracking`.
        """
        new_eps_stmt = select(Episode).where(Episode.show_id == show_id)
        new_eps = (await self.session.execute(new_eps_stmt)).scalars().all()
        ep_by_se: dict[tuple[int, int], Episode] = {
            (e.season_number, e.episode_number): e for e in new_eps
        }

        # Phase 2: restore tracking
        migrated = 0
        for key, state in old_tracking.items():
            matched_ep = ep_by_se.get(key)
            if matched_ep is not None:
                mark_episode_tracked(
                    matched_ep,
                    state["tracked_filename"],
                    state["tracked_source"],
                    tracked_at=state["file_tracked_at"],
                )
                migrated += 1

        # Phase 3: re-link orphaned DownloadedFile rows
        orphan_stmt = select(DownloadedFile).where(
            DownloadedFile.show_id == show_id,
            DownloadedFile.episode_id.is_(None),
            DownloadedFile.parsed_season.is_not(None),
            DownloadedFile.parsed_episode.is_not(None),
        )
        orphaned_files = (await self.session.execute(orphan_stmt)).scalars().all()
        relinked = 0
        orphan_records_created = 0
        # Track which (season, episode) keys Phase 3 already persisted as orphans
        # so the unrecoverable_keys loop below skips them and avoids duplicates.
        phase3_orphan_keys: set[tuple[int, int]] = set()
        for file in orphaned_files:
            if file.parsed_season is not None and file.parsed_episode is not None:
                new_ep = ep_by_se.get((file.parsed_season, file.parsed_episode))
                if new_ep is not None:
                    file.episode_id = new_ep.id
                    relinked += 1
                else:
                    self.session.add(
                        OrphanedTrackingRecord(
                            show_id=show_id,
                            tracked_filename=file.local_path or file.original_filename,
                            tracked_source="match",
                            old_season_number=file.parsed_season,
                            old_episode_number=file.parsed_episode,
                            downloaded_file_id=file.id,
                        )
                    )
                    phase3_orphan_keys.add((file.parsed_season, file.parsed_episode))
                    orphan_records_created += 1

        unrecoverable_keys = set(old_tracking.keys()) - set(ep_by_se.keys())
        for key in unrecoverable_keys:
            if key in phase3_orphan_keys:
                continue
            state = old_tracking[key]
            self.session.add(
                OrphanedTrackingRecord(
                    show_id=show_id,
                    tracked_filename=state["tracked_filename"],
                    tracked_source=state["tracked_source"] or "match",
                    old_season_number=key[0],
                    old_episode_number=key[1],
                    downloaded_file_id=None,
                )
            )
            orphan_records_created += 1

        if unrecoverable_keys:
            logger.warning(
                "Unrecoverable tracking records after rematch of show id=%d: %d persisted",
                show_id,
                orphan_records_created,
            )

        logger.info(
            "Tracking migration: show id=%d migrated=%d relinked=%d orphans_created=%d",
            show_id,
            migrated,
            relinked,
            orphan_records_created,
        )

        await self.session.flush()
