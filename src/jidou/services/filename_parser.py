"""Extracts show name, season, episode, and other metadata from a raw filename.

Two extraction strategies:

1. LLM (preferred) — sends the full filename to a configured LLM with a
   detailed structured-output prompt, using a fast regex anchor as a
   grounding hint. Produces the richest result: show name, season, episode,
   CRC32, content type, and a confidence score.
2. Heuristic regex fallback — used when no LLM is configured or available.
   Seven ordered patterns, most- to least-specific; never infers content
   type (that requires either the LLM or a subsequent TMDB lookup).

This module is intentionally dependency-free beyond ``LLMService`` — it has
no database or orchestrator-level knowledge, so both ``ParseOrchestrator``
(SFTP pipeline) and ``PathImportOrchestrator`` (path-list import) can share
one implementation instead of maintaining two copies of the same regex
patterns and LLM prompt that would inevitably drift apart.
"""

import functools
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path

from jidou.services.file_filters import (
    QUALITY_TOKENS,
    RELEASE_YEAR_MIN,
    RESOLUTION_TOKENS,
    release_year_max,
)
from jidou.services.llm_json import (
    NULLABLE_INT,
    NULLABLE_STRING,
    json_schema_format,
    optional_int,
    sanitize_for_prompt,
)
from jidou.services.llm_service import LLMService
from jidou.services.llm_structured import JsonCallFailure, request_json_object

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent / "prompts" / "parse_filename.txt"
_PARSE_SYSTEM: str = _PROMPT_FILE.read_text(encoding="utf-8")

# Fast-path regex: extract S/E before trying the LLM, as a grounding hint.
# Episodes take 1-4 digits: long-running shows have passed episode 1,000 (D20).
_SE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,4})"),
    re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,4})(?!\d)"),
]

# Heuristic parser — applied when no LLM is available.
_CRC32_PAT = re.compile(r"\[([0-9A-Fa-f]{8})\]")
_EXTENSION_PAT = re.compile(r"\.[a-z0-9]{2,4}$", re.IGNORECASE)
_BRACKETS_PAT = re.compile(r"[\[\(].*?[\]\)]")
# Strip common video quality/source/codec tokens that appear without brackets.
# These are frequently 3-digit numbers (480, 720) that would otherwise be
# misidentified as episode numbers by the bare-episode fallback patterns.
# Built from the token lists shared with path_parser (D21).
_QUALITY_PAT = re.compile(
    r"\b(?:" + "|".join(RESOLUTION_TOKENS) + r")(?:p|i)?"
    r"|\b(?:" + "|".join(re.escape(token) for token in QUALITY_TOKENS) + r")\b",
    re.IGNORECASE,
)
_DELIMITERS_PAT = re.compile(r"[_.]")
_WHITESPACE_PAT = re.compile(r"\s+")


@functools.cache
def _heuristic_patterns(max_year: int) -> tuple[re.Pattern[str], ...]:
    """Build the ordered heuristic patterns for a given release-year upper bound.

    Ordered from most- to least-specific; first match wins. Every episode
    capture takes 1-4 digits (D20). A number after an explicit marker
    (``S01E``, ``E``, ``Season``) is always an episode. A bare number, with no
    marker of its own, is skipped when it is a release year (1900 through
    *max_year*) or a resolution token, because those appear in filenames far
    more often than episode 1,000+. The end-anchored bare pattern runs BEFORE
    the mid-string one so that the rightmost number is preferred over an
    earlier number in the show title (e.g. "Show Part 2 - 05" → episode=5).

    Cached per year so the patterns compile once, yet the year bound still
    comes from the clock at call time.

    Args:
        max_year: Newest year treated as a release-year tag.

    Returns:
        The compiled patterns, in priority order.
    """
    excluded = [str(y) for y in range(RELEASE_YEAR_MIN, max_year + 1)] + list(RESOLUTION_TOKENS)
    # Rejects a whole excluded token; a longer number that merely starts with one still matches.
    guard = r"(?!(?:" + "|".join(excluded) + r")(?!\d))"
    bare = guard + r"\d{1,4}"
    # Mid-string only: a 4-digit number loses to any later bare number, so a number in the
    # show title ("The 4400 - 05 - Title") never beats the real 1-3 digit episode after it.
    bare_mid = guard + r"(?:\d{1,3}|\d{4}(?!.*[\s\-]\d))"
    return (
        # "2nd Season 04" / "1st Season 01"
        re.compile(
            r"(?P<name>.*?)[\s\-]+(?P<season>\d{1,2})(?:st|nd|rd|th)?[\s\-]+Season[\s\-]+(?P<episode>\d{1,4})",
            re.IGNORECASE,
        ),
        # S01E02
        re.compile(r"(?P<name>.*?)[\s\-]+[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,4})"),
        # S01 02 — the episode digits carry no marker of their own, so they are bare.
        re.compile(rf"(?P<name>.*?)[\s\-]+[Ss](?P<season>\d{{1,2}})[\s\-]+(?P<episode>{bare})"),
        # E02 (season optional)
        re.compile(
            r"(?P<name>.*?)(?:[\s\-]+[Ss](?P<season>\d{1,2}).*)?[\s\-]+[Ee](?P<episode>\d{1,4})"
        ),
        # bare episode at end of string (end-anchored — more specific than mid-string)
        re.compile(rf"(?P<name>.*?)[\s\-]+(?P<episode>{bare})$"),
        # bare episode number anywhere, optional v2 suffix
        re.compile(rf"(?P<name>.*?)[\s\-]+(?P<episode>{bare_mid})(?:v\d)?\b"),
        # S01E02 with leading space only
        re.compile(r"(?P<name>.*?)\s+[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,4})"),
    )


