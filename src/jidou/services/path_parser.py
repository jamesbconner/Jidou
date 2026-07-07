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

# NxNN / NNxNN — common release-group format (e.g. Criminal.Minds.01x01).
_SxE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,2})(?!\d)")

# "Season N Episode N" — long-form text label (e.g. "Breaking Bad Season 2 Episode 09").
_SEASON_EPISODE_WORD = re.compile(
    r"\bSeason\s+(\d{1,2})\b.*?\bEpisode\s+(\d{1,3})\b", re.IGNORECASE
)

# "Episode N" — standalone episode label (e.g. "Episode 11 - 25 to Life").
_EPISODE_WORD = re.compile(r"\bEpisode\s+(\d{1,3})\b", re.IGNORECASE)

# "Ep N" or "Ep. N" (Yawara-style).
_EP_WORD = re.compile(r"\bEp\.?\s*(\d{1,3})\b", re.IGNORECASE)

# "- N" followed by end-of-string or a quality/hash bracket.
# Handles SubsPlease, HorribleSubs, and plain "Show - 06".
_DASH_EP = re.compile(r"[-–]\s*(\d{1,3})\s*(?:$|[\(\[])")  # noqa: RUF001

# "N - Title" where N is the episode number *before* a title separator.
# Handles encoders that use "Show 01 - Episode Title [hash]" naming.
# Requires a letter immediately after the separator to avoid matching
# resolution strings or hashes that contain "NN - NN".
_PREDASH_EP = re.compile(r"(?<!\d)(\d{1,3})\s+[-–]\s+[A-Za-z]")  # noqa: RUF001

# "N - Title" at start of stem where the title begins with a digit or word
# (e.g. "32 - 100th Dirty Job Special", "19 - 200 Jobs Look-Back").
# More permissive than _PREDASH_EP; anchored to ^ to limit false positives.
_LEADING_EP = re.compile(r"^(\d{1,3})\s+[-–]\s+")  # noqa: RUF001

# "Title NN" — a bare trailing 1-2 digit number with nothing but whitespace
# separating it from the title (e.g. "Bamboo Blade 20", "Yawara 6"). No dash,
# no keyword, just a space. \b requires the digits be preceded by a
# non-word character (so "v2" or "S02" — glued directly to a letter — never
# match), and the "season" lookbehind excludes a lone trailing season number
# with no episode (e.g. "Show Season 2"). Limited to 1-2 digits so it can
# never collide with the 3-4 digit compact SEEE/SSEEE heuristic below.
_BARE_TRAILING_EP = re.compile(r"(?<!season\s)\b(\d{1,2})$", re.IGNORECASE)

# Non-credit opening/ending and other bonus-content markers (e.g.
# "Show NCOP 01", "Show OVA 2"). A trailing number after one of these is a
# clip/disc index, not an episode number — _BARE_TRAILING_EP must not fire
# for these so the file falls through to the LLM, whose prompt explicitly
# treats these tokens as non-episode content.
_NON_EPISODE_ASSET_WORD = re.compile(r"\b(NCED|NCOP|OP|ED|PV|CM|SP|OVA|OAD)\b", re.IGNORECASE)

# Compact SEEE / SSEEE — episode and season run together without a delimiter
# (e.g. criminal.minds.201 → S02E01, criminal.minds.1001 → S10E01).
# Applied last because it is the most ambiguous pattern.
_COMPACT_EP = re.compile(r"\b(\d{3,4})\b")
_COMPACT_QUALITY = frozenset({"480", "576", "720", "1080", "2160", "4320"})

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


def _relative_parts(path: PurePath, root: str) -> tuple[str, ...] | None:
    """Return ``path``'s parts relative to ``root``, or None if it isn't under it.

    Args:
        path: The full file path.
        root: The configured library root (host-side path string).

    Returns:
        Tuple of path segments below ``root``, or None when ``path`` doesn't
        fall under ``root`` (including a path-style mismatch, e.g. root given
        as a POSIX path while the line is Windows-style).
    """
    try:
        root_path = _as_pure_path(root)
        return path.relative_to(root_path).parts
    except (ValueError, TypeError):
        return None


