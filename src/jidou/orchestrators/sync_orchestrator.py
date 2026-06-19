"""Orchestrator for running the full sync pipeline."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show
from jidou.orchestrators.download_orchestrator import DownloadOrchestrator, DownloadResult
from jidou.orchestrators.match_orchestrator import MatchOrchestrator, MatchResult
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator, ScanResult
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator, TMDBSyncResult
from jidou.services.llm_service import LLMService
from jidou.services.sftp_service import SFTPService
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a full sync pipeline run."""

    tmdb: TMDBSyncResult
    scan: ScanResult
    download: DownloadResult
    match: MatchResult


class SyncOrchestrator:
    """Run the full pipeline: TMDB sync → Scan → Download → Match.

    Args:
        session: Active async SQLAlchemy session.
        sftp: Configured SFTPService instance.
        tmdb: Configured TMDBService instance.
        llm: Optional LLMService for match fallback.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        tmdb: TMDBService,
        llm: LLMService | None = None,
    ) -> None:
        self.session = session
        self.sftp = sftp
        self.tmdb = tmdb
        self.llm = llm

    async def run(
        self,
        show_id: int | None = None,
        dry_run: bool = False,
        on_phase: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> SyncResult:
        """Execute all 4 phases in order, reporting phase-level progress.

        Args:
            show_id: Limit to one show. None syncs all shows.
            dry_run: Passed through to each orchestrator.
            on_phase: Optional async callback(current_phase, total_phases, message).
                May raise TaskCancelledError; propagates uncaught.

        Returns:
            SyncResult with results from each phase.
        """
        # Phase 1: TMDB episode cache
        if on_phase:
            await on_phase(1, 4, "Syncing TMDB episode data")
        tmdb_orch = TMDBOrchestrator(self.session, self.tmdb)
        if show_id is not None:
            show_stmt = select(Show).where(Show.id == show_id)
            show = (await self.session.execute(show_stmt)).scalar_one_or_none()
            if show is not None and not show.cached:
                tmdb_result = await tmdb_orch.sync_show_episodes(show)
            else:
                tmdb_result = TMDBSyncResult(
                    shows_synced=0, episodes_upserted=0, episodes_skipped=0
                )
        else:
            tmdb_result = await tmdb_orch.sync_all_shows()

        # Phase 2: Scan
        if on_phase:
            await on_phase(2, 4, "Scanning remote files")
        scan_result = await ScanOrchestrator(self.session, self.sftp).run(
            show_id=show_id, dry_run=dry_run
        )

        # Phase 3: Download
        if on_phase:
            await on_phase(3, 4, "Downloading new files")
        dl_result = await DownloadOrchestrator(self.session, self.sftp).run(
            show_id=show_id, dry_run=dry_run
        )

        # Phase 4: Match
        if on_phase:
            await on_phase(4, 4, "Matching files to episodes")
        match_result = await MatchOrchestrator(self.session, self.llm).run(
            show_id=show_id, dry_run=dry_run
        )

        return SyncResult(
            tmdb=tmdb_result, scan=scan_result, download=dl_result, match=match_result
        )
