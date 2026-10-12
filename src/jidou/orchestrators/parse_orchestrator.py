"""Orchestrator for parsing filenames and matching downloaded files to shows."""

import logging
from collections import Counter
from dataclasses import dataclass
from enum import Enum, auto

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.show import ContentType, Show
from jidou.orchestrators._events import EventSink
from jidou.services.alias_handling import add_alias, sanitize_alias
from jidou.services.callbacks import OnEvent, OnProgress
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_match_llm import llm_match_episode
from jidou.services.episode_tracking import dismiss_orphans_for_file
from jidou.services.filename_parser import FilenameParseResult, heuristic_se, parse_filename
from jidou.services.llm_service import LLMService
from jidou.services.path_resolution import resolve_show_local_path
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


class ParseOutcome(Enum):
    """How parsing one file ended, as tallied by :meth:`ParseOrchestrator.run`."""

    MATCHED = auto()
    UNMATCHED = auto()
    FAILED = auto()


def _is_exact_alias_match(show: Show, name: str) -> bool:
    """Return True if *name* already exactly names *show* (title or alias).

    Guards ``add_alias`` calls after a fuzzy ``_find_show`` lookup: a
    substring hit (e.g. "Daredevil" matching "Daredevil: Born Again") must
    never get added as a permanent alias, since that would misfile every
    future parse of the shorter name onto the longer show.

    Args:
        show: The show ``_find_show`` returned.
        name: The parsed name that was searched for.

    Returns:
        True if *name* matches ``show.title`` or is already in
        ``show.aliases`` (case-insensitive), False otherwise.
    """
    normalised = sanitize_alias(name)
    if normalised == sanitize_alias(show.title):
        return True
    return show.aliases is not None and normalised in show.aliases