def parse_line(line: str, root: str | None = None) -> ParsedPathEntry | None:
    """Parse one line from a path file into a structured entry.

    Skips blank lines and comment lines (starting with ``#``).  Accepts both
    Windows (``Z:\\...``) and POSIX (``/mnt/...``) absolute paths.

    Args:
        line: A single line from the path file, possibly with surrounding whitespace.
        root: Configured library root for this import's content type (e.g.
            ``settings.local_anime_host_path``). When given and the line falls
            under it, ``show_dir`` is anchored to the first path segment below
            ``root`` — regardless of how many extra directories (bonus
            content, OVA folders, anything not named ``Season N``) sit between
            it and the file. When omitted, or the line doesn't fall under
            ``root``, falls back to treating the file's immediate parent
            directory as the show directory (or its grandparent, if the
            immediate parent looks like ``Season N``).

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

    rel_parts = _relative_parts(path, root) if root else None

    if rel_parts is not None and len(rel_parts) >= 2:
        # Anchored resolution: the first segment below the configured library
        # root is the show directory, no matter what's nested beneath it.
        # A "Season N" match can appear at any depth in between.
        show_dir = rel_parts[0]
        show_root = str(path.parents[len(rel_parts) - 2])
        dir_season = None
        for seg in rel_parts[1:-1]:
            season_match = _SEASON_DIR.match(seg)
            if season_match:
                dir_season = int(season_match.group(1))
                break
    else:
        # Fallback: infer the show directory from the file's immediate
        # parent (or grandparent, if the parent looks like "Season N").
        second_to_last = parts[-2]
        season_match = _SEASON_DIR.match(second_to_last)
        if season_match:
            dir_season = int(season_match.group(1))
            show_dir = parts[-3]
            show_root = str(path.parent.parent)
        else:
            dir_season = None
            show_dir = parts[-2]
            show_root = str(path.parent)

    stem = path.stem
    fn_season, episode = _parse_episode(stem, dir_season=dir_season)

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


def parse_file(content: str, root: str | None = None) -> list[ParsedPathEntry]:
    """Parse every line of a path file.

    Args:
        content: Full text content of the path file (``\\n``-separated lines).
        root: Configured library root for this import's content type; see
            :func:`parse_line` for how it anchors show directory resolution.

    Returns:
        List of successfully parsed entries; blank/comment/non-media lines skipped.
    """
    entries: list[ParsedPathEntry] = []
    for line in content.splitlines():
        entry = parse_line(line, root=root)
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


def _parse_episode(stem: str, dir_season: int | None = None) -> tuple[int | None, int | None]:
    """Extract (season, episode) from a filename stem (no extension).

    Priority order (first match wins):
    1. ``SxxExx`` / ``SxxEyyy`` standard notation.
    2. ``NNxNN`` release-group notation (e.g. ``01x01``).
    3. ``Season N … Episode N`` long-form text.
    4. ``Episode N`` standalone label.
    5. ``Ep N`` / ``Ep. N`` short label.
    6. ``- N`` at end-of-string or before a bracket.
    7. ``N - Title`` where title starts with a letter.
    8. ``N - Title`` at start of stem (title may start with a digit).
    9. Bare ``Title NN`` — a trailing 1-2 digit number with only whitespace
       separating it from the title, no dash or keyword (e.g. "Show 06").
       Skipped when the stem contains a non-episode asset marker (NCED,
       NCOP, OP, ED, PV, CM, SP, OVA, OAD) — those fall through to the LLM,
       whose prompt knows to treat them as non-episode content instead of a
       numbered episode.
    10. Compact ``SEEE`` / ``SSEEE`` (e.g. ``201`` → S02E01) — last resort.
        Tokens whose encoded season disagrees with ``dir_season`` are skipped
        to prevent cross-season mismatches (e.g. ``924`` under ``Season 10``
        would otherwise yield S10E24 instead of remaining unmatched).

    Args:
        stem: Filename without extension.
        dir_season: Season already known from the directory name, if any.
            Used only to guard the ambiguous compact-code path.

    Returns:
        ``(season, episode)`` where either value may be ``None``.
    """
    m = _SE_PATTERN.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = _SxE_PATTERN.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = _SEASON_EPISODE_WORD.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = _EPISODE_WORD.search(stem)
    if m:
        return None, int(m.group(1))

    m = _EP_WORD.search(stem)
    if m:
        return None, int(m.group(1))

    m = _DASH_EP.search(stem)
    if m:
        return None, int(m.group(1))

    m = _PREDASH_EP.search(stem)
    if m:
        return None, int(m.group(1))

    m = _LEADING_EP.search(stem)
    if m:
        return None, int(m.group(1))

    if not _NON_EPISODE_ASSET_WORD.search(stem):
        m = _BARE_TRAILING_EP.search(stem)
        if m:
            return None, int(m.group(1))

    for cm in _COMPACT_EP.finditer(stem):
        raw = cm.group(1)
        if raw in _COMPACT_QUALITY:
            continue
        n = int(raw)
        if 1900 <= n <= 2030:
            continue
        s_num = int(raw[:-2])
        e_num = int(raw[-2:])
        if s_num >= 1 and e_num >= 1:
            if dir_season is not None and s_num != dir_season:
                continue
            return s_num, e_num

    return None, None
