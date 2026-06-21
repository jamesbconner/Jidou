"""Orchestrator for running the full sync pipeline."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        tmdb: TMDBService,
        llm: LLMService | None = None,
        remote_paths: list[str] | None = None,
        local_staging_path: str = "/data/staging",
    ) -> None:
        self.session = session
        self.sftp = sftp
        self.tmdb = tmdb
        self.llm = llm
        self.remote_paths = remote_paths or ["/"]
        self.local_staging_path = local_staging_path

    async def run(
        self,
        show_id: int | None = None,
        dry_run: bool = False,
        on_phase: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> SyncResult:
        """Execute all 5 phases in order, reporting phase-level progress.

        Args:
            show_id: When given, limit the TMDB sync to one show.
                     Scan/download/parse/route are always global.
            dry_run: Passed through to each orchestrator.
            on_phase: Optional async callback(current_phase, total_phases, message).
                May raise TaskCancelledError; propagates uncaught.

        Returns:
            SyncResult with results from each phase.
        """
        # Phase 1: TMDB episode cache — skipped entirely in dry_run.
        if on_phase:
            await on_phase(1, _TOTAL_PHASES, "Syncing TMDB episode data")
        if dry_run:
            tmdb_result = TMDBSyncResult(shows_synced=0, episodes_upserted=0, episodes_skipped=0)
        else:
            tmdb_orch = TMDBOrchestrator(self.session, self.tmdb)
            if show_id is not None:
                show_stmt = select(Show).where(Show.id == show_id)
                show = (await self.session.execute(show_stmt)).scalar_one_or_none()
                if show is not None:
                    ep_exists = exists(select(Episode).where(Episode.show_id == show.id))
                    has_episodes = (await self.session.execute(select(ep_exists))).scalar()
                    if not show.cached or not has_episodes:
                        try:
                            tmdb_result = await tmdb_orch.sync_show_episodes(show)
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
                tmdb_result = await tmdb_orch.sync_all_shows()

        # Phase 2: Scan all remote paths
        if on_phase:
            await on_phase(2, _TOTAL_PHASES, "Scanning remote files")
        scan_result = await ScanOrchestrator(self.session, self.sftp, self.remote_paths).run(
            dry_run=dry_run
        )

        # Phase 3: Download DISCOVERED files to staging
        if on_phase:
            await on_phase(3, _TOTAL_PHASES, "Downloading new files")
        dl_result = await DownloadOrchestrator(
            self.session, self.sftp, self.local_staging_path
        ).run(dry_run=dry_run, max_workers=self.sftp.max_workers)

        # Phase 4: Parse filenames and match to shows
        if on_phase:
            await on_phase(4, _TOTAL_PHASES, "Parsing and matching files to shows")
        parse_result = await ParseOrchestrator(self.session, self.llm).run(dry_run=dry_run)

        # Phase 5: Route MATCHED files to final local paths
        if on_phase:
            await on_phase(5, _TOTAL_PHASES, "Routing matched files")
        route_result = await RouteOrchestrator(self.session).run(dry_run=dry_run)

        return SyncResult(
            tmdb=tmdb_result,
            scan=scan_result,
            download=dl_result,
            parse=parse_result,
            route=route_result,
        )
