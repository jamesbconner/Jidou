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
from jidou.orchestrators._episode_refresh import EpisodeRefresher
from jidou.orchestrators._events import EventSink
from jidou.services.alias_handling import (
    add_alias,
    names_agree,
    season_for_name,
    unmapped_arc_label,
)
from jidou.services.callbacks import OnEvent, OnProgress
from jidou.services.duplicate_files import find_duplicate_original
from jidou.services.episode_file_matching import resolve_with_season
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_match_llm import llm_match_episode
from jidou.services.episode_tracking import dismiss_orphans_for_file, link_file_to_episode
from jidou.services.filename_parser import FilenameParseResult, heuristic_se, parse_filename
from jidou.services.llm_service import LLMService
from jidou.services.path_resolution import auto_local_path_for
from jidou.services.show_lookup import find_show_by_name

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
    # Decided MATCHED/UNMATCHED, then the closing flush (or a late step) raised. The batch
    # result has always counted such a file in both buckets; kept as is.
    MATCHED_THEN_FAILED = auto()
    UNMATCHED_THEN_FAILED = auto()


# Maps the outcome decided before a failure to the outcome that preserves its count.
_FAILED_AFTER: dict[ParseOutcome | None, ParseOutcome] = {
    ParseOutcome.MATCHED: ParseOutcome.MATCHED_THEN_FAILED,
    ParseOutcome.UNMATCHED: ParseOutcome.UNMATCHED_THEN_FAILED,
}


