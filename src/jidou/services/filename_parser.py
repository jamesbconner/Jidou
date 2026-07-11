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

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from jidou.services.llm_json import parse_llm_json, sanitize_for_prompt
from jidou.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent / "prompts" / "parse_filename.txt"
_PARSE_SYSTEM: str = _PROMPT_FILE.read_text(encoding="utf-8")

# Fast-path regex: extract S/E before trying the LLM, as a grounding hint.
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

# JSON schema for structured LLM output (OpenAI response_format shape).
# Passed to OpenAI-compatible providers; Anthropic ignores it and relies on
# the system prompt text instead.
_PARSE_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "filename_parse",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "show_name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "season": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "episode": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "crc32": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "content_type": {
                    "anyOf": [
                        {"type": "string", "enum": ["anime", "tv", "movie"]},
                        {"type": "null"},
                    ]
                },
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
            },
            "required": [
                "show_name",
                "season",
                "episode",
                "crc32",
                "content_type",
                "confidence",
                "reasoning",
            ],
            "additionalProperties": False,
        },
    },
}


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

    response = await llm.complete(
        prompt=f"Given this filename: {sanitize_for_prompt(filename)}{hint_line}",
        system=_PARSE_SYSTEM,
        response_format=_PARSE_RESPONSE_FORMAT,
    )
    if response is None:
        logger.warning("LLM returned no response for %r; falling back to heuristic", filename)
        return _heuristic_parse(filename)

    parsed = parse_llm_json(response.content)
    if not isinstance(parsed, dict):
        logger.warning(
            "LLM returned non-object JSON for %r: %r; falling back to heuristic",
            filename,
            response.content,
        )
        return _heuristic_parse(filename)

    if reasoning := parsed.get("reasoning"):
        logger.debug("LLM reasoning for %r: %s", filename, reasoning)

    raw_season = parsed.get("season")
    raw_episode = parsed.get("episode")
    try:
        season = int(raw_season) if raw_season is not None else None
        episode = int(raw_episode) if raw_episode is not None else None
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
