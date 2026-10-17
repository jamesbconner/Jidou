"""Orchestrator for manually matching a downloaded file to a show/episode."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.errors import InvalidRequestError, NotFoundError
from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.show import ContentType, Show
from jidou.orchestrators._show_provisioning import (
    generate_aliases_best_effort,
    insert_show_or_existing,
    sync_episodes_best_effort,
)
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.schemas.file_schema import FileMatchRequest
from jidou.services.alias_handling import add_alias, sanitize_alias
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_tracking import (
    clear_if_unreferenced,
    dismiss_orphans_for_file,
    link_file_to_episode,
    mark_episode_tracked,
)
from jidou.services.filename_parser import heuristic_se
from jidou.services.llm_service import LLMService
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata, stamp_refreshed

logger = logging.getLogger(__name__)


def _fill_missing_show_fields(show: Show, payload: FileMatchRequest) -> None:
    """Set ``local_path`` / ``content_type`` from the payload where the show has none.

    Never overwrites a configured value; the user changes those explicitly from
    the show detail page.

    Args:
        show: The existing show (mutated in place).
        payload: Match request carrying the optional values.
    """
    if payload.local_path and not show.local_path:
        show.local_path = payload.local_path
    if payload.content_type and not show.content_type:
        show.content_type = ContentType(payload.content_type)


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
        tmdb: TMDB service used to look up and sync shows created on demand.
        llm: Optional LLM service, used for alias generation on newly
            created shows.
    """

    def __init__(
        self, session: AsyncSession, tmdb: TMDBService, llm: LLMService | None = None
    ) -> None:
        self.session = session
        self.tmdb = tmdb
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
            NotFoundError: If the referenced show or TMDB resource is not found.
            InvalidRequestError: If the resolved show has no ``local_path``.
        """
        if payload.show_id is None and payload.tmdb_id is None:
            return await self._reset(file)

        if payload.tmdb_id is not None:
            show = await self._resolve_show_by_tmdb_id(payload)
        else:
            show = await self._resolve_show_by_id(payload)

        if show.local_path is None:
            raise InvalidRequestError(
                "Show has no local_path configured; "
                "provide local_path or set it via PATCH /shows/{id}/paths"
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
            NotFoundError: If no show has that ID.
        """
        show_stmt = select(Show).where(Show.id == payload.show_id)
        show = (await self.session.execute(show_stmt)).scalar_one_or_none()
        if show is None:
            raise NotFoundError("Show not found")
        return show

    async def _resolve_show_by_tmdb_id(self, payload: FileMatchRequest) -> Show:
        """Find or create a show for ``payload.tmdb_id``.

        Args:
            payload: Match request with ``tmdb_id`` set.

        Returns:
            The existing or newly created Show record.

        Raises:
            InvalidRequestError: If creating a new show and ``local_path`` is absent.
            NotFoundError: If the TMDB lookup fails.
        """
        if payload.tmdb_id is None:
            raise ValueError("_resolve_show_by_tmdb_id requires payload.tmdb_id to be set")

        # Check DB first (idempotent)
        tmdb_id = payload.tmdb_id
        show = await self._find_show_by_tmdb_id(tmdb_id)

        if show is not None:
            # Show exists — only fill in local_path / content_type if not already set.
            # Never silently overwrite a configured path; the user should explicitly
            # update it via the show detail page if they want to change it.
            _fill_missing_show_fields(show, payload)
            await self.session.flush()
            await TMDBOrchestrator(self.session, self.tmdb).ensure_episode_group_map(show)
            return show

        if not payload.local_path:
            raise InvalidRequestError("local_path is required when creating a new show via tmdb_id")

        tmdb = self.tmdb
        # Use the TMDB-reported media_type from the search result (tv/movie).
        # Fall back to inferring from content_type only when not provided.
        media_type = payload.tmdb_media_type or (
            "movie" if payload.content_type == "movie" else "tv"
        )
        try:
            data = await fetch_show_metadata(tmdb, tmdb_id, media_type)
        except Exception as exc:
            raise NotFoundError(f"TMDB lookup failed: {exc}") from exc

        fields = stamp_refreshed(build_show_fields(data, tmdb_id, media_type))
        new_show = Show(
            **fields,
            content_type=payload.content_type,
            local_path=payload.local_path,
            cached=False,
            track_missing_episodes=True,
        )

        async def refind() -> Show:
            winner = await self._find_show_by_tmdb_id(tmdb_id)
            if winner is None:
                # No winner to return: surface the original IntegrityError.
                raise
            # Apply caller's path/type only if the concurrently-created row
            # doesn't already have values — never overwrite existing config.
            _fill_missing_show_fields(winner, payload)
            await self.session.flush()
            # Treat the winner like a show found up front: it may predate the episode-group
            # map and still lack one.
            await TMDBOrchestrator(self.session, self.tmdb).ensure_episode_group_map(winner)
            return winner

        resolved, created = await insert_show_or_existing(self.session, new_show, refind=refind)
        if created:
            logger.info(
                "Created show tmdb_id=%d title=%r (id=%d) via on-demand match",
                resolved.tmdb_id,
                resolved.title,
                resolved.id,
            )

        await self._sync_and_alias_new_show(resolved, tmdb)

        return resolved

    async def _find_show_by_tmdb_id(self, tmdb_id: int) -> Show | None:
        """Look up a show by its TMDB ID.

        Args:
            tmdb_id: TMDB ID to look up.

        Returns:
            The matching Show, or ``None``.
        """
        show_stmt = select(Show).where(Show.tmdb_id == tmdb_id)
        return (await self.session.execute(show_stmt)).scalar_one_or_none()

    async def _sync_and_alias_new_show(self, show: Show, tmdb: TMDBService) -> None:
        """Sync a new show's episodes, commit, then generate its aliases.

        Both TMDB steps are best-effort; a database error in either propagates
        because the session's transaction is broken after one.

        Args:
            show: The created (or concurrently created) show.
            tmdb: TMDB service.

        Raises:
            SQLAlchemyError: If the episode sync or alias generation hits a
                database error.
        """
        # Sync episodes immediately so the episode lookup below has data to
        # work with.  Mirrors the inline sync in POST /shows.  Failures are
        # non-fatal — episodes will arrive on the next pipeline run.
        if show.media_type != "movie":
            sync_error = await sync_episodes_best_effort(
                self.session, tmdb, show, reraise_db_errors=True, rollback_on_failure=False
            )
            if sync_error is None:
                logger.info(
                    "Synced episodes for show id=%d tmdb_id=%d via manual match",
                    show.id,
                    show.tmdb_id,
                )
            else:
                logger.warning(
                    "Episode sync failed for show id=%d; episodes will sync on next pipeline run",
                    show.id,
                    exc_info=sync_error,
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
        alias_error = await generate_aliases_best_effort(
            self.session, tmdb, self.llm, show, reraise_db_errors=True, rollback_on_failure=False
        )
        if alias_error is None:
            logger.info(
                "Generated aliases for show id=%d tmdb_id=%d via manual match",
                show.id,
                show.tmdb_id,
            )
        else:
            logger.warning(
                "Alias generation failed for show id=%d; "
                "aliases can be regenerated via the Manage Aliases modal",
                show.id,
                exc_info=alias_error,
            )

    @staticmethod
    def _add_parsed_name_alias(file: DownloadedFile, show: Show) -> None:
        """Record the file's parsed show name as an alias of *show*.

        A name that already equals the show's title is skipped, since title
        lookup already covers it.

        Args:
            file: The file being assigned.
            show: The show it is assigned to (mutated in place).
        """
        name = (file.parsed_show_name or "").strip()
        if not name or sanitize_alias(name) == sanitize_alias(show.title):
            return
        add_alias(show, name)
        logger.info(
            "Added alias %r to show id=%d (%s) from manual match of file id=%d",
            sanitize_alias(name),
            show.id,
            show.title,
            file.id,
        )

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
            ep = await resolve_episode(
                self.session, show.id, file.parsed_season, file.parsed_episode
            )
            if ep is not None:
                # Also backfills a missing season, which enables Season NN routing.
                link_file_to_episode(file, ep)
                # Only dismiss the orphan once an episode is confirmed; keeping it
                # when episode_id stays None preserves DQ visibility until the
                # route task resolves the link.
                await dismiss_orphans_for_file(self.session, file.id)
                mark_episode_tracked(ep, file.local_path or file.original_filename, "match")

        # Add the name this file was parsed as to the show's aliases, so the next file with
        # the same parsed name matches automatically instead of landing in
        # UNMATCHED again. A manual match is an explicit human decision, so
        # unlike the parse pipeline there is no fuzzy-hit guard here.
        self._add_parsed_name_alias(file, show)

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