# JSON schema for structured LLM output (OpenAI response_format shape).
# Passed to OpenAI-compatible providers; Anthropic ignores it and relies on
# the system prompt text instead.
_PARSE_RESPONSE_FORMAT: dict[str, object] = json_schema_format(
    "filename_parse",
    {
        "show_name": NULLABLE_STRING,
        "season": NULLABLE_INT,
        "episode": NULLABLE_INT,
        "crc32": NULLABLE_STRING,
        "content_type": {
            "anyOf": [
                {"type": "string", "enum": ["anime", "tv", "movie"]},
                {"type": "null"},
            ]
        },
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
)


@dataclass
class FilenameParseResult:
    """Extracted metadata for one filename.

    Attributes:
        show_name: Extracted show title, or None if it couldn't be determined.
        season: Season number, or None (never inferred from a bare number).
        episode: Episode number, or None for non-episode assets.
        crc32: 8-character uppercase hex checksum, or None if absent/invalid.
        content_type: One of "anime" / "tv" / "movie", or None if uncertain.
            Always None for heuristic (non-LLM) results.
        confidence: 0.0-1.0. Fixed at 0.6 (pattern matched) or 0.1 (no match)
            for heuristic results; LLM results are self-scored per the prompt.
        llm_ok: True when this result came from a successful LLM call.
    """

    show_name: str | None
    season: int | None
    episode: int | None
    crc32: str | None
    content_type: str | None
    confidence: float
    llm_ok: bool


def extract_crc32(filename: str) -> str | None:
    """Return the 8-char uppercase CRC32 hex tag embedded in a filename, if any.

    Args:
        filename: Raw filename (basename or full path).

    Returns:
        8-char uppercase hex string, or None if no ``[XXXXXXXX]`` tag is present.
    """
    m = _CRC32_PAT.search(filename)
    return m.group(1).upper() if m else None


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
    crc32 = extract_crc32(filename)
    base = _EXTENSION_PAT.sub("", Path(filename).name)
    cleaned = _BRACKETS_PAT.sub("", base)
    cleaned = _QUALITY_PAT.sub("", cleaned)
    cleaned = _DELIMITERS_PAT.sub(" ", cleaned)
    cleaned = _WHITESPACE_PAT.sub(" ", cleaned).strip()
    return cleaned, crc32


def _heuristic_parse(filename: str) -> FilenameParseResult:
    """Parse a media filename into structured metadata using regex patterns only.

    Applies an ordered set of patterns (most- to least-specific) against the
    cleaned filename.  Falls back to the full cleaned string as the show name
    when no pattern matches.  CRC32 checksums embedded in bracket tags are
    extracted regardless of which pattern matches.

    Args:
        filename: Raw filename to parse.

    Returns:
        FilenameParseResult with content_type always None and llm_ok=False.
    """
    cleaned, crc32 = _clean_filename(filename)

    for idx, pattern in enumerate(_heuristic_patterns(release_year_max())):
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
            return FilenameParseResult(
                show_name=show_name,
                season=season,
                episode=episode,
                crc32=crc32,
                content_type=None,
                confidence=0.6,
                llm_ok=False,
            )

    logger.debug("Heuristic parse: no pattern matched, fallback name=%r CRC32=%s", cleaned, crc32)
    return FilenameParseResult(
        show_name=cleaned or None,
        season=None,
        episode=None,
        crc32=crc32,
        content_type=None,
        confidence=0.1,
        llm_ok=False,
    )


# Private-use placeholders for path separators (see parse_release_title).
_SLASH = "\ue000"
_BACKSLASH = "\ue001"


# Tracker release titles such as
# "Show Name - TV Series [2026] :: Web | MKV | h264 | 1080p | Episode 4 | Freeleech".
# The "::" separator is what distinguishes them from a filename; the name is
# everything before " - <kind> [year]".
_TRACKER_TITLE_PAT = re.compile(
    r"^(?P<name>.+?)\s+-\s+[A-Za-z][A-Za-z0-9 ]{0,30}?(?:\s*\[[^\]]*\])*\s*::\s*(?P<rest>.*)$"
)
_TRACKER_EPISODE_PAT = re.compile(r"\bEpisode\s+(\d{1,4})\b", re.IGNORECASE)


def _parse_tracker_title(title: str) -> FilenameParseResult | None:
    """Parse a ``Name - Kind [year] :: details | Episode N`` tracker title.

    The name is kept verbatim (including bracketed tokens such as ``[Re]``) so
    it can match a library title exactly.

    Args:
        title: Raw release title.

    Returns:
        FilenameParseResult, or None when *title* is not in tracker format.
    """
    m = _TRACKER_TITLE_PAT.match(title)
    if m is None:
        return None
    name = _WHITESPACE_PAT.sub(" ", m.group("name")).strip(" -_")
    if not name:
        return None
    ep = _TRACKER_EPISODE_PAT.search(m.group("rest"))
    return FilenameParseResult(
        show_name=name,
        season=None,
        episode=int(ep.group(1)) if ep else None,
        crc32=None,
        content_type=None,
        confidence=0.6,
        llm_ok=False,
    )


def parse_release_title(title: str) -> FilenameParseResult:
    """Heuristically parse an RSS/torrent release title (not a filesystem path).

    ``_heuristic_parse`` treats its input as a filename and takes the
    basename first, which would truncate a title such as ``"Fate/stay night -
    05"`` to ``"stay night - 05"``. Path separators are therefore swapped for
    placeholders that survive the filename cleanup and restored in the parsed
    name, so the result is still ``"Fate/stay night"`` and matches a library
    show of that exact title. Regex only — no LLM call — so it is cheap enough
    to run on every entry of a feed.

    Args:
        title: Raw release title as published in a feed entry.

    Returns:
        FilenameParseResult with content_type always None and llm_ok=False.
    """
    tracker = _parse_tracker_title(title)
    if tracker is not None:
        return tracker
    result = _heuristic_parse(title.replace("/", _SLASH).replace("\\", _BACKSLASH))
    if result.show_name:
        restored = result.show_name.replace(_SLASH, "/").replace(_BACKSLASH, "\\")
        result = replace(result, show_name=restored)
    return result


def heuristic_se(filename: str) -> tuple[int, int] | None:
    """Return (season, episode) via regex, or None if no match."""
    for pattern in _SE_PATTERNS:
        m = pattern.search(filename)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


async def parse_filename(
    filename: str,
    llm: LLMService | None = None,
) -> FilenameParseResult:
    """Extract show name, season, episode, CRC32, and content type from a filename.

    Runs a fast regex anchor first (season, episode) as a grounding hint.
    If an LLM is configured and available, sends the full filename for a
    structured parse (see ``services/prompts/parse_filename.txt`` for the
    detailed extraction rules); otherwise, or on any LLM failure, falls back
    to a 7-pattern heuristic regex parse.

    Args:
        filename: Raw filename to parse (basename or full path).
        llm: Optional LLMService; without it (or if unavailable) only the
            heuristic path runs.

    Returns:
        FilenameParseResult with the extracted fields.
    """
    if llm is None or not llm.is_available():
        return _heuristic_parse(filename)

    regex_hint = heuristic_se(filename)
    hint_line = ""
    if regex_hint is not None:
        hint_line = f"\nRegex anchor detected: season={regex_hint[0]} episode={regex_hint[1]}"

    result = await request_json_object(
        llm,
        prompt=f"Given this filename: {sanitize_for_prompt(filename)}{hint_line}",
        system=_PARSE_SYSTEM,
        response_format=_PARSE_RESPONSE_FORMAT,
    )
    if result.error is not None:
        # Unlike the other structured callers, parse_filename has never swallowed
        # provider exceptions; callers rely on them propagating.
        raise result.error
    if result.failure is JsonCallFailure.NO_RESPONSE:
        logger.warning("LLM returned no response for %r; falling back to heuristic", filename)
        return _heuristic_parse(filename)

    parsed = result.data
    if parsed is None:
        # Invalid JSON and a non-object root share one fallback and one message.
        logger.warning(
            "LLM returned non-object JSON for %r: %r; falling back to heuristic",
            filename,
            result.content,
        )
        return _heuristic_parse(filename)

    if reasoning := parsed.get("reasoning"):
        logger.debug("LLM reasoning for %r: %s", filename, reasoning)

    try:
        season = optional_int(parsed.get("season"))
        episode = optional_int(parsed.get("episode"))
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        logger.warning("LLM returned non-numeric S/E/confidence for %r: %r", filename, parsed)
        return _heuristic_parse(filename)

    return FilenameParseResult(
        show_name=parsed.get("show_name"),
        season=season,
        episode=episode,
        crc32=parsed.get("crc32"),
        content_type=parsed.get("content_type"),
        confidence=confidence,
        llm_ok=True,
    )
