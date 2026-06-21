"""Parser for episode file path lists.

Converts absolute paths — either Windows-style (``Z:\\anime tv\\Show\\Season 1\\ep.mkv``)
or POSIX-style (``/mnt/media/anime/Show/Season 1/ep.mkv``) — into structured
:class:`ParsedPathEntry` objects that carry the show directory name, season, and
episode numbers needed for TMDB/DB lookup.

Path format is detected automatically: a path containing ``\\`` or a drive-letter
prefix (``C:\\``) is parsed as a Windows path; everything else is treated as POSIX.
"""

import re
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath, PureWindowsPath

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
class ParsedPathEntry:
    """A single episode file parsed from a path list line.

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


def _as_pure_path(line: str) -> PurePath:
    """Return a Windows or POSIX PurePath based on the path format.

    Args:
        line: A single raw path string.

    Returns:
        :class:`~pathlib.PureWindowsPath` when the line contains a backslash or
        a drive-letter prefix; :class:`~pathlib.PurePosixPath` otherwise.
    """
    if "\\" in line or (len(line) >= 2 and line[1] == ":"):
        return PureWindowsPath(line)
    return PurePosixPath(line)


def parse_line(line: str) -> ParsedPathEntry | None:
    """Parse one line from a path file into a structured entry.

    Skips blank lines and comment lines (starting with ``#``).  Accepts both
    Windows (``Z:\\...``) and POSIX (``/mnt/...``) absolute paths.

    Args:
        line: A single line from the path file, possibly with surrounding whitespace.

    Returns:
        A :class:`ParsedPathEntry`, or None if the line should be ignored.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    try:
        path = _as_pure_path(line)
        parts = path.parts
    except Exception:
        return None

    # Need at least: root + show_dir + filename with one intermediate directory (4 parts).
    if len(parts) < 4:
        return None

    if path.suffix.lower() not in _MEDIA_EXTENSIONS:
        return None

    # Detect an optional "Season N" directory one level above the filename.
    second_to_last = parts[-2]
    season_match = _SEASON_DIR.match(second_to_last)

    if season_match:
        dir_season: int | None = int(season_match.group(1))
        show_dir = parts[-3]
        show_root = str(path.parent.parent)
    else:
        dir_season = None
        show_dir = parts[-2]
        show_root = str(path.parent)

    stem = path.stem
    fn_season, episode = _parse_episode(stem)

    # Season from directory takes precedence over season from filename.
    season = dir_season if dir_season is not None else fn_season
    is_absolute = season is None and episode is not None

    return ParsedPathEntry(
        raw_path=line,
        show_dir=show_dir,
        show_root=show_root,
        season=season,
        episode=episode,
        is_absolute=is_absolute,
    )


def parse_file(content: str) -> list[ParsedPathEntry]:
    """Parse every line of a path file.

    Args:
        content: Full text content of the path file (``\\n``-separated lines).

    Returns:
        List of successfully parsed entries; blank/comment/non-media lines skipped.
    """
    entries: list[ParsedPathEntry] = []
    for line in content.splitlines():
        entry = parse_line(line)
        if entry is not None:
            entries.append(entry)
    return entries


def group_by_show(
    entries: list[ParsedPathEntry],
) -> dict[str, list[ParsedPathEntry]]:
    """Group parsed entries by their show directory name.

    Args:
        entries: Flat list of parsed entries.

    Returns:
        Dict mapping show directory name → list of entries for that show,
        in the order they appeared in the source file.
    """
    groups: dict[str, list[ParsedPathEntry]] = {}
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
