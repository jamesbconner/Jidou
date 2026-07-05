"""Orchestrator for matching downloaded files to episodes via heuristic + LLM."""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.show import Show
from jidou.services.episode_tracking import clear_episode_tracking, mark_episode_tracked
from jidou.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# Ordered list of regex patterns for episode detection.
# Each must capture group 1 = season number, group 2 = episode number.
# The NxN pattern uses word boundaries and caps season at 2 digits / episode at 3
# digits to avoid false positives from resolution strings like "1920x1080".
_EP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})"),  # S01E02 / s01e02
    re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)"),  # 1x02 but NOT 1920x1080
]

_LLM_SYSTEM = (
    "You are a filename-to-episode matcher. "
    "Given a show title, a filename, and a numbered episode list, "
    "identify which episode the file belongs to. "
    "Reply with ONLY a compact JSON object: "
    '{"season": <integer or null>, "episode": <integer or null>}. '
    "Use null for season or episode if you cannot determine the match. "
    "No other text, no markdown, no explanation."
)

_LLM_MATCH_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "episode_match",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "season": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "episode": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["season", "episode"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class MatchResult:
    """Result of a file-to-episode matching operation."""

    files_matched: int
    matched_by_heuristic: int
    matched_by_llm: int
    files_unmatched: int
    files_failed: int
    dry_run: bool


class MatchOrchestrator:
    """Match DOWNLOADED files to Episode rows using regex heuristics, then LLM.

    Args:
        session: Active async SQLAlchemy session.
        llm: Optional LLMService; LLM matching is skipped if None or unavailable.
    """

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMService | None = None,
    ) -> None:
        self.session = session
        self.llm = llm

    @staticmethod
    def _heuristic_match(filename: str) -> tuple[int, int] | None:
        """Return (season, episode) from filename using regex, or None.

        Args:
            filename: The filename to parse.

        Returns:
            Tuple of (season_number, episode_number) or None if no pattern matches.
        """
        for pattern in _EP_PATTERNS:
            m = pattern.search(filename)
            if m:
                return int(m.group(1)), int(m.group(2))
        return None

    async def _llm_match(
        self,
        filename: str,
        show_title: str,
        episodes: list[Episode],
    ) -> tuple[int, int] | None:
        """Ask LLM to identify (season, episode) from filename.

        Args:
            filename: The filename to match.
            show_title: Title of the show for context.
            episodes: List of known episodes to match against.

        Returns:
            Tuple of (season_number, episode_number) or None if unavailable or unknown.
        """
        if self.llm is None or not self.llm.is_available():
            return None

        ep_list = "\n".join(
            f"S{ep.season_number:02d}E{ep.episode_number:02d}: {ep.name}" for ep in episodes[:500]
        )
        prompt = f"Show: {show_title}\nFilename: {filename}\n\nEpisodes:\n{ep_list}"

        response = await self.llm.complete(
            prompt=prompt,
            system=_LLM_SYSTEM,
            response_format=_LLM_MATCH_RESPONSE_FORMAT,
        )
        if response is None:
            return None

        text = response.content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text).rstrip("`").strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON for match of %r: %r", filename, text)
            return None

        if not isinstance(parsed, dict):
            logger.warning("LLM returned non-dict JSON for match of %r: %r", filename, text)
            return None

        raw_season = parsed.get("season")
        raw_episode = parsed.get("episode")
        if raw_season is None or raw_episode is None:
            return None
        try:
            return int(raw_season), int(raw_episode)
        except (TypeError, ValueError):
            logger.warning("LLM returned non-integer S/E for %r: %r", filename, parsed)
            return None

    async def run(
        self,
        show_id: int | None = None,
        dry_run: bool = False,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> MatchResult:
        """Match all DOWNLOADED files to Episode rows.

        Sets file.status = ROUTED and episode.file_tracked = True on success.
        Sets file.status = ERROR on failure or no match found.

        Args:
            show_id: Limit to one show. None processes all shows.
            dry_run: Log results without writing to DB.
            on_progress: Optional async callback(current, total, message).
                May raise TaskCancelledError; propagates uncaught.

        Returns:
            MatchResult with counts.
        """
        stmt = (
            select(DownloadedFile, Show)
            .join(Show, DownloadedFile.show_id == Show.id)
            .where(
                (DownloadedFile.status == FileStatus.DOWNLOADED)
                | (DownloadedFile.status == FileStatus.ERROR)
            )
        )
        if show_id is not None:
            stmt = stmt.where(DownloadedFile.show_id == show_id)

        rows = list((await self.session.execute(stmt)).all())
        total = len(rows)

        # Pre-load episodes per show to avoid N+1 queries.
        # Also build a (season, episode) → Episode index per show for O(1) lookup.
        # When two episodes share identical (season, episode) numbers (rare specials),
        # the first occurrence wins — matching next() / linear-scan behaviour.
        show_ids = {show.id for _, show in rows}
        episodes_by_show: dict[int, list[Episode]] = {}
        episode_index_by_show: dict[int, dict[tuple[int, int], Episode]] = {}
        for sid in show_ids:
            ep_stmt = select(Episode).where(Episode.show_id == sid)
            eps = list((await self.session.execute(ep_stmt)).scalars().all())
            episodes_by_show[sid] = eps
            index: dict[tuple[int, int], Episode] = {}
            for e in eps:
                key = (e.season_number, e.episode_number)
                if key not in index:
                    index[key] = e
            episode_index_by_show[sid] = index

        files_matched = 0
        matched_by_heuristic = 0
        matched_by_llm = 0
        files_unmatched = 0
        files_failed = 0

        for idx, (file, show) in enumerate(rows, 1):
            if on_progress:
                await on_progress(idx, total, f"Matching {file.original_filename}")

            episodes = episodes_by_show.get(show.id, [])

            if dry_run:
                se = self._heuristic_match(file.original_filename)
                if se is not None:
                    logger.info("[DRY RUN] Would match %s via heuristic", file.original_filename)
                    files_matched += 1
                elif self.llm and self.llm.is_available():
                    logger.info("[DRY RUN] Would attempt LLM match for %s", file.original_filename)
                    files_matched += 1
                else:
                    logger.info(
                        "[DRY RUN] No match strategy available for %s", file.original_filename
                    )
                    files_unmatched += 1
                continue

            file.status = FileStatus.ROUTING
            await self.session.flush()

            try:
                season: int | None = None
                episode_num: int | None = None
                matched_by: MatchedBy | None = None

                se = self._heuristic_match(file.original_filename)
                if se is not None:
                    season, episode_num = se
                    matched_by = MatchedBy.HEURISTIC
                elif episodes:
                    se = await self._llm_match(file.original_filename, show.title, episodes)
                    if se is not None:
                        season, episode_num = se
                        matched_by = MatchedBy.LLM

                if season is not None and episode_num is not None:
                    ep = episode_index_by_show.get(show.id, {}).get((season, episode_num))
                    if ep is not None:
                        old_episode_id = (
                            file.episode_id
                            if file.episode_id is not None and file.episode_id != ep.id
                            else None
                        )
                        file.episode_id = ep.id
                        file.matched_by = matched_by
                        file.status = FileStatus.ROUTED
                        await self.session.execute(
                            OrphanedTrackingRecord.__table__.delete().where(  # type: ignore[attr-defined]
                                OrphanedTrackingRecord.downloaded_file_id == file.id
                            )
                        )
                        mark_episode_tracked(ep, file.original_filename, "match")
                        if old_episode_id is not None:
                            count_result = await self.session.execute(
                                select(func.count()).where(
                                    DownloadedFile.episode_id == old_episode_id
                                )
                            )
                            if (count_result.scalar() or 0) == 0:
                                old_ep_result = await self.session.execute(
                                    select(Episode).where(Episode.id == old_episode_id)
                                )
                                old_ep = old_ep_result.scalar_one_or_none()
                                if old_ep is not None:
                                    clear_episode_tracking(old_ep)
                        files_matched += 1
                        if matched_by == MatchedBy.HEURISTIC:
                            matched_by_heuristic += 1
                        else:
                            matched_by_llm += 1
                    else:
                        file.status = FileStatus.ERROR
                        file.error_message = (
                            f"S{season:02d}E{episode_num:02d} not found in episode list"
                        )
                        files_unmatched += 1
                else:
                    file.status = FileStatus.ERROR
                    file.error_message = "Could not determine season/episode from filename"
                    files_unmatched += 1

            except Exception as exc:
                logger.error("Failed to match %s: %s", file.original_filename, exc)
                file.status = FileStatus.ERROR
                file.error_message = str(exc)
                files_failed += 1

            await self.session.flush()

        await self.session.commit()

        logger.info(
            "Match complete: %d matched (%d heuristic, %d llm), %d unmatched, %d failed",
            files_matched,
            matched_by_heuristic,
            matched_by_llm,
            files_unmatched,
            files_failed,
        )
        return MatchResult(
            files_matched=files_matched,
            matched_by_heuristic=matched_by_heuristic,
            matched_by_llm=matched_by_llm,
            files_unmatched=files_unmatched,
            files_failed=files_failed,
            dry_run=dry_run,
        )
