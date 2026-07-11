"""Orchestrator for parsing filenames and matching downloaded files to shows."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.show import Show
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_tracking import dismiss_orphans_for_file
from jidou.services.filename_parser import heuristic_se, parse_filename
from jidou.services.llm_service import LLMService
from jidou.services.show_lookup import find_show_by_name
from jidou.services.sys_name import sanitize_sys_name

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class ParseResult:
    """Result of a batch filename parse + show-match operation."""

    files_processed: int
    files_matched: int
    files_unmatched: int
    files_failed: int
    dry_run: bool


def _sanitize_alias(name: str) -> str:
    """Normalise an alias name for case-insensitive storage and lookup."""
    return name.strip().lower()


def _is_exact_alias_match(show: Show, name: str) -> bool:
    """Return True if *name* already exactly names *show* (title or alias).

    Guards ``_add_alias`` calls after a fuzzy ``_find_show`` lookup: a
    substring hit (e.g. "Daredevil" matching "Daredevil: Born Again") must
    never get taught as a permanent alias, since that would misfile every
    future parse of the shorter name onto the longer show.

    Args:
        show: The show ``_find_show`` returned.
        name: The parsed name that was searched for.

    Returns:
        True if *name* matches ``show.title`` or is already in
        ``show.aliases`` (case-insensitive), False otherwise.
    """
    normalised = _sanitize_alias(name)
    if normalised == _sanitize_alias(show.title):
        return True
    return show.aliases is not None and normalised in show.aliases


class ParseOrchestrator:
    """Parse DOWNLOADED filenames and match to shows via alias lookup + LLM.

    Two-stage pipeline per file:
      1. LLM extracts ``show_name``, ``season``, ``episode``, and
         ``content_type`` from the raw filename.
      2. DB lookup: ``show.aliases`` contains the parsed name (case-folded),
         or ``show.title ILIKE`` as a fallback.

    On a successful match:
    - The parsed name is written back to ``show.aliases`` so future matches
      skip the LLM entirely.
    - If ``show.local_path`` is unset, it is auto-populated from
      ``show.sys_name`` and the appropriate media base path so that
      ``RouteOrchestrator`` can immediately move the file.

    Args:
        session: Active async SQLAlchemy session.
        llm: Optional LLMService; without it only the heuristic path runs.
        local_tv_path: Base directory for live-action TV series.
        local_anime_path: Base directory for anime series.
        local_movie_path: Base directory for movies.
    """

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMService | None = None,
        local_tv_path: str = "/data/media/tv",
        local_anime_path: str = "/data/media/anime",
        local_movie_path: str = "/data/media/movies",
    ) -> None:
        self.session = session
        self.llm = llm
        self.local_tv_path = local_tv_path
        self.local_anime_path = local_anime_path
        self.local_movie_path = local_movie_path

    def _resolve_local_path(self, show: Show) -> str:
        """Compute ``show.local_path`` from the show's sys_name and content type.

        Call this *after* backfilling ``show.content_type`` so the show's own
        classification is always authoritative.  Priority: ``show.content_type``
        → ``show.media_type`` → default TV.

        Args:
            show: The matched show record (content_type should already be set).

        Returns:
            Absolute path string for the show's root directory.
        """
        ct = show.content_type or show.media_type or "tv"
        if ct == "movie":
            base = self.local_movie_path
        elif ct == "anime":
            base = self.local_anime_path
        else:
            base = self.local_tv_path
        # sys_name is pre-sanitized; fall back to title with invalid chars stripped.
        dir_name = show.sys_name or sanitize_sys_name(show.title)
        # PurePosixPath ensures forward slashes — these are always Linux container paths.
        return str(PurePosixPath(base) / dir_name)

    async def _find_show(self, parsed_name: str) -> Show | None:
        """Look up a show by alias list containment or title match.

        Enables the substring title fallback (``fuzzy=True``) since the LLM's
        parsed name is not guaranteed to equal the show's exact stored title.
        A fuzzy hit must not be trusted as a valid alias on its own — see the
        exactness check in ``run()`` before ``_add_alias`` is called.

        Args:
            parsed_name: The extracted show name (not yet normalised).

        Returns:
            Matching :class:`Show` or None if not found.
        """
        return await find_show_by_name(self.session, parsed_name, fuzzy=True)

    @staticmethod
    def _add_alias(show: Show, alias: str) -> None:
        """Add a normalised alias to show.aliases and aliases_sources (in-place, no duplicate).

        Mirrors the alias into ``aliases_sources["user"]`` so the structured
        PUT /shows/{id}/aliases endpoint does not silently drop it when the
        user next edits aliases via the UI (which reads from aliases_sources).
        """
        norm = _sanitize_alias(alias)
        # Flat GIN-indexed column — used for fast show lookup during parsing.
        current: list[str] = list(show.aliases) if show.aliases else []
        if norm not in current:
            show.aliases = [*current, norm]
        # Structured source map — used by the UI and the PUT endpoint.
        sources: dict[str, list[str]] = dict(show.aliases_sources) if show.aliases_sources else {}
        if not show.aliases_sources and show.aliases:
            # First-time write on a legacy show: seed the user bucket from all
            # existing flat aliases so that generate_aliases or a UI save doesn't
            # orphan them when it rebuilds show.aliases from sources only.
            sources["user"] = list(show.aliases)
            show.aliases_sources = sources  # persist even if norm is already present
        user_aliases: list[str] = list(sources.get("user") or [])
        if norm not in user_aliases:
            sources["user"] = [*user_aliases, norm]
            show.aliases_sources = sources

    async def run(
        self,
        dry_run: bool = False,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> ParseResult:
        """Parse all DOWNLOADED files and update their status to MATCHED or UNMATCHED.

        Files are processed sequentially.  On each file:
        - Heuristic regex extracts S/E numbers as a fast path.
        - LLM parses the full show name, season, episode, and content type.
        - DB alias/title lookup finds the show.
        - Episode lookup uses parsed season/episode numbers.
        - Status is set to MATCHED (show found) or UNMATCHED (no show found).

        Args:
            dry_run: Log results without modifying the DB.
            on_progress: Optional async callback(current, total, message).

        Returns:
            ParseResult with counts.
        """
        stmt = select(DownloadedFile).where(DownloadedFile.status == FileStatus.DOWNLOADED)
        files = list((await self.session.execute(stmt)).scalars().all())
        total = len(files)

        files_matched = 0
        files_unmatched = 0
        files_failed = 0
        llm_active = self.llm is not None and self.llm.is_available()

        for idx, file in enumerate(files, 1):
            if on_progress:
                await on_progress(idx, total, f"Parsing {file.original_filename}")

            try:
                # Stage 1a: regex anchors season/episode (fast, structural)
                se = heuristic_se(file.original_filename)

                # Stage 1b: LLM parses show name + confirms/corrects S/E
                parsed = await parse_filename(file.original_filename, self.llm)

                # Prefer LLM values; fall back to regex anchor if LLM missed them
                season: int | None = parsed.season or (se[0] if se else None)
                episode: int | None = parsed.episode or (se[1] if se else None)
                show_name: str | None = parsed.show_name
                confidence: float = parsed.confidence
                content_type: str | None = parsed.content_type
                llm_ok: bool = parsed.llm_ok

                # Gate applies only when LLM produced a result and content is not a
                # movie (movie prompts always score low due to null-episode penalty).
                apply_gate = llm_active and llm_ok and content_type != "movie"

                if dry_run:
                    dry_show = await self._find_show(show_name) if show_name else None
                    logger.info(
                        "[DRY RUN] %s → show=%r S%sE%s confidence=%.2f match=%s",
                        file.original_filename,
                        show_name,
                        season,
                        episode,
                        confidence,
                        dry_show.title if dry_show is not None else "none",
                    )
                    gate_passes = not apply_gate or confidence >= _CONFIDENCE_THRESHOLD
                    if dry_show is not None and gate_passes:
                        files_matched += 1
                    else:
                        files_unmatched += 1
                    continue

                # Persist parsed metadata regardless of match outcome
                file.parsed_show_name = show_name
                file.parsed_season = season
                file.parsed_episode = episode
                file.parsed_confidence = confidence
                file.parsed_content_type = content_type

                # Stage 2: confidence gate — skipped for heuristic results (llm_ok=False)
                # and for movies (null episode is expected, not a sign of uncertainty).
                if apply_gate and confidence < _CONFIDENCE_THRESHOLD:
                    file.status = FileStatus.UNMATCHED
                    file.error_message = (
                        f"Parse confidence {confidence:.2f} below threshold "
                        f"{_CONFIDENCE_THRESHOLD} — manual review required"
                    )
                    files_unmatched += 1
                    logger.info(
                        "Low confidence (%.2f) for %s, flagging UNMATCHED",
                        confidence,
                        file.original_filename,
                    )
                    await self.session.flush()
                    continue

                # Stage 3: DB lookup
                if show_name:
                    show = await self._find_show(show_name)
                else:
                    show = None

                if show is not None:
                    file.show_id = show.id
                    ep = await resolve_episode(self.session, show.id, season, episode)
                    file.episode_id = ep.id if ep is not None else None
                    # When the LLM returned season=None (anime absolute numbering),
                    # backfill parsed_season from the resolved episode so RouteOrchestrator
                    # can place the file in the correct Season NN directory.
                    if ep is not None and season is None and ep.season_number is not None:
                        file.parsed_season = ep.season_number
                    if ep is not None:
                        await dismiss_orphans_for_file(self.session, file.id)
                    file.matched_by = (
                        MatchedBy.LLM
                        if (self.llm is not None and self.llm.is_available())
                        else MatchedBy.HEURISTIC
                    )
                    file.status = FileStatus.MATCHED
                    # Teach the alias index so future matches skip LLM — but only
                    # when show_name is already known to name this show exactly.
                    # A fuzzy substring hit from _find_show must never be
                    # permanently written as an alias.
                    if show_name and _is_exact_alias_match(show, show_name):
                        self._add_alias(show, show_name)
                    # Backfill show.content_type from the parsed value if unset
                    if content_type and not show.content_type:
                        show.content_type = content_type
                    # Auto-populate show.local_path when the content type is
                    # unambiguous.  media_type="movie" is always safe; media_type="tv"
                    # is not (TMDB uses "tv" for both TV series and anime), so for
                    # that case we require content_type to be explicitly set.
                    can_auto_path = bool(show.content_type) or show.media_type == "movie"
                    if show.local_path is None and can_auto_path:
                        show.local_path = self._resolve_local_path(show)
                        logger.debug(
                            "Auto-set local_path=%r for show id=%d",
                            show.local_path,
                            show.id,
                        )
                    elif show.local_path is None:
                        logger.warning(
                            "Cannot auto-set local_path for show id=%d: "
                            "content_type unknown — set it manually via PATCH /shows/%d",
                            show.id,
                            show.id,
                        )
                    files_matched += 1
                    logger.info(
                        "Matched %s → show_id=%d %s",
                        file.original_filename,
                        show.id,
                        show.title,
                    )
                else:
                    file.status = FileStatus.UNMATCHED
                    file.error_message = (
                        f"No show found for parsed name {show_name!r}"
                        if show_name
                        else "LLM could not identify a show name"
                    )
                    files_unmatched += 1
                    logger.info(
                        "Unmatched %s (parsed_name=%r)",
                        file.original_filename,
                        show_name,
                    )

                await self.session.flush()

            except Exception as exc:
                logger.error("Failed to parse %s: %s", file.original_filename, exc)
                if not dry_run:
                    file.status = FileStatus.ERROR
                    file.error_message = str(exc)
                    await self.session.flush()
                files_failed += 1

        if not dry_run:
            await self.session.commit()

        logger.info(
            "Parse complete: %d matched, %d unmatched, %d failed (dry_run=%s)",
            files_matched,
            files_unmatched,
            files_failed,
            dry_run,
        )
        return ParseResult(
            files_processed=total,
            files_matched=files_matched,
            files_unmatched=files_unmatched,
            files_failed=files_failed,
            dry_run=dry_run,
        )
