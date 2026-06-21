"""Orchestrator for parsing filenames and matching downloaded files to shows."""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# Fast-path regex: extract S/E before trying LLM.
# Captures (season, episode) from common SxxEyy / NxM patterns.
_SE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})"),
    re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)"),
]

# Strips everything from the first S/E marker onward, then cleans separators.
# Used to derive a heuristic show name when no LLM is available.
_SHOW_NAME_STRIP = re.compile(r"[\.\s_-]*(?:[Ss]\d{1,2}[Ee]\d{1,3}|\d{1,2}[xX]\d{1,3}).*$")
_SHOW_NAME_CLEAN = re.compile(r"[\._]+")


def _heuristic_show_name(filename: str) -> str | None:
    """Extract a probable show name from a filename without an LLM.

    Strips the file extension, removes everything from the first S/E
    pattern onward, then converts separators to spaces.  Returns None
    if nothing remains after cleaning.

    Args:
        filename: Raw filename (may include a path).

    Returns:
        Best-effort show name, or None if it cannot be extracted.
    """
    stem = Path(filename).stem
    name = _SHOW_NAME_STRIP.sub("", stem).strip()
    name = _SHOW_NAME_CLEAN.sub(" ", name).strip()
    return name if name else None


_PARSE_SYSTEM = (
    "You are a media filename parser. "
    "Extract the show name, season number, episode number, "
    "content type (anime/tv/movie), and your confidence (0.0-1.0). "
    "Reply with ONLY valid JSON, no markdown, no extra text:\n"
    '{"show": "...", "season": N_or_null, "episode": N_or_null, '
    '"content_type": "anime"|"tv"|"movie"|null, "confidence": 0.0}\n'
    "For movies use season=null and episode=null. "
    "If the filename is not a media file or you cannot parse it, "
    'return {"show": null, "season": null, "episode": null,'
    ' "content_type": null, "confidence": 0.0}'
)


@dataclass
class ParseResult:
    """Result of a batch filename parse + show-match operation."""

    files_processed: int
    files_matched: int
    files_unmatched: int
    files_failed: int
    dry_run: bool


def _heuristic_se(filename: str) -> tuple[int, int] | None:
    """Return (season, episode) via regex, or None if no match."""
    for pattern in _SE_PATTERNS:
        m = pattern.search(filename)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def _sanitize_alias(name: str) -> str:
    """Normalise an alias name for case-insensitive storage and lookup."""
    return name.strip().lower()


