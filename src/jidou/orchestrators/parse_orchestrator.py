"""Orchestrator for parsing filenames and matching downloaded files to shows."""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent.parent / "services" / "prompts" / "parse_filename.txt"
_PARSE_SYSTEM: str = _PROMPT_FILE.read_text(encoding="utf-8")

# Fast-path regex: extract S/E before trying LLM.
# Captures (season, episode) from common SxxEyy / NxM patterns.
_SE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})"),
    re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)"),
]

# Heuristic parser — applied when no LLM is available.
_CRC32_PAT = re.compile(r"\[([0-9A-Fa-f]{8})\]")
_EXTENSION_PAT = re.compile(r"\.[a-z0-9]{2,4}$", re.IGNORECASE)
_BRACKETS_PAT = re.compile(r"[\[\(].*?[\]\)]")
# Strip common video quality/source/codec tokens that appear without brackets.
# These are frequently 3-digit numbers (480, 720) that would otherwise be
# misidentified as episode numbers by the bare-episode fallback patterns.
_QUALITY_PAT = re.compile(
    r"\b(?:480|576|720|1080|2160|4320)(?:p|i)?"
    r"|\b(?:4K|UHD|FHD|HD|SD|BluRay|BDRip|BRRip|DVDRip|WEBRip|WEB-DL|HDTV"
    r"|x264|x265|HEVC|AVC|AAC|AC3|DTS|FLAC|MP3|Remux|Repack|PROPER)\b",
    re.IGNORECASE,
)
_DELIMITERS_PAT = re.compile(r"[_.]")
_WHITESPACE_PAT = re.compile(r"\s+")

# Ordered from most- to least-specific; first match wins.
# Episode capture is capped at \d{1,3} (max 999) intentionally: 4-digit years
# (1080, 2024, etc.) appear in filenames far more often than shows with 1000+
# episodes, and false positives on years are worse than missing edge cases.
# End-anchored bare-episode pattern runs BEFORE the mid-string one so that
# the rightmost number is preferred over an earlier number in the show title
# (e.g. "Show Part 2 - 05" → episode=5, not episode=2).
_HEURISTIC_PATTERNS: list[re.Pattern[str]] = [
    # "2nd Season 04" / "1st Season 01"
    re.compile(
        r"(?P<name>.*?)[\s\-]+(?P<season>\d{1,2})(?:st|nd|rd|th)?[\s\-]+Season[\s\-]+(?P<episode>\d{1,3})",
        re.IGNORECASE,
    ),
    # S01E02
    re.compile(r"(?P<name>.*?)[\s\-]+[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,3})"),
    # S01 02
    re.compile(r"(?P<name>.*?)[\s\-]+[Ss](?P<season>\d{1,2})[\s\-]+(?P<episode>\d{1,3})"),
    # E02 (season optional)
    re.compile(
        r"(?P<name>.*?)(?:[\s\-]+[Ss](?P<season>\d{1,2}).*)?[\s\-]+[Ee](?P<episode>\d{1,3})"
    ),
    # bare episode at end of string (end-anchored — more specific than mid-string)
    re.compile(r"(?P<name>.*?)[\s\-]+(?P<episode>\d{1,3})$"),
    # bare episode number anywhere, optional v2 suffix
    re.compile(r"(?P<name>.*?)[\s\-]+(?P<episode>\d{1,3})(?:v\d)?\b"),
    # S01E02 with leading space only
    re.compile(r"(?P<name>.*?)\s+[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,3})"),
]

# Strips characters that are invalid on common filesystems (Windows + Linux).
_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


def _clean_filename(filename: str) -> tuple[str, str | None]:
    """Strip metadata noise from a filename and extract any CRC32 checksum.

    Removes the file extension, bracket/parenthesis tags (release group,
    resolution, codec, etc.), then normalises delimiters to spaces.

    Args:
        filename: Raw filename (basename or full path).

    Returns:
        Tuple of (cleaned_name, crc32) where crc32 is an 8-char uppercase
        hex string or None if no CRC32 tag was present.
    """
    crc32_m = _CRC32_PAT.search(filename)
    crc32 = crc32_m.group(1).upper() if crc32_m else None
    base = _EXTENSION_PAT.sub("", Path(filename).name)
    cleaned = _BRACKETS_PAT.sub("", base)
    cleaned = _QUALITY_PAT.sub("", cleaned)
    cleaned = _DELIMITERS_PAT.sub(" ", cleaned)
    cleaned = _WHITESPACE_PAT.sub(" ", cleaned).strip()
    return cleaned, crc32


