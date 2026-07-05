"""Orchestrator for running the full sync pipeline."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators.download_orchestrator import DownloadOrchestrator, DownloadResult
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator, ParseResult
from jidou.orchestrators.route_orchestrator import RouteOrchestrator, RouteResult
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator, ScanResult
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator, TMDBSyncResult
from jidou.services.llm_service import LLMService
from jidou.services.sftp_service import SFTPService
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

_TOTAL_PHASES = 5


@dataclass
class SyncResult:
    """Result of a full sync pipeline run."""

    tmdb: TMDBSyncResult
    scan: ScanResult
    download: DownloadResult
    parse: ParseResult
    route: RouteResult


class SyncOrchestrator:
    """Run the full pipeline: TMDB sync → Scan → Download → Parse → Route.

    Args:
        session: Active async SQLAlchemy session.
        sftp: Configured SFTPService instance.
        tmdb: Configured TMDBService instance.
        llm: Optional LLMService for parse/match.
        remote_paths: SFTP remote paths to scan.
        local_staging_path: Local directory for staging downloaded files.
        local_tv_path: Base directory for live-action TV series.
        local_anime_path: Base directory for anime series.
        local_movie_path: Base directory for movies.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        tmdb: TMDBService,
        llm: LLMService | None = None,
        remote_paths: list[str] | None = None,
        local_staging_path: str = "/data/staging",
        local_tv_path: str = "/data/media/tv",
        local_anime_path: str = "/data/media/anime",
        local_movie_path: str = "/data/media/movies",
    ) -> None:
        self.session = session
        self.sftp = sftp
        self.tmdb = tmdb
        self.llm = llm
        self.remote_paths = remote_paths or ["/"]
        self.local_staging_path = local_staging_path
        self.local_tv_path = local_tv_path
        self.local_anime_path = local_anime_path
        self.local_movie_path = local_movie_path

    async def _fill_missing_episodes(self, tmdb_orch: TMDBOrchestrator) -> None:
        """Re-sync TMDB for shows whose MATCHED files have no resolved episode_id.

        Runs after ParseOrchestrator.  For each show that has MATCHED files
        with (parsed_season, parsed_episode) set but episode_id=None, force a
        full TMDB episode refresh then retry the episode lookup — writing
        episode_id back onto the file so RouteOrchestrator can track it.

        This fixes the stale-cache case: shows marked cached=True in Phase 1
        are skipped by sync_all_shows, so new seasons/episodes don't reach the
        DB until this phase catches them.

        Args:
            tmdb_orch: Already-constructed TMDB orchestrator sharing this session.
        """
        # Find distinct show_ids that need help — includes anime (parsed_season=None).
        gap_stmt = (
            select(DownloadedFile.show_id)
            .distinct()
            .where(
                DownloadedFile.status == FileStatus.MATCHED,
                DownloadedFile.episode_id.is_(None),
                DownloadedFile.parsed_episode.is_not(None),
                DownloadedFile.show_id.is_not(None),
            )
        )
        show_ids = list((await self.session.execute(gap_stmt)).scalars().all())

        if not show_ids:
            return

        logger.info(
            "Phase 4.5: re-syncing TMDB for %d show(s) with unresolved episode rows",
            len(show_ids),
        )

        for sid in show_ids:
            show_stmt = select(Show).where(Show.id == sid)
            show = (await self.session.execute(show_stmt)).scalar_one_or_none()
            if show is None:
                continue
            try:
                await tmdb_orch.sync_show_episodes(show)
            except Exception:
                logger.exception("Phase 4.5: TMDB re-sync failed for show id=%d", sid)
                await self.session.rollback()
                continue

            # Retry episode lookup for the affected files (anime or regular).
            retry_stmt = select(DownloadedFile).where(
                DownloadedFile.status == FileStatus.MATCHED,
                DownloadedFile.episode_id.is_(None),
                DownloadedFile.show_id == sid,
                DownloadedFile.parsed_episode.is_not(None),
            )
            files = list((await self.session.execute(retry_stmt)).scalars().all())
            for file in files:
                if file.parsed_season is not None:
                    ep_stmt = select(Episode).where(
                        Episode.show_id == sid,
                        Episode.season_number == file.parsed_season,
                        Episode.episode_number == file.parsed_episode,
                    )
                    ep = (await self.session.execute(ep_stmt)).scalar_one_or_none()
                else:
                    # Anime absolute-number fallback: try absolute first, then Season 1.
                    ep_stmt = select(Episode).where(
                        Episode.show_id == sid,
                        Episode.absolute_episode_number == file.parsed_episode,
                    )
                    ep = (await self.session.execute(ep_stmt)).scalar_one_or_none()
                    if ep is None:
                        ep_stmt = select(Episode).where(
                            Episode.show_id == sid,
                            Episode.season_number == 1,
                            Episode.episode_number == file.parsed_episode,
                        )
                        ep = (await self.session.execute(ep_stmt)).scalar_one_or_none()

                if ep is not None:
                    file.episode_id = ep.id
                    if file.parsed_season is None and ep.season_number is not None:
                        # Backfill so RouteOrchestrator lands in Season NN, not show root.
                        file.parsed_season = ep.season_number
                    logger.debug(
                        "Phase 4.5: resolved episode_id=%d for file id=%d (%r)",
                        ep.id,
                        file.id,
                        file.original_filename,
                    )

            # Commit per show so a rollback on a later show doesn't clobber
            # episode_id writes that already succeeded for earlier shows.
            await self.session.commit()

    async def run(
        self,
        show_id: int | None = None,
        dry_run: bool = False,
        on_phase: Callable[[int, int, str], Awaitable[None]] | None = None,
        on_event: Callable[[str, str, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> SyncResult:
        """Execute all 5 phases in order, reporting phase-level progress.

        Args:
            show_id: When given, limit the TMDB sync to one show.
                     Scan/download/parse/route are always global.
            dry_run: Passed through to each orchestrator.
            on_phase: Optional async callback(current_phase, total_phases, message).
                May raise TaskCancelledError; propagates uncaught.
            on_event: Optional async callback(level, message, ctx) for structured
                event log entries — wired to append_task_event in the task layer.

        Returns:
            SyncResult with results from each phase.
        """
        # Phase 1: TMDB episode cache — skipped entirely in dry_run.
        if on_phase:
            await on_phase(1, _TOTAL_PHASES, "Syncing TMDB episode data")
        _tmdb_orch: TMDBOrchestrator | None = None
        if dry_run:
            tmdb_result = TMDBSyncResult(shows_synced=0, episodes_upserted=0, episodes_skipped=0)
        else:
            _tmdb_orch = TMDBOrchestrator(self.session, self.tmdb)
            if show_id is not None:
                show_stmt = select(Show).where(Show.id == show_id)
                show = (await self.session.execute(show_stmt)).scalar_one_or_none()
                if show is not None:
                    ep_exists = exists(select(Episode).where(Episode.show_id == show.id))
                    has_episodes = (await self.session.execute(select(ep_exists))).scalar()
                    if not show.cached or not has_episodes:
                        try:
                            tmdb_result = await _tmdb_orch.sync_show_episodes(show)
                        except Exception:
                            logger.exception("Failed to sync TMDB for show id=%d", show.id)
                            await self.session.rollback()
                            tmdb_result = TMDBSyncResult(
                                shows_synced=0, episodes_upserted=0, episodes_skipped=0
                            )
                    else:
                        tmdb_result = TMDBSyncResult(
                            shows_synced=0, episodes_upserted=0, episodes_skipped=0
                        )
                else:
                    tmdb_result = TMDBSyncResult(
                        shows_synced=0, episodes_upserted=0, episodes_skipped=0
                    )
            else:
                tmdb_result = await _tmdb_orch.sync_all_shows()
        if on_event:
            await on_event(
                "info",
                f"TMDB sync: {tmdb_result.shows_synced} shows refreshed, "
                f"{tmdb_result.episodes_upserted} episodes upserted"
                + (" (skipped — dry run)" if dry_run else ""),
                {
                    "shows_synced": tmdb_result.shows_synced,
                    "episodes_upserted": tmdb_result.episodes_upserted,
                },
            )

        # Phase 2: Scan all remote paths
        if on_phase:
            await on_phase(2, _TOTAL_PHASES, "Scanning remote files")
        scan_result = await ScanOrchestrator(self.session, self.sftp, self.remote_paths).run(
            dry_run=dry_run
        )
        if on_event:
            await on_event(
                "info",
                f"Scan: {scan_result.files_created} new file(s) discovered"
                + (" (dry run)" if dry_run else ""),
                {"files_created": scan_result.files_created},
            )

        # Phase 3: Download DISCOVERED files to staging
        if on_phase:
            await on_phase(3, _TOTAL_PHASES, "Downloading new files")
        dl_result = await DownloadOrchestrator(
            self.session, self.sftp, self.local_staging_path
        ).run(dry_run=dry_run, max_workers=self.sftp.max_workers)
        if on_event:
            await on_event(
                "info",
                f"Download: {dl_result.files_downloaded} file(s) downloaded"
                + (" (dry run)" if dry_run else ""),
                {"files_downloaded": dl_result.files_downloaded},
            )

        # Phase 4: Parse filenames and match to shows
        if on_phase:
            await on_phase(4, _TOTAL_PHASES, "Parsing and matching files to shows")
        parse_result = await ParseOrchestrator(
            self.session,
            self.llm,
            local_tv_path=self.local_tv_path,
            local_anime_path=self.local_anime_path,
            local_movie_path=self.local_movie_path,
        ).run(dry_run=dry_run)
        if on_event:
            await on_event(
                "info",
                f"Parse: {parse_result.files_matched} file(s) matched to shows"
                + (" (dry run)" if dry_run else ""),
                {"files_matched": parse_result.files_matched},
            )

        # Phase 4.5: Episode gap fill — re-sync TMDB for shows where the parser
        # matched a show but couldn't resolve an episode row.  This handles
        # already-cached shows whose DB episode list is stale (new seasons/
        # episodes released since the last sync).  Only triggered when there are
        # MATCHED files with a known (season, episode) but no episode_id.
        if not dry_run and _tmdb_orch is not None:
            await self._fill_missing_episodes(_tmdb_orch)

        # Phase 5: Route MATCHED files to final local paths
        if on_phase:
            await on_phase(5, _TOTAL_PHASES, "Routing matched files")
        route_result = await RouteOrchestrator(self.session).run(dry_run=dry_run, on_event=on_event)
        if on_event:
            await on_event(
                "info",
                f"Route: {route_result.files_routed} file(s) routed to final paths"
                + (" (dry run)" if dry_run else ""),
                {"files_routed": route_result.files_routed},
            )

        return SyncResult(
            tmdb=tmdb_result,
            scan=scan_result,
            download=dl_result,
            parse=parse_result,
            route=route_result,
        )