class ParseOrchestrator:
    """Parse DOWNLOADED filenames and match to shows via alias lookup + LLM.

    Two-stage pipeline per file:
      1. LLM extracts ``show_name``, ``season``, ``episode``, and
         ``content_type`` from the raw filename.
      2. DB lookup: ``show.aliases`` contains the parsed name (case-folded),
         or ``show.title ILIKE`` as a fallback.

    On a successful match the parsed name is written back to
    ``show.aliases`` so future matches skip the LLM entirely.

    Args:
        session: Active async SQLAlchemy session.
        llm: Optional LLMService; without it only the heuristic path runs.
    """

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMService | None = None,
    ) -> None:
        self.session = session
        self.llm = llm

    async def _llm_parse(self, filename: str) -> dict[str, object]:
        """Ask the LLM to parse a media filename into structured metadata.

        Args:
            filename: The raw filename to parse.

        Returns:
            Dict with keys ``show``, ``season``, ``episode``,
            ``content_type``, ``confidence``; values may be None.
        """
        empty: dict[str, object] = {
            "show": None,
            "season": None,
            "episode": None,
            "content_type": None,
            "confidence": 0.0,
        }
        if self.llm is None or not self.llm.is_available():
            # No LLM: derive a show name heuristically so DB lookup can still run.
            heuristic = _heuristic_show_name(filename)
            return {**empty, "show": heuristic}

        response = await self.llm.complete(
            prompt=f"Filename: {filename}",
            system=_PARSE_SYSTEM,
        )
        if response is None:
            return empty

        text = response.content.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text).rstrip("`").strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON for %r: %r", filename, text)
            return empty

        raw_season = parsed.get("season")
        raw_episode = parsed.get("episode")
        return {
            "show": parsed.get("show"),
            # Coerce to int — LLM may return strings like "01" or floats like 1.0.
            "season": int(raw_season) if raw_season is not None else None,
            "episode": int(raw_episode) if raw_episode is not None else None,
            "content_type": parsed.get("content_type"),
            "confidence": float(parsed.get("confidence") or 0.0),
        }

    async def _find_show(self, parsed_name: str) -> Show | None:
        """Look up a show by alias list containment or title match.

        Args:
            parsed_name: The extracted show name (not yet normalised).

        Returns:
            Matching :class:`Show` or None if not found.
        """
        normalised = _sanitize_alias(parsed_name)

        # 1. Check if any show's aliases array contains this name (GIN-indexed).
        #    limit(1) + order_by(id) avoids MultipleResultsFound and gives a
        #    deterministic result when the alias appears on more than one show.
        alias_stmt = (
            select(Show)
            .where(Show.aliases.cast(JSONB).contains([normalised]))
            .order_by(Show.id)
            .limit(1)
        )
        show = (await self.session.execute(alias_stmt)).scalars().first()
        if show is not None:
            return show

        # 2. Case-insensitive title fallback — escape % and _ so parsed names that
        #    contain SQL wildcard characters do not match arbitrary shows.
        escaped = parsed_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        title_stmt = (
            select(Show)
            .where(Show.title.ilike(f"%{escaped}%", escape="\\"))
            .order_by(Show.id)
            .limit(1)
        )
        return (await self.session.execute(title_stmt)).scalars().first()

    async def _find_episode(
        self,
        show_id: int,
        season: int | None,
        episode: int | None,
    ) -> Episode | None:
        """Look up a specific episode, or return None."""
        if season is None or episode is None:
            return None
        stmt = select(Episode).where(
            (Episode.show_id == show_id)
            & (Episode.season_number == season)
            & (Episode.episode_number == episode)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _add_alias(show: Show, alias: str) -> None:
        """Add a normalised alias to show.aliases (in-place, no duplicate)."""
        norm = _sanitize_alias(alias)
        current: list[str] = list(show.aliases) if show.aliases else []
        if norm not in current:
            show.aliases = [*current, norm]

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

        for idx, file in enumerate(files, 1):
            if on_progress:
                await on_progress(idx, total, f"Parsing {file.original_filename}")

            try:
                # Stage 1: parse filename
                parsed = await self._llm_parse(file.original_filename)

                # Fill in season/episode via heuristic if LLM missed them
                se = _heuristic_se(file.original_filename)
                season: int | None = parsed.get("season") or (se[0] if se else None)  # type: ignore[assignment]
                episode: int | None = parsed.get("episode") or (se[1] if se else None)  # type: ignore[assignment]
                show_name: str | None = parsed.get("show")  # type: ignore[assignment]
                confidence: float = float(parsed.get("confidence") or 0.0)  # type: ignore[arg-type]
                content_type: str | None = parsed.get("content_type")  # type: ignore[assignment]

                if dry_run:
                    # Run the DB lookup so the count reflects real match potential,
                    # not just whether the parser extracted a show name.
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
                    if dry_show is not None:
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

                # Stage 2: DB lookup
                if show_name:
                    show = await self._find_show(show_name)
                else:
                    show = None

                if show is not None:
                    file.show_id = show.id
                    ep = await self._find_episode(show.id, season, episode)
                    file.episode_id = ep.id if ep is not None else None
                    file.matched_by = (
                        MatchedBy.LLM
                        if (self.llm is not None and self.llm.is_available())
                        else MatchedBy.HEURISTIC
                    )
                    file.status = FileStatus.MATCHED
                    # Teach the alias index so future matches skip LLM
                    if show_name:
                        self._add_alias(show, show_name)
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