def _heuristic_parse(filename: str) -> dict[str, object]:
    """Parse a media filename into structured metadata using regex patterns only.

    Applies an ordered set of patterns (most- to least-specific) against the
    cleaned filename.  Falls back to the full cleaned string as the show name
    when no pattern matches.  CRC32 checksums embedded in bracket tags are
    extracted regardless of which pattern matches.

    Args:
        filename: Raw filename to parse.

    Returns:
        Dict with keys ``show_name``, ``season``, ``episode``, ``crc32``,
        ``content_type``, ``confidence``, ``llm_ok``.
    """
    cleaned, crc32 = _clean_filename(filename)

    for idx, pattern in enumerate(_HEURISTIC_PATTERNS):
        m = pattern.search(cleaned)
        if m:
            groups = m.groupdict()
            show_name: str | None = groups.get("name", "").strip(" -_") or None
            season: int | None = int(groups["season"]) if groups.get("season") else None
            episode: int | None = int(groups["episode"]) if groups.get("episode") else None
            logger.debug(
                "Heuristic parse: show=%r S%sE%s CRC32=%s pattern=%d",
                show_name,
                season,
                episode,
                crc32,
                idx,
            )
            return {
                "show_name": show_name,
                "season": season,
                "episode": episode,
                "crc32": crc32,
                "content_type": None,
                "confidence": 0.6,
                "llm_ok": False,
            }

    logger.debug("Heuristic parse: no pattern matched, fallback name=%r CRC32=%s", cleaned, crc32)
    return {
        "show_name": cleaned or None,
        "season": None,
        "episode": None,
        "crc32": crc32,
        "content_type": None,
        "confidence": 0.1,
        "llm_ok": False,
    }


_CONFIDENCE_THRESHOLD = 0.7


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

    async def _llm_parse(
        self,
        filename: str,
        regex_hint: tuple[int, int] | None = None,
    ) -> dict[str, object]:
        """Ask the LLM to parse a media filename into structured metadata.

        The regex anchor (season, episode) extracted by ``_heuristic_se`` is
        included in the user message so the LLM can use it as a grounding
        signal rather than rediscovering structural tokens it is not better at.

        Args:
            filename: The raw filename to parse.
            regex_hint: Optional ``(season, episode)`` from ``_heuristic_se``,
                passed as context to reduce LLM hallucination on structured tokens.

        Returns:
            Dict with keys ``show_name``, ``season``, ``episode``,
            ``content_type``, ``confidence``; values may be None.
        """

        if self.llm is None or not self.llm.is_available():
            return _heuristic_parse(filename)

        hint_line = ""
        if regex_hint is not None:
            hint_line = f"\nRegex anchor detected: season={regex_hint[0]} episode={regex_hint[1]}"

        response = await self.llm.complete(
            prompt=f"Given this filename: {filename}{hint_line}",
            system=_PARSE_SYSTEM,
        )
        if response is None:
            logger.warning("LLM returned no response for %r; falling back to heuristic", filename)
            return _heuristic_parse(filename)

        text = response.content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text).rstrip("`").strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "LLM returned invalid JSON for %r: %r; falling back to heuristic",
                filename,
                text,
            )
            return _heuristic_parse(filename)

        if reasoning := parsed.get("reasoning"):
            logger.debug("LLM reasoning for %r: %s", filename, reasoning)

        raw_season = parsed.get("season")
        raw_episode = parsed.get("episode")
        return {
            "show_name": parsed.get("show_name"),
            "season": int(raw_season) if raw_season is not None else None,
            "episode": int(raw_episode) if raw_episode is not None else None,
            "content_type": parsed.get("content_type"),
            "confidence": float(parsed.get("confidence") or 0.0),
            "llm_ok": True,
        }

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
        dir_name = show.sys_name or _INVALID_FS_CHARS.sub("_", show.title).strip()
        # PurePosixPath ensures forward slashes — these are always Linux container paths.
        return str(PurePosixPath(base) / dir_name)

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
        llm_active = self.llm is not None and self.llm.is_available()

        for idx, file in enumerate(files, 1):
            if on_progress:
                await on_progress(idx, total, f"Parsing {file.original_filename}")

            try:
                # Stage 1a: regex anchors season/episode (fast, structural)
                se = _heuristic_se(file.original_filename)

                # Stage 1b: LLM parses show name + confirms/corrects S/E
                parsed = await self._llm_parse(file.original_filename, regex_hint=se)

                # Prefer LLM values; fall back to regex anchor if LLM missed them
                season: int | None = parsed.get("season") or (se[0] if se else None)  # type: ignore[assignment]
                episode: int | None = parsed.get("episode") or (se[1] if se else None)  # type: ignore[assignment]
                show_name: str | None = parsed.get("show_name")  # type: ignore[assignment]
                confidence: float = float(parsed.get("confidence") or 0.0)  # type: ignore[arg-type]
                content_type: str | None = parsed.get("content_type")  # type: ignore[assignment]
                llm_ok: bool = bool(parsed.get("llm_ok", False))

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