def _missing_episode_reason(show: Show, season: int | None, episode: int | None) -> str:
    """Explain why no episode row was found, for ``DownloadedFile.error_message``.

    Args:
        show: The matched show.
        season: Parsed season number, if any.
        episode: Parsed episode number, if any.

    Returns:
        A message naming what was looked up and what the user can do.
    """
    if episode is None:
        return f"No episode number detected for {show.title!r}; resolve it manually"
    if season is None:
        return (
            f"Season not detected, and episode {episode} of {show.title!r} matches neither an "
            "absolute episode number nor a Season 1 episode; resolve it manually"
        )
    return (
        f"Episode S{season:02d}E{episode:02d} of {show.title!r} not found in the "
        "database; resolve it manually or re-run Parse once the show's episodes are current"
    )


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
        episode_refresher: Optional refresher used when a matched show has no
            episode row for the parsed numbers (typically a new season whose
            episodes are not synced yet). Without it the miss goes straight to
            UNMATCHED.
    """

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMService | None = None,
        local_tv_path: str = "/data/media/tv",
        local_anime_path: str = "/data/media/anime",
        local_movie_path: str = "/data/media/movies",
        episode_refresher: EpisodeRefresher | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.local_tv_path = local_tv_path
        self.local_anime_path = local_anime_path
        self.local_movie_path = local_movie_path
        self.episode_refresher = episode_refresher
        # Shows already refreshed in this orchestrator's lifetime (one run): a
        # second miss for the same show cannot be cured by refreshing again.
        self._refreshed_show_ids: set[int] = set()

    def _resolve_local_path(self, show: Show) -> str | None:
        """Compute ``show.local_path`` from this run's library roots.

        Call this *after* backfilling ``show.content_type`` so the show's own
        classification is always authoritative. See
        :func:`~jidou.services.path_resolution.auto_local_path_for` for the rule.

        Args:
            show: The matched show record (content_type should already be set).

        Returns:
            Absolute path string for the show's root directory, or None when
            the show's library is ambiguous (no content_type, not a movie).
        """
        return auto_local_path_for(
            show,
            tv=self.local_tv_path,
            anime=self.local_anime_path,
            movie=self.local_movie_path,
        )

    async def _find_show(self, parsed_name: str) -> Show | None:
        """Look up a show by alias list containment or title match.

        Enables the substring title fallback (``fuzzy=True``) since the LLM's
        parsed name is not guaranteed to equal the show's exact stored title.
        A fuzzy hit must not be trusted as a valid alias on its own — see the
        exactness check in ``_apply_match()`` before ``add_alias`` is called.

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
        if show.local_path is not None:
            return
        auto_path = self._resolve_local_path(show)
        if auto_path is not None:
            show.local_path = auto_path
            logger.debug(
                "Auto-set local_path=%r for show id=%d",
                show.local_path,
                show.id,
            )
        else:
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
        remap_groups: bool = False,
    ) -> tuple[Episode | None, int | None, int | None]:
        """Find the episode row for a matched show, falling back to an LLM title match.

        Args:
            file: The file being matched (its parsed numbers are updated by the fallback).
            show: The matched show.
            season: Parsed season number, if any.
            episode: Parsed episode number, if any.
            llm_active: Whether an LLM is configured and available for this run.
            sink: Event sink forwarded to the LLM matcher.
            remap_groups: Try the show's episode-group remap when the direct
                ``(season, episode)`` lookup misses. Set for a season taken
                from a season name, since TMDB may number that arc as a
                continuation of an earlier season.

        Returns:
            ``(episode_row, season, episode)``; the numbers are the remapped or
            LLM ones when either supplied them.
        """
        if remap_groups and season is not None and episode is not None:
            hit = await resolve_with_season(
                self.session, show.id, show.episode_group_map, season, episode
            )
            ep = None
            if hit is not None:
                ep, season, episode = hit
                file.parsed_season = season
                file.parsed_episode = episode
        else:
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
            if ep is not None and remap_groups and ep.season_number != season:
                # A season name fixes the season; a title guess from another
                # season would misfile the arc all over again.
                logger.info(
                    "Ignoring LLM episode match S%sE%s for %s: season name says season %s",
                    llm_ep_season,
                    llm_ep_num,
                    file.original_filename,
                    season,
                )
                ep = None
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

    async def _flag_duplicate(
        self, file: DownloadedFile, show: Show, ep: Episode, sink: EventSink
    ) -> None:
        """Flag *file* when another file already covers *ep* (decision D33).

        Both files are kept and routing is unchanged; picking a copy stays a
        manual decision. The flag is recomputed on every link, so a re-parse
        clears a stale one.

        Args:
            file: The file just linked to *ep*.
            show: The matched show (for the warning text).
            ep: The episode the file was linked to.
            sink: Event sink.
        """
        original = await find_duplicate_original(self.session, episode_id=ep.id, file_id=file.id)
        file.duplicate_of_file_id = original.id if original is not None else None
        if original is None:
            return
        logger.warning(
            "Duplicate file id=%s for episode id=%d (original file id=%d)",
            file.id,
            ep.id,
            original.id,
        )
        await sink(
            "warn",
            f"Episode S{ep.season_number:02d}E{ep.episode_number:02d} of '{show.title}' "
            f"already has '{original.original_filename}'; "
            f"'{file.original_filename}' flagged as a duplicate (both kept)",
            {"file_id": file.id, "duplicate_of_file_id": original.id, "episode_id": ep.id},
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
        remap_groups: bool = False,
    ) -> ParseOutcome:
        """Link *file* to *show*, resolve its episode and mark it MATCHED.

        A non-movie file whose episode cannot be resolved (even after a
        metadata refresh) keeps its show link but is marked UNMATCHED, so it
        is not routed into the show root before its episode data exists.

        Args:
            file: The file being matched.
            show: The show found for the parsed name.
            season: Parsed season number, if any.
            episode: Parsed episode number, if any.
            show_name: The parsed show name, used for the alias write-back.
            content_type: Raw parsed content type, used for the show backfill.
            llm_active: Whether an LLM is configured and available for this run.
            sink: Event sink.
            remap_groups: Forwarded to :meth:`_resolve_matched_episode`.

        Returns:
            ``UNMATCHED`` when a non-movie episode could not be resolved,
            otherwise ``MATCHED``.
        """
        file.show_id = show.id
        ep, season, episode = await self._resolve_with_refresh(
            file,
            show,
            season,
            episode,
            llm_active=llm_active,
            sink=sink,
            remap_groups=remap_groups,
        )
        unresolved = ep is None and show.media_type != "movie"
        if ep is None:
            file.episode_id = None
            file.duplicate_of_file_id = None
        else:
            # When the LLM returned season=None (anime absolute numbering), the
            # helper backfills parsed_season from the resolved episode so
            # RouteOrchestrator can place the file in the correct Season NN directory.
            link_file_to_episode(file, ep)
            await dismiss_orphans_for_file(self.session, file.id)
        file.matched_by = MatchedBy.LLM if llm_active else MatchedBy.HEURISTIC
        file.status = FileStatus.UNMATCHED if unresolved else FileStatus.MATCHED
        # Replaces any stale reason from a prior attempt (None when matched).
        file.error_message = _missing_episode_reason(show, season, episode) if unresolved else None
        # Add the alias so future matches skip LLM — but only
        # when show_name is already known to name this show exactly.
        # A fuzzy substring hit from _find_show must never be
        # permanently written as an alias.
        if show_name and names_agree(show_name, show):
            add_alias(show, show_name)
        self._backfill_content_type(file, show, content_type)
        self._ensure_show_local_path(show)
        if unresolved:
            await self._report_missing_episode(file, show, sink)
            return ParseOutcome.UNMATCHED
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
        if ep is not None:
            await self._flag_duplicate(file, show, ep, sink)
        return ParseOutcome.MATCHED

    async def _resolve_with_refresh(
        self,
        file: DownloadedFile,
        show: Show,
        season: int | None,
        episode: int | None,
        *,
        llm_active: bool,
        sink: EventSink,
        remap_groups: bool,
    ) -> tuple[Episode | None, int | None, int | None]:
        """Resolve the episode, refreshing the show's episodes once on a miss.

        A miss on a non-movie show usually means TMDB data for a new season or
        episode has not been synced yet. The refresh runs at most once per show
        per run, and the lookup is retried only if it brought in new episodes.

        Args:
            file: The file being matched.
            show: The matched show.
            season: Parsed season number, if any.
            episode: Parsed episode number, if any.
            llm_active: Whether an LLM is configured and available for this run.
            sink: Event sink.
            remap_groups: Forwarded to :meth:`_resolve_matched_episode`.

        Returns:
            ``(episode_row, season, episode)`` as :meth:`_resolve_matched_episode`.
        """
        resolved = await self._resolve_matched_episode(
            file,
            show,
            season,
            episode,
            llm_active=llm_active,
            sink=sink,
            remap_groups=remap_groups,
        )
        if resolved[0] is not None or not await self._refresh_for_miss(file, show, sink):
            return resolved
        return await self._resolve_matched_episode(
            file,
            show,
            resolved[1],
            resolved[2],
            llm_active=llm_active,
            sink=sink,
            remap_groups=remap_groups,
        )

    async def _refresh_for_miss(self, file: DownloadedFile, show: Show, sink: EventSink) -> bool:
        """Refresh *show*'s episodes after a lookup miss, if that is allowed and useful.

        Args:
            file: The file whose episode was not found.
            show: The matched show.
            sink: Event sink.

        Returns:
            True when the refresh added episodes, so a retry may now succeed.
            False for movies, a missing refresher, an already-refreshed show,
            or a refresh that added nothing.
        """
        if (
            self.episode_refresher is None
            or show.media_type == "movie"
            or show.id in self._refreshed_show_ids
        ):
            return False
        self._refreshed_show_ids.add(show.id)
        await sink(
            "info",
            f"Episode not found for {file.original_filename!r}; "
            f"refreshing episodes for {show.title!r}",
            {"file_id": file.id, "show_id": show.id},
        )
        return await self.episode_refresher.refresh_episodes(show)

    async def _report_missing_episode(
        self, file: DownloadedFile, show: Show, sink: EventSink
    ) -> None:
        """Log and emit the warning for a file left UNMATCHED by a missing episode.

        Args:
            file: The file left UNMATCHED; ``error_message`` carries the reason.
            show: The show it was matched to.
            sink: Event sink.
        """
        logger.info(
            "No episode for %s (show id=%d), flagging UNMATCHED: %s",
            file.original_filename,
            show.id,
            file.error_message,
        )
        await sink(
            "warn",
            f"{file.original_filename!r} → {show.title!r}: {file.error_message}",
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
            return await self._preview_matched_show(
                file, dry_show, show_name, season, episode, sink
            )
        await sink(
            "info",
            f"[Dry run] Would leave unmatched: {file.original_filename!r}",
            {"file_id": file.id},
        )
        return ParseOutcome.UNMATCHED

    async def _preview_matched_show(
        self,
        file: DownloadedFile,
        show: Show,
        show_name: str | None,
        season: int | None,
        episode: int | None,
        sink: EventSink,
    ) -> ParseOutcome:
        """Dry-run a file whose show was found: unmapped arc, episode lookup, then match.

        Args:
            file: The file being previewed (never modified).
            show: The show the parsed name matched.
            show_name: The parsed show name, if any.
            season: Merged season number, if any.
            episode: Merged episode number, if any.
            sink: Event sink.

        Returns:
            ``MATCHED`` if a real run would match the file, otherwise ``UNMATCHED``.
        """
        alias_season: int | None = None
        if season is None and show_name:
            label = unmapped_arc_label(show_name, show)
            if label is not None:
                await sink(
                    "info",
                    f"[Dry run] Would leave unmatched (unmapped arc {label!r}): "
                    f"{file.original_filename!r}",
                    {"file_id": file.id, "show_id": show.id, "arc_label": label},
                )
                return ParseOutcome.UNMATCHED
            alias_season = season_for_name(show_name, show)
        if not await self._preview_episode_exists(show, alias_season or season, episode):
            await sink(
                "info",
                f"[Dry run] Would leave unmatched unless the episode refresh finds it: "
                f"{file.original_filename!r} → {show.title!r}",
                {"file_id": file.id, "show_id": show.id},
            )
            return ParseOutcome.UNMATCHED
        suffix = f" (Season {alias_season} from season name)" if alias_season is not None else ""
        await sink(
            "info",
            f"[Dry run] Would match {file.original_filename!r} → {show.title!r}{suffix}",
            {"file_id": file.id, "show_id": show.id},
        )
        return ParseOutcome.MATCHED

    async def _preview_episode_exists(
        self, show: Show, season: int | None, episode: int | None
    ) -> bool:
        """Read-only check that a real run would find the file's episode without a refresh.

        A dry run cannot refresh or call the LLM, so a miss here is reported as
        "unmatched unless the refresh finds it". Movies have no episode rows.

        Args:
            show: The matched show.
            season: Season to look up (a season-name season takes precedence).
            episode: Episode number to look up.

        Returns:
            True for a movie or when the episode row exists.
        """
        if show.media_type == "movie":
            return True
        if episode is not None and season is not None and show.episode_group_map is not None:
            hit = await resolve_with_season(
                self.session, show.id, show.episode_group_map, season, episode
            )
            if hit is not None:
                return True
        return await resolve_episode(self.session, show.id, season, episode) is not None

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
        return ParseOutcome.UNMATCHED

    async def _season_from_alias(
        self, file: DownloadedFile, show: Show, show_name: str, sink: EventSink
    ) -> int | None:
        """Take the season from a season name on *show*, recording it on *file*.

        Args:
            file: The file being matched; ``parsed_season`` is set on a hit.
            show: The matched show.
            show_name: The parsed show name.
            sink: Event sink.

        Returns:
            The season number, or None when *show_name* is not a season name.
        """
        season = season_for_name(show_name, show)
        if season is None:
            return None
        file.parsed_season = season
        logger.info(
            "Season %d from season name %r for %s (show id=%d)",
            season,
            show_name,
            file.original_filename,
            show.id,
        )
        await sink(
            "info",
            f"Season {season} from season name {show_name!r} for {show.title!r}",
            {"file_id": file.id, "show_id": show.id, "season": season},
        )
        return season

    async def _flag_unmapped_arc(
        self, file: DownloadedFile, show: Show, label: str, sink: EventSink
    ) -> ParseOutcome:
        """Mark *file* UNMATCHED because its arc label has no season set.

        Guessing Season 1 (the absolute-number fallback) would link the wrong
        episode and route the file into the wrong season directory.

        Args:
            file: The file to flag.
            show: The show the name's prefix matched.
            label: The arc label from the parsed name.
            sink: Event sink.

        Returns:
            Always ``UNMATCHED``.
        """
        file.status = FileStatus.UNMATCHED
        file.error_message = (
            f"{label!r} looks like a season or arc name for {show.title!r} but has no "
            "season set; add it under Season names in the show's aliases, then re-run Parse"
        )
        logger.info(
            "Unmapped arc %r for %s (show id=%d), flagging UNMATCHED",
            label,
            file.original_filename,
            show.id,
        )
        await sink(
            "warn",
            f"Unmapped arc {label!r} for {file.original_filename!r} ({show.title!r}), "
            "flagging UNMATCHED",
            {"file_id": file.id, "show_id": show.id, "arc_label": label},
        )
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
        # Set once MATCHED/UNMATCHED is decided, so a failure in the closing flush is
        # still counted the way it always was (in both buckets).
        decided: ParseOutcome | None = None
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
                decided = await self._flag_low_confidence(file, parsed.confidence, sink)
                await self.session.flush()
                return decided

            # Stage 3: DB lookup
            show = await self._find_show(parsed.show_name) if parsed.show_name else None
            remap_groups = False
            if show is not None and season is None and parsed.show_name:
                # "<show> - <arc>" names a season the filename does not number.
                label = unmapped_arc_label(parsed.show_name, show)
                if label is not None:
                    decided = await self._flag_unmapped_arc(file, show, label, sink)
                    await self.session.flush()
                    return decided
                season = await self._season_from_alias(file, show, parsed.show_name, sink)
                remap_groups = season is not None
            if show is not None:
                decided = await self._apply_match(
                    file,
                    show,
                    season,
                    episode,
                    show_name=parsed.show_name,
                    content_type=parsed.content_type,
                    llm_active=llm_active,
                    sink=sink,
                    remap_groups=remap_groups,
                )
            else:
                await self._mark_unmatched(file, parsed.show_name, sink)
                decided = ParseOutcome.UNMATCHED
            await self.session.flush()
            return decided

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
            return _FAILED_AFTER.get(decided, ParseOutcome.FAILED)

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
        - Episode lookup uses parsed season/episode numbers; a miss refreshes the
          show's episodes once per run and retries.
        - Status is set to MATCHED (show and, for non-movies, episode found) or
          UNMATCHED (no show found, or no episode even after the refresh).

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

        files_matched = counts[ParseOutcome.MATCHED] + counts[ParseOutcome.MATCHED_THEN_FAILED]
        files_unmatched = (
            counts[ParseOutcome.UNMATCHED] + counts[ParseOutcome.UNMATCHED_THEN_FAILED]
        )
        files_failed = (
            counts[ParseOutcome.FAILED]
            + counts[ParseOutcome.MATCHED_THEN_FAILED]
            + counts[ParseOutcome.UNMATCHED_THEN_FAILED]
        )
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
