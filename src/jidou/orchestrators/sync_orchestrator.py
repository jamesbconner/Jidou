"""Orchestrator for running the full sync pipeline."""

import logging
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators._episode_refresh import TMDBEpisodeRefresher
from jidou.orchestrators._events import EventSink
from jidou.orchestrators.download_orchestrator import DownloadOrchestrator, DownloadResult
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator, ParseResult
from jidou.orchestrators.route_orchestrator import RouteOrchestrator, RouteResult
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator, ScanResult
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator, TMDBSyncResult
from jidou.services.callbacks import OnEvent, OnProgress
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_tracking import link_file_to_episode
from jidou.services.llm_service import LLMService
from jidou.services.sftp_service import SFTPService
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

_TOTAL_PHASES = 5


def _dry_run_suffix(dry_run: bool, *, tmdb: bool = False) -> str:
    """Return the dry-run marker appended to a phase summary message.

    Args:
        dry_run: Whether this run is a dry run.
        tmdb: ``True`` for the TMDB phase, which is skipped outright in a dry run
            rather than merely simulated.

    Returns:
        The marker text, or ``""`` when this is not a dry run.
    """
    if not dry_run:
        return ""
    return " (skipped — dry run)" if tmdb else " (dry run)"


async def _tick(on_phase: OnProgress | None, current: int, message: str) -> None:
    """Report phase progress; a ``TaskCancelledError`` from the callback propagates.

    Args:
        on_phase: Optional progress callback.
        current: 1-based phase number.
        message: Human-readable phase description.
    """
    if on_phase:
        await on_phase(current, _TOTAL_PHASES, message)


