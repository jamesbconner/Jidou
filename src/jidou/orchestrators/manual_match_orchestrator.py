"""Orchestrator for manually matching a downloaded file to a show/episode."""

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.schemas.file_schema import FileMatchRequest
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_tracking import (
    clear_if_unreferenced,
    dismiss_orphans_for_file,
    mark_episode_tracked,
)
from jidou.services.filename_parser import heuristic_se
from jidou.services.llm_service import LLMService
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata

logger = logging.getLogger(__name__)


class ManualMatchOrchestrator:
    """Orchestrate assigning a show to an unmatched file, or resetting it.

    Three modes controlled by the request payload:

    * ``show_id`` supplied: assign an existing tracked show directly.
    * ``tmdb_id`` supplied: look up or create the show on demand from TMDB,
      then assign.  ``local_path`` is required when creating a new show.
    * Neither supplied: reset the file to ``downloaded`` for automatic
      re-processing by the parse pipeline.

    Args:
        session: Active async SQLAlchemy session.
        llm: Optional LLM service, used for alias generation on newly
            created shows.
    """

    def __init__(self, session: AsyncSession, llm: LLMService | None = None) -> None:
        self.session = session
        self.llm = llm

    async def match(self, file: DownloadedFile, payload: FileMatchRequest) -> DownloadedFile:
        """Execute the manual-match pipeline and return the updated file.

        Args:
            file: The DownloadedFile ORM object to match (already looked up
                and status-validated by the caller).
            payload: Match request; see :class:`FileMatchRequest` for fields.

        Returns:
            The updated DownloadedFile record.

        Raises:
            HTTPException: 404 if the referenced show or TMDB resource is
                not found.
            HTTPException: 422 if the resolved show has no ``local_path``.
        """
        if payload.show_id is None and payload.tmdb_id is None:
            return await self._reset(file)

        if payload.tmdb_id is not None:
            show = await self._resolve_show_by_tmdb_id(payload)
        else:
            show = await self._resolve_show_by_id(payload)

        if show.local_path is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Show has no local_path configured; "
                    "provide local_path or set it via PATCH /shows/{id}/paths"
                ),
            )

        await self._assign(file, show)
        return file

    async def _reset(self, file: DownloadedFile) -> DownloadedFile:
        """Clear a file's match state and queue it for automatic re-matching.

        Args:
            file: The DownloadedFile to reset.

        Returns:
            The updated DownloadedFile record.
        """
        file.status = FileStatus.DOWNLOADED
        file.show_id = None
        file.episode_id = None
        file.matched_by = None
        file.error_message = None
        await self.session.flush()
        await self.session.refresh(file)
        await self.session.commit()
        logger.info("Reset file id=%d to downloaded for auto re-matching", file.id)
        return file

    async def _resolve_show_by_id(self, payload: FileMatchRequest) -> Show:
        """Look up an existing show by ``payload.show_id``.

        Args:
            payload: Match request with ``show_id`` set.

        Returns:
            The matching Show record.

        Raises:
            HTTPException: 404 if no show has that ID.
        """
        show_stmt = select(Show).where(Show.id == payload.show_id)
        show = (await self.session.execute(show_stmt)).scalar_one_or_none()
        if show is None:
            raise HTTPException(status_code=404, detail="Show not found")
        return show

    async def _resolve_show_by_tmdb_id(self, payload: FileMatchRequest) -> Show:
        """Find or create a show for ``payload.tmdb_id``.

        Args:
            payload: Match request with ``tmdb_id`` set.

        Returns:
            The existing or newly created Show record.

        Raises:
            HTTPException: 422 if creating a new show and ``local_path`` is absent.
            HTTPException: 404 if the TMDB lookup fails.
        """
        if payload.tmdb_id is None:
            raise ValueError("_resolve_show_by_tmdb_id requires payload.tmdb_id to be set")

        # Check DB first (idempotent)
        show_stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
        show = (await self.session.execute(show_stmt)).scalar_one_or_none()

        if show is not None:
            # Show exists — only fill in local_path / content_type if not already set.
            # Never silently overwrite a configured path; the user should explicitly
            # update it via the show detail page if they want to change it.
            if payload.local_path and not show.local_path:
                show.local_path = payload.local_path
            if payload.content_type and not show.content_type:
                show.content_type = payload.content_type
            await self.session.flush()
            await TMDBOrchestrator(self.session, TMDBService()).ensure_episode_group_map(show)
            return show

        if not payload.local_path:
            raise HTTPException(
                status_code=422,
                detail="local_path is required when creating a new show via tmdb_id",
            )

        tmdb = TMDBService()
        # Use the TMDB-reported media_type from the search result (tv/movie).
        # Fall back to inferring from content_type only when not provided.
        media_type = payload.tmdb_media_type or (
            "movie" if payload.content_type == "movie" else "tv"
        )
        try:
            data = await fetch_show_metadata(tmdb, payload.tmdb_id, media_type)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"TMDB lookup failed: {exc}") from exc

        fields = build_show_fields(data, payload.tmdb_id, media_type)
        show = Show(
            **fields,
            content_type=payload.content_type,
            local_path=payload.local_path,
            cached=False,
        )
        self.session.add(show)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            show_stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
            show = (await self.session.execute(show_stmt)).scalar_one_or_none()
            if show is None:
                raise
            # Apply caller's path/type only if the concurrently-created row
            # doesn't already have values — never overwrite existing config.
            if payload.local_path and not show.local_path:
                show.local_path = payload.local_path
            if payload.content_type and not show.content_type:
                show.content_type = payload.content_type
            await self.session.flush()
        else:
            logger.info(
                "Created show tmdb_id=%d title=%r (id=%d) via on-demand match",
                show.tmdb_id,
                show.title,
                show.id,
            )

        # Sync episodes immediately so the episode lookup below has data to
        # work with.  Mirrors the inline sync in POST /shows.  Failures are
        # non-fatal — episodes will arrive on the next pipeline run.
        if show.media_type != "movie":
            try:
                await TMDBOrchestrator(self.session, tmdb).sync_show_episodes(show)
                logger.info(
                    "Synced episodes for show id=%d tmdb_id=%d via manual match",
                    show.id,
                    show.tmdb_id,
                )
            except SQLAlchemyError:
                # DB failure during sync's internal flush leaves the
                # session's transaction in a broken state; propagate so
                # the caller gets a 500 rather than silently issuing more
                # queries against a dead transaction (mirrors the same
                # guard in POST /shows).
                raise
            except Exception:
                logger.warning(
                    "Episode sync failed for show id=%d; episodes will sync on next pipeline run",
                    show.id,
                    exc_info=True,
                )

        # Commit the show (and any synced episodes) now, independent of
        # alias generation below. sync_show_episodes only flushes, so
        # without this commit a later DB-level failure in alias
        # generation would roll back an already-successful sync too --
        # both steps are meant to be independently best-effort.
        await self.session.commit()

        # Generate TMDB alternative-title aliases and LLM aliases so the
        # show is immediately searchable under all its known names.
        # Mirrors the inline alias generation in POST /shows.
        try:
            from jidou.orchestrators.alias_orchestrator import generate_aliases

            await generate_aliases(show, tmdb, llm=self.llm)
            await self.session.flush()
            logger.info(
                "Generated aliases for show id=%d tmdb_id=%d via manual match",
                show.id,
                show.tmdb_id,
            )
        except SQLAlchemyError:
            raise
        except Exception:
            logger.warning(
                "Alias generation failed for show id=%d; "
                "aliases can be regenerated via the Manage Aliases modal",
                show.id,
                exc_info=True,
            )

        return show

    async def _assign(self, file: DownloadedFile, show: Show) -> None:
        """Assign *file* to *show*, resolve its episode, and clean up tracking.

        Args:
            file: The DownloadedFile to assign (mutated in place).
            show: The resolved Show to assign the file to.
        """
        # Capture the previously linked episode before clearing it.  We always
        # capture regardless of whether the show changes so that same-show
        # different-episode rematch also clears stale tracking.
        # (Cancelling the re-match modal never calls this endpoint, so the old
        # episode stays tracked until the user explicitly confirms.)
        old_episode_id: int | None = file.episode_id

        file.show_id = show.id
        file.episode_id = None  # cleared here; route task resolves and writes new ep
        file.matched_by = MatchedBy.MANUAL
        file.status = FileStatus.MATCHED
        file.error_message = None

        # Populate parsed_season / parsed_episode from the filename heuristic when
        # neither is known yet (i.e. the file was never processed by the LLM pipeline).
        # Run BEFORE stale-episode clearing so we know the new episode_id and can
        # skip the clear when the file stays on the same episode.
        if file.parsed_season is None and file.parsed_episode is None:
            se = heuristic_se(file.original_filename)
            if se is not None:
                file.parsed_season, file.parsed_episode = se

        # Resolve episode_id from whatever season/episode info we now have.
        # Handles three cases:
        #   1. Regular TV: season + episode both known → exact match.
        #   2. Anime (season=None, episode=N): absolute_episode_number, then Season-1 fallback.
        #   3. No episode info at all: skip; route task will resolve later.
        ep: Episode | None = None
        if file.parsed_episode is not None:
            had_no_season = file.parsed_season is None
            ep = await resolve_episode(
                self.session, show.id, file.parsed_season, file.parsed_episode
            )
            if had_no_season and ep is not None and ep.season_number is not None:
                file.parsed_season = ep.season_number  # enables Season NN routing

            if ep is not None:
                file.episode_id = ep.id
                # Only dismiss the orphan once an episode is confirmed; keeping it
                # when episode_id stays None preserves DQ visibility until the
                # route task resolves the link.
                await dismiss_orphans_for_file(self.session, file.id)
                mark_episode_tracked(ep, file.local_path or file.original_filename, "match")

        # Clear stale tracking on the old episode only when the episode actually
        # changed.  Running this after the heuristic avoids falsely clearing
        # tracking when the file resolves back to the same episode it was on.
        await clear_if_unreferenced(self.session, old_episode_id, file.episode_id)

        await self.session.flush()
        await self.session.refresh(file)
        await self.session.commit()

        logger.info(
            "Manually matched file id=%d → show id=%d (%s) S%sE%s",
            file.id,
            show.id,
            show.title,
            file.parsed_season,
            file.parsed_episode,
        )