class ParseOrchestrator:
    """Parse DOWNLOADED/UNMATCHED filenames and match to shows via alias lookup + LLM.

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
        # sys_name is pre-sanitized; fall back to title with invalid chars stripped.
        dir_name = show.sys_name or sanitize_sys_name(show.title)
        return resolve_show_local_path(
            content_type=show.content_type,
            media_type=show.media_type,
            sys_name=dir_name,
            local_tv_path=self.local_tv_path,
            local_anime_path=self.local_anime_path,
            local_movie_path=self.local_movie_path,
        )

    async def _find_show(self, parsed_name: str) -> Show | None:
        """Look up a show by alias list containment or title match.

        Enables the substring title fallback (``fuzzy=True``) since the LLM's
        parsed name is not guaranteed to equal the show's exact stored title.
        A fuzzy hit must not be trusted as a valid alias on its own — see the
        exactness check in ``run()`` before ``add_alias`` is called.

        Args:
            parsed_name: The extracted show name (not yet normalised).

        Returns:
            Matching :class:`Show` or None if not found.
        """
        return await find_show_by_name(self.session, parsed_name, fuzzy=True)

    def _ensure_show_local_path(self, show: Show) -> None:
        """Auto-populate ``show.local_path`` when the content type is unambiguous.

        ``media_type="movie"`` is always safe; ``media_type="tv"`` is not (TMDB
        uses "tv" for both TV series and anime), so for that case the show's
        ``content_type`` must be explicitly set.

        Args:
            show: The matched show (``content_type`` already backfilled).
        """
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

    async def _resolve_matched_episode(
        self,
        file: DownloadedFile,
        show: Show,
        season: int | None,
        episode: int | None,
        *,
        llm_active: bool,
        sink: EventSink,
    ) -> tuple[Episode | None, int | None, int | None]:
        """Find the episode row for a matched show, falling back to an LLM title match.

        Args:
            file: The file being matched (its parsed numbers are updated by the fallback).
            show: The matched show.
            season: Parsed season number, if any.
            episode: Parsed episode number, if any.
            llm_active: Whether an LLM is configured and available for this run.
            sink: Event sink forwarded to the LLM matcher.

        Returns:
            ``(episode_row, season, episode)``; the numbers are the LLM's when the
            title fallback supplied them.
        """
        ep = await resolve_episode(self.session, show.id, season, episode)
        if ep is None and llm_active:
            # No number matched a known episode (or none was found
            # at all) -- last resort: match by title against the
            # show's full episode list before giving up.
            ep, llm_ep_season, llm_ep_num = await llm_match_episode(
                self.session,
                self.llm,
                show.id,
                show.title,
                file.original_filename,
                on_event=sink,
            )
            if ep is not None:
                season = llm_ep_season if llm_ep_season is not None else season
                episode = llm_ep_num if llm_ep_num is not None else episode
                file.parsed_season = season
                file.parsed_episode = episode
        return ep, season, episode

    def _backfill_content_type(
        self, file: DownloadedFile, show: Show, content_type: str | None
    ) -> None:
        """Backfill ``show.content_type`` from the parsed value if the show has none.

        Args:
            file: The file being matched (for the warning's context).
            show: The matched show.
            content_type: Raw content type returned by the parser, if any.
        """
        if not content_type or show.content_type:
            return
        try:
            show.content_type = ContentType(content_type)
        except ValueError:
            # Not every provider enforces the response schema. Storing the
            # raw string would make the show unloadable (LookupError), and
            # raising would flip an otherwise good match to ERROR, so skip
            # only the backfill. parsed_content_type keeps the raw answer.
            logger.warning(
                "Ignoring out-of-vocabulary content_type %r for file id=%s (show id=%d)",
                content_type,
                file.id,
                show.id,
            )

    async def _apply_match(
        self,
        file: DownloadedFile,
        show: Show,
        season: int | None,
        episode: int | None,
        *,
        show_name: str | None,
        content_type: str | None,
        llm_active: bool,
        sink: EventSink,
    ) -> None:
        """Link *file* to *show*, resolve its episode and mark it MATCHED.

        Args:
            file: The file being matched.
            show: The show found for the parsed name.
            season: Parsed season number, if any.
            episode: Parsed episode number, if any.
            show_name: The parsed show name, used for the alias write-back.
            content_type: Raw parsed content type, used for the show backfill.
            llm_active: Whether an LLM is configured and available for this run.
            sink: Event sink.
        """
        file.show_id = show.id
        ep, season, episode = await self._resolve_matched_episode(
            file, show, season, episode, llm_active=llm_active, sink=sink
        )
        file.episode_id = ep.id if ep is not None else None
        if ep is not None:
            # When the LLM returned season=None (anime absolute numbering),
            # backfill parsed_season from the resolved episode so RouteOrchestrator
            # can place the file in the correct Season NN directory.
            if season is None and ep.season_number is not None:
                file.parsed_season = ep.season_number
            await dismiss_orphans_for_file(self.session, file.id)
        file.matched_by = MatchedBy.LLM if llm_active else MatchedBy.HEURISTIC
        file.status = FileStatus.MATCHED
        # Clear any stale reason from a prior UNMATCHED attempt.
        file.error_message = None
        # Add the alias so future matches skip LLM — but only
        # when show_name is already known to name this show exactly.
        # A fuzzy substring hit from _find_show must never be
        # permanently written as an alias.
        if show_name and _is_exact_alias_match(show, show_name):
            add_alias(show, show_name)
        self._backfill_content_type(file, show, content_type)
        self._ensure_show_local_path(show)
        logger.info(
            "Matched %s → show_id=%d %s",
            file.original_filename,
            show.id,
            show.title,
        )
        await sink(
            "info",
            f"Matched {file.original_filename!r} → {show.title!r}",
            {"file_id": file.id, "show_id": show.id},
        )

    async def _preview_one(
        self,
        file: DownloadedFile,
        parsed: FilenameParseResult,
        season: int | None,
        episode: int | None,
        *,
        apply_gate: bool,
        sink: EventSink,
    ) -> ParseOutcome:
        """Dry-run one file: look the show up and report what would happen.

        Args:
            file: The file being previewed (never modified).
            parsed: The parser's result for its filename.
            season: Merged season number, if any.
            episode: Merged episode number, if any.
            apply_gate: Whether the confidence gate applies to this result.
            sink: Event sink.

        Returns:
            ``MATCHED`` if the file would be matched, otherwise ``UNMATCHED``.
        """
        show_name = parsed.show_name
        dry_show = await self._find_show(show_name) if show_name else None
        logger.info(
            "[DRY RUN] %s → show=%r S%sE%s confidence=%.2f match=%s",
            file.original_filename,
            show_name,
            season,
            episode,
            parsed.confidence,
            dry_show.title if dry_show is not None else "none",
        )
        gate_passes = not apply_gate or parsed.confidence >= _CONFIDENCE_THRESHOLD
        if dry_show is not None and gate_passes:
            await sink(
                "info",
                f"[Dry run] Would match {file.original_filename!r} → {dry_show.title!r}",
                {"file_id": file.id, "show_id": dry_show.id},
            )
            return ParseOutcome.MATCHED
        await sink(
            "info",
            f"[Dry run] Would leave unmatched: {file.original_filename!r}",
            {"file_id": file.id},
        )
        return ParseOutcome.UNMATCHED

    async def _flag_low_confidence(
        self, file: DownloadedFile, confidence: float, sink: EventSink
    ) -> ParseOutcome:
        """Mark *file* UNMATCHED because the LLM's confidence is below the threshold.

        Args:
            file: The file to flag.
            confidence: The parser's confidence score.
            sink: Event sink.

        Returns:
            Always ``UNMATCHED``.
        """
        file.status = FileStatus.UNMATCHED
        file.error_message = (
            f"Parse confidence {confidence:.2f} below threshold "
            f"{_CONFIDENCE_THRESHOLD} — manual review required"
        )
        logger.info(
            "Low confidence (%.2f) for %s, flagging UNMATCHED",
            confidence,
            file.original_filename,
        )
        await sink(
            "warn",
            f"Low confidence ({confidence:.2f}) for {file.original_filename!r}, flagging UNMATCHED",
            {"file_id": file.id, "confidence": confidence},
        )
        await self.session.flush()
        return ParseOutcome.UNMATCHED

    async def _mark_unmatched(
        self, file: DownloadedFile, show_name: str | None, sink: EventSink
    ) -> None:
        """Mark *file* UNMATCHED because no show was found for the parsed name.

        Args:
            file: The file to mark.
            show_name: The parsed show name, or None if the parser found none.
            sink: Event sink.
        """
        file.status = FileStatus.UNMATCHED
        file.error_message = (
            f"No show found for parsed name {show_name!r}"
            if show_name
            else "LLM could not identify a show name"
        )
        logger.info(
            "Unmatched %s (parsed_name=%r)",
            file.original_filename,
            show_name,
        )
        await sink(
            "warn",
            f"Unmatched {file.original_filename!r} (parsed_name={show_name!r})",
            {"file_id": file.id, "parsed_name": show_name},
        )

    async def _parse_one(
        self,
        file: DownloadedFile,
        *,
        dry_run: bool,
        llm_active: bool,
        sink: EventSink,
    ) -> ParseOutcome:
        """Parse and match a single file, turning any exception into ``FAILED``.

        Args:
            file: The DOWNLOADED/UNMATCHED file.
            dry_run: Preview only; the file and DB are not modified.
            llm_active: Whether an LLM is configured and available, computed once per run.
            sink: Event sink.

        Returns:
            How the file ended.
        """
        try:
            # Stage 1a: regex anchors season/episode (fast, structural)
            se = heuristic_se(file.original_filename)

            # Stage 1b: LLM parses show name + confirms/corrects S/E
            parsed = await parse_filename(file.original_filename, self.llm)

            # Prefer LLM values; fall back to regex anchor if LLM missed them.
            # `is not None` (not `or`) because 0 is a real, meaningful value
            # here -- season 0 is TMDB's specials convention, and "or" would
            # otherwise treat a correctly-identified 0 as falsy/absent and
            # silently replace it with the regex fallback (or None).
            season = parsed.season if parsed.season is not None else (se[0] if se else None)
            episode = parsed.episode if parsed.episode is not None else (se[1] if se else None)

            # Gate applies only when LLM produced a result and content is not a
            # movie (movie prompts always score low due to null-episode penalty).
            apply_gate = llm_active and parsed.llm_ok and parsed.content_type != "movie"

            if dry_run:
                return await self._preview_one(
                    file, parsed, season, episode, apply_gate=apply_gate, sink=sink
                )

            # Persist parsed metadata regardless of match outcome
            file.parsed_show_name = parsed.show_name
            file.parsed_season = season
            file.parsed_episode = episode
            file.parsed_confidence = parsed.confidence
            file.parsed_content_type = parsed.content_type
            # Independent of crc32_extracted (DownloadOrchestrator's regex-only
            # reading) — lets a divergence (e.g. LLM misreads the tag) be
            # pinpointed to this stage instead of masked as a false corruption.
            file.crc32_declared = parsed.crc32

            # Stage 2: confidence gate — skipped for heuristic results (llm_ok=False)
            # and for movies (null episode is expected, not a sign of uncertainty).
            if apply_gate and parsed.confidence < _CONFIDENCE_THRESHOLD:
                return await self._flag_low_confidence(file, parsed.confidence, sink)

            # Stage 3: DB lookup
            show = await self._find_show(parsed.show_name) if parsed.show_name else None
            if show is not None:
                await self._apply_match(
                    file,
                    show,
                    season,
                    episode,
                    show_name=parsed.show_name,
                    content_type=parsed.content_type,
                    llm_active=llm_active,
                    sink=sink,
                )
                outcome = ParseOutcome.MATCHED
            else:
                await self._mark_unmatched(file, parsed.show_name, sink)
                outcome = ParseOutcome.UNMATCHED
            await self.session.flush()
            return outcome

        except Exception as exc:
            logger.error("Failed to parse %s: %s", file.original_filename, exc)
            await sink(
                "error",
                f"Failed to parse {file.original_filename!r}: {exc}",
                {"file_id": file.id, "error": str(exc)},
            )
            if not dry_run:
                file.status = FileStatus.ERROR
                file.error_message = str(exc)
                await self.session.flush()
            return ParseOutcome.FAILED

    async def run(
        self,
        dry_run: bool = False,
        on_progress: OnProgress | None = None,
        on_event: OnEvent | None = None,
    ) -> ParseResult:
        """Parse all DOWNLOADED and UNMATCHED files, updating status to MATCHED or UNMATCHED.

        Re-including UNMATCHED files on every run lets a user add the missing
        show (via the Files page "Resolve" flow or the Shows page) and then
        simply re-run this task to sweep up every previously-unmatched file for
        that show, instead of manually resolving each one.

        Files are processed sequentially.  On each file:
        - Heuristic regex extracts S/E numbers as a fast path.
        - LLM parses the full show name, season, episode, and content type.
        - DB alias/title lookup finds the show.
        - Episode lookup uses parsed season/episode numbers.
        - Status is set to MATCHED (show found) or UNMATCHED (no show found).

        Args:
            dry_run: Log results without modifying the DB.
            on_progress: Optional async callback(current, total, message).
            on_event: Optional async callback(level, message, ctx) for
                structured per-file event log entries.

        Returns:
            ParseResult with counts.
        """

        sink = EventSink(on_event, swallow_errors=True)

        stmt = select(DownloadedFile).where(
            DownloadedFile.status.in_([FileStatus.DOWNLOADED, FileStatus.UNMATCHED])
        )
        files = list((await self.session.execute(stmt)).scalars().all())
        total = len(files)

        # Availability is checked once per run so every file in the batch is
        # attributed (matched_by) consistently, rather than re-probing per file.
        llm_active = self.llm is not None and self.llm.is_available()

        counts: Counter[ParseOutcome] = Counter()
        for idx, file in enumerate(files, 1):
            if on_progress:
                await on_progress(idx, total, f"Parsing {file.original_filename}")
            outcome = await self._parse_one(file, dry_run=dry_run, llm_active=llm_active, sink=sink)
            counts[outcome] += 1

        if not dry_run:
            await self.session.commit()

        files_matched = counts[ParseOutcome.MATCHED]
        files_unmatched = counts[ParseOutcome.UNMATCHED]
        files_failed = counts[ParseOutcome.FAILED]
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