async def _summary(on_event: OnEvent | None, message: str, ctx: dict[str, int]) -> None:
    """Emit one phase-summary info event; a failing callback is logged, not raised.

    Args:
        on_event: Optional event callback.
        message: Summary line.
        ctx: Structured counts for the event.
    """
    await EventSink(on_event, swallow_errors=True)("info", message, ctx)


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
        noscan_paths: SFTP paths excluded from parse/match/route — see
            ``ScanOrchestrator``.
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
        noscan_paths: list[str] | None = None,
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
        self.noscan_paths = noscan_paths or []
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
            if sid is None:
                continue  # excluded by the WHERE clause above; narrows the type for mypy
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
                ep = await resolve_episode(
                    self.session, sid, file.parsed_season, file.parsed_episode
                )

                if ep is not None:
                    # Also backfills the season so RouteOrchestrator lands in Season NN.
                    link_file_to_episode(file, ep)
                    logger.debug(
                        "Phase 4.5: resolved episode_id=%d for file id=%d (%r)",
                        ep.id,
                        file.id,
                        file.original_filename,
                    )

            # Commit per show so a rollback on a later show doesn't clobber
            # episode_id writes that already succeeded for earlier shows.
            await self.session.commit()

    async def _sync_tmdb_phase(
        self, show_id: int | None, dry_run: bool, on_event: OnEvent | None = None
    ) -> tuple[TMDBSyncResult, TMDBOrchestrator | None]:
        """Phase 1: refresh the TMDB episode cache.

        Args:
            show_id: When given, sync only this show; otherwise sync every show.
            dry_run: When ``True`` nothing is built or fetched.
            on_event: Optional event callback; used to warn when *show_id* names a
                show that does not exist.  Failures it raises are logged, not raised.

        Returns:
            ``(result, tmdb_orchestrator)``.  The orchestrator is ``None`` only
            in a dry run.  It is also returned when *show_id* names a missing or
            already-cached show (with an empty result), because the later
            episode gap-fill phase reuses it.
        """
        if dry_run:
            return TMDBSyncResult.empty(), None

        tmdb_orch = TMDBOrchestrator(self.session, self.tmdb)
        if show_id is None:
            return await tmdb_orch.sync_all_shows(), tmdb_orch

        show_stmt = select(Show).where(Show.id == show_id)
        show = (await self.session.execute(show_stmt)).scalar_one_or_none()
        if show is None:
            # Surface a mistyped or stale id instead of a silent "0 shows refreshed".
            message = f"Show id={show_id} not found; TMDB phase skipped"
            logger.warning(message)
            await EventSink(on_event, swallow_errors=True)("warn", message, {"show_id": show_id})
            return TMDBSyncResult.empty(), tmdb_orch

        ep_exists = exists(select(Episode).where(Episode.show_id == show.id))
        has_episodes = (await self.session.execute(select(ep_exists))).scalar()
        if show.cached and has_episodes:
            return TMDBSyncResult.empty(), tmdb_orch

        try:
            result = await tmdb_orch.sync_show_episodes(show)
            # sync_show_episodes only flushes; commit here so this phase's data
            # is durable regardless of what happens in the phases that follow.
            await self.session.commit()
        except Exception:
            logger.exception("Failed to sync TMDB for show id=%d", show.id)
            await self.session.rollback()
            result = TMDBSyncResult.empty()
        return result, tmdb_orch

    async def run(
        self,
        show_id: int | None = None,
        dry_run: bool = False,
        on_phase: OnProgress | None = None,
        on_event: OnEvent | None = None,
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
                Forwarded to Scan/Download/Parse/Route so each stage's
                per-item detail (not just this method's one-line phase
                summary) reaches the task log.  Errors it raises propagate.

        Returns:
            SyncResult with results from each phase.
        """
        # Phase 1: TMDB episode cache — skipped entirely in dry_run.
        await _tick(on_phase, 1, "Syncing TMDB episode data")
        tmdb_result, tmdb_orch = await self._sync_tmdb_phase(show_id, dry_run, on_event)
        await _summary(
            on_event,
            f"TMDB sync: {tmdb_result.shows_synced} shows refreshed, "
            f"{tmdb_result.episodes_upserted} episodes upserted"
            + _dry_run_suffix(dry_run, tmdb=True),
            {
                "shows_synced": tmdb_result.shows_synced,
                "episodes_upserted": tmdb_result.episodes_upserted,
            },
        )

        # Phase 2: Scan all remote paths
        await _tick(on_phase, 2, "Scanning remote files")
        scan_result = await ScanOrchestrator(
            self.session, self.sftp, self.remote_paths, self.noscan_paths
        ).run(dry_run=dry_run, on_event=on_event)
        await _summary(
            on_event,
            f"Scan: {scan_result.files_created} new file(s) discovered, "
            f"{scan_result.files_skipped} already known" + _dry_run_suffix(dry_run),
            {
                "files_created": scan_result.files_created,
                "files_skipped": scan_result.files_skipped,
            },
        )

        # Phase 3: Download DISCOVERED files to staging
        await _tick(on_phase, 3, "Downloading new files")
        dl_result = await DownloadOrchestrator(
            self.session, self.sftp, self.local_staging_path, self.remote_paths
        ).run(dry_run=dry_run, max_workers=self.sftp.max_workers, on_event=on_event)
        await _summary(
            on_event,
            f"Download: {dl_result.files_downloaded} file(s) downloaded" + _dry_run_suffix(dry_run),
            {"files_downloaded": dl_result.files_downloaded},
        )

        # Phase 4: Parse filenames and match to shows
        await _tick(on_phase, 4, "Parsing and matching files to shows")
        parse_result = await ParseOrchestrator(
            self.session,
            self.llm,
            local_tv_path=self.local_tv_path,
            local_anime_path=self.local_anime_path,
            local_movie_path=self.local_movie_path,
            episode_refresher=TMDBEpisodeRefresher(self.session, self.tmdb),
        ).run(dry_run=dry_run, on_event=on_event)
        await _summary(
            on_event,
            f"Parse: {parse_result.files_matched} file(s) matched to shows"
            + _dry_run_suffix(dry_run),
            {"files_matched": parse_result.files_matched},
        )

        # Phase 4.5: Episode gap fill — re-sync TMDB for shows where the parser
        # matched a show but couldn't resolve an episode row.  This handles
        # already-cached shows whose DB episode list is stale (new seasons/
        # episodes released since the last sync).  Only triggered when there are
        # MATCHED files with a known (season, episode) but no episode_id.
        if not dry_run and tmdb_orch is not None:
            await self._fill_missing_episodes(tmdb_orch)

        # Phase 5: Route MATCHED files to final local paths
        await _tick(on_phase, 5, "Routing matched files")
        route_result = await RouteOrchestrator(self.session).run(dry_run=dry_run, on_event=on_event)
        await _summary(
            on_event,
            f"Route: {route_result.files_routed} file(s) routed to final paths"
            + _dry_run_suffix(dry_run),
            {"files_routed": route_result.files_routed},
        )

        return SyncResult(
            tmdb=tmdb_result,
            scan=scan_result,
            download=dl_result,
            parse=parse_result,
            route=route_result,
        )
