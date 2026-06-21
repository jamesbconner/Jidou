"""Parser for NAS file path lists.

Converts Windows-style absolute paths (e.g. ``Z:\\anime tv\\Show\\Season 1\\ep.mkv``)
into structured :class:`ParsedNASEntry` objects that carry the show directory
name, season, and episode numbers needed for TMDB/DB lookup.
"""

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath

# Matches directory names like "Season 1", "Season 01" (case-insensitive).
_SEASON_DIR = re.compile(r"^[Ss]eason\s+(\d{1,2})$")

# Standard SxxExx notation — always carries both season and episode.
_SE_PATTERN = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")

# "Ep N" or "Ep. N" (Yawara-style).
_EP_WORD = re.compile(r"\bEp\.?\s*(\d{1,3})\b", re.IGNORECASE)

# "- N" followed by end-of-string or a quality/hash bracket.
# Handles SubsPlease, HorribleSubs, and plain "Show - 06".
_DASH_EP = re.compile(r"[-–]\s*(\d{1,3})\s*(?:$|[\(\[])")  # noqa: RUF001

_MEDIA_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".flv", ".ts", ".m2ts"}
)


@dataclass
class ParsedNASEntry:
    """A single episode file parsed from a NAS path list line.

    Attributes:
        raw_path: The original unmodified line.
        show_dir: Directory name used as the primary show identifier.
        show_root: Full path to the show's root directory (no season or filename).
        season: Season number inferred from the directory name or filename.
        episode: Episode number (may be absolute when ``is_absolute`` is True).
        is_absolute: True when no season information is available; the episode
            number should be treated as an absolute episode counter.
    """

    raw_path: str
    show_dir: str
    show_root: str
    season: int | None
    episode: int | None
    is_absolute: bool


def parse_line(line: str) -> ParsedNASEntry | None:
    """Parse one line from a NAS path file into a structured entry.

    Skips blank lines and comment lines (starting with ``#``).

    Args:
        line: A single line from the path file, possibly with surrounding whitespace.

    Returns:
        A :class:`ParsedNASEntry`, or None if the line should be ignored.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    try:
        path = PureWindowsPath(line)
        parts = path.parts
    except Exception:
        return None

    # Need at least: drive + root_dir + show_dir + filename  (4 parts)
    if len(parts) < 4:
        return None

    filename = parts[-1]
    if PureWindowsPath(filename).suffix.lower() not in _MEDIA_EXTENSIONS:
        return None

    # Detect an optional "Season N" directory one level above the filename.
    second_to_last = parts[-2]
    season_match = _SEASON_DIR.match(second_to_last)

    if season_match:
        dir_season: int | None = int(season_match.group(1))
        show_dir = parts[-3]
        show_root = str(PureWindowsPath(*parts[:-2]))
    else:
        dir_season = None
        show_dir = parts[-2]
        show_root = str(PureWindowsPath(*parts[:-1]))

    stem = PureWindowsPath(filename).stem
    fn_season, episode = _parse_episode(stem)

    # Season from directory takes precedence over season from filename.
    season = dir_season if dir_season is not None else fn_season
    is_absolute = season is None and episode is not None

    return ParsedNASEntry(
        raw_path=line,
        show_dir=show_dir,
        show_root=show_root,
        season=season,
        episode=episode,
        is_absolute=is_absolute,
    )


def parse_file(content: str) -> list[ParsedNASEntry]:
    """Parse every line of a NAS path file.

    Args:
        content: Full text content of the path file (``\\n``-separated lines).

    Returns:
        List of successfully parsed entries; blank/comment/non-media lines skipped.
    """
    entries: list[ParsedNASEntry] = []
    for line in content.splitlines():
        entry = parse_line(line)
        if entry is not None:
            entries.append(entry)
    return entries


def group_by_show(
    entries: list[ParsedNASEntry],
) -> dict[str, list[ParsedNASEntry]]:
    """Group parsed entries by their show directory name.

    Args:
        entries: Flat list of parsed entries.

    Returns:
        Dict mapping show directory name → list of entries for that show,
        in the order they appeared in the source file.
    """
    groups: dict[str, list[ParsedNASEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.show_dir, []).append(entry)
    return groups


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_episode(stem: str) -> tuple[int | None, int | None]:
    """Extract (season, episode) from a filename stem (no extension).

    Priority:
    1. Standard ``SxxExx`` notation — returns both season and episode.
    2. ``Ep N`` / ``Ep. N`` word-boundary pattern.
    3. ``- N`` followed by end-of-string or a quality bracket.

    Args:
        stem: Filename without extension.

    Returns:
        ``(season, episode)`` where either value may be ``None``.
    """
    m = _SE_PATTERN.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = _EP_WORD.search(stem)
    if m:
        return None, int(m.group(1))

    m = _DASH_EP.search(stem)
    if m:
        return None, int(m.group(1))

    return None, None
