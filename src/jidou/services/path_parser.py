"""Parser for episode file path lists.

Converts absolute paths — either Windows-style (``Z:\\anime tv\\Show\\Season 1\\ep.mkv``)
or POSIX-style (``/mnt/media/anime/Show/Season 1/ep.mkv``) — into structured
:class:`ParsedPathEntry` objects that carry the show directory name, season, and
episode numbers needed for TMDB/DB lookup.

Path format is detected automatically: a path containing ``\\`` or a drive-letter
prefix (``C:\\``) is parsed as a Windows path; everything else is treated as POSIX.
"""

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from jidou.services.file_filters import is_valid_directory, is_valid_media_file
from jidou.services.path_transport import encode_path_bytes

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

# A bare 3-4 digit token that looks like a scene-release year tag (e.g.
# "Show.Name.2024.1080p.WEB-DL.mkv" — a near-universal release convention) is
# excluded from the compact SxxExx guess below. The upper bound tracks the
# current year (plus headroom for near-future release dates) instead of a
# fixed cutoff, so it never silently goes stale.
_YEAR_EXCLUSION_MIN = 1900
_YEAR_EXCLUSION_HEADROOM_YEARS = 2

_MEDIA_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".flv", ".ts", ".m2ts"}
)


def _detect_season_from_segments(segments: Sequence[str]) -> int | None:
    """Return the season number from the first ``Season N`` segment, or None.

    Shared by :func:`parse_line` and :func:`scan_show_directory` so the two
    features can never drift apart on how a season directory is detected.

    Args:
        segments: Path segments to search, ordered outermost to innermost —
            the first match wins (an outer ``Season N`` folder takes priority
            over any ``Season N`` folder nested inside it).

    Returns:
        The season number, or None if no segment matches.
    """
    for seg in segments:
        season_match = _SEASON_DIR.match(seg)
        if season_match:
            return int(season_match.group(1))
    return None


def path_comparison_key(path_str: str, depth: int = 2) -> str:
    """Build a format-agnostic, case-insensitive key for comparing two paths.

    Two path strings can refer to the same physical file while having
    completely different, unrelated roots — e.g. a Windows-style path typed
    into a bulk-import text file (``Z:\\anime tv\\Show\\...``) versus the
    container's own POSIX view of the same file (``/data/media/anime/Show/...``).
    There is no invertible string transform between the two roots, so this
    only compares the trailing *depth* segments (parent directory name(s) plus
    filename) rather than the full path — a much weaker but achievable
    signal for "this is probably the same file" without needing the
    host/container path mapping.

    Args:
        path_str: A path string, Windows- or POSIX-style.
        depth: Number of trailing path segments to include in the key.

    Returns:
        A lower-cased, forward-slash-joined key built from the trailing
        *depth* segments (fewer if the path is shorter than *depth*).
    """
    path = _as_pure_path(path_str)
    parts = path.parts[-depth:] if len(path.parts) >= depth else path.parts
    return "/".join(p.lower() for p in parts)


@dataclass
class ParsedPathEntry:
    """A single episode file parsed from a path list line.

    Attributes:
        raw_path: The source line/path, run through
            :func:`~jidou.services.path_transport.encode_path_bytes`. Always
            the *encoded* form — decode with ``decode_path_bytes`` before any
            real filesystem access. Encoding both here and in
            :func:`scan_show_directory` keeps ``path_comparison_key`` matches
            consistent regardless of which feature a file was first tracked
            through (a filename with a literal ``%`` would otherwise compare
            unequal between an unencoded bulk-import record and a later scan).
        show_dir: Directory name used as the primary show identifier. Not
            encoded — unlike ``raw_path``, this can become ``show.local_path``
            (see ``PathImportOrchestrator``), which must stay a real,
            directly-usable filesystem path.
        show_root: Full path to the show's root directory (no season or filename).
        season: Season number inferred from the directory name or filename.
        episode: Episode number (may be absolute when ``is_absolute`` is True).
        is_absolute: True when no season information is available; the episode
            number should be treated as an absolute episode counter.
        absolute_candidate: Set only when ``season``/``episode`` came from the
            ambiguous compact SEEE/SSEEE heuristic (e.g. "212" guessed as
            S02E12) — holds the raw joined number as an alternate "this might
            just be a plain absolute episode number" interpretation, since
            shows with pure absolute numbering (e.g. One Piece) produce
            exactly this kind of filename with no season directory.
        is_directory: True when this entry came from a directory-only line
            (``shows_only`` import mode's ``directories_only`` parsing) rather
            than a real episode file — see :func:`_parse_directory_line`.
    """

    raw_path: str
    show_dir: str
    show_root: str
    season: int | None
    episode: int | None
    is_absolute: bool
    absolute_candidate: int | None = None
    is_directory: bool = False


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


def _parse_directory_line(path: PurePath, root: str | None) -> ParsedPathEntry | None:
    """Parse a directory-only line — a show location with no filename.

    Used for the ``shows_only`` import mode, where the input is a bare list of
    show directories rather than per-episode file paths — there's no filename
    to extract season/episode information from, so this entry exists purely
    so :class:`~jidou.orchestrators.path_import_orchestrator.PathImportOrchestrator`
    can resolve or create the show it names.

    Args:
        path: The line's directory path (trailing separator already stripped
            by :class:`~pathlib.PurePath` construction).
        root: Configured library root, or None — same anchoring rules as
            :func:`parse_line`.

    Returns:
        A :class:`ParsedPathEntry` with ``season``/``episode`` both None, or
        None if the line doesn't resolve to a usable directory (e.g. it *is*
        the root itself, with nothing below it).
    """
    rel_parts = _relative_parts(path, root) if root else None

    if rel_parts is not None and root is not None:
        if not rel_parts:
            # Line is exactly the configured root itself — nothing below it
            # to treat as a show directory.
            return None
        # Anchored: the first segment below the configured library root is
        # the show directory, even if this line points at a subdirectory
        # further inside it (e.g. a bonus-content folder).
        show_dir = rel_parts[0]
        show_root = str(_as_pure_path(root) / show_dir)
    else:
        # Fallback: no configured root, or the line doesn't fall under it —
        # the line already names the show's own directory.
        parts = path.parts
        if len(parts) < 2:
            return None
        show_dir = parts[-1]
        show_root = str(path)

    return ParsedPathEntry(
        raw_path=encode_path_bytes(str(path)),
        show_dir=show_dir,
        show_root=show_root,
        season=None,
        episode=None,
        is_absolute=False,
        is_directory=True,
    )


def parse_line(
    line: str, root: str | None = None, directories_only: bool = False
) -> ParsedPathEntry | None:
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
        directories_only: True for the ``shows_only`` import mode. The mode
            itself is the signal that a line names a show location, not a
            file — so any line that doesn't end in a recognized media
            extension is parsed as a bare show directory (trailing ``\\``/``/``
            optional; see :func:`_parse_directory_line`) instead of being
            rejected. A line that *does* end in a media extension is still
            parsed as a normal file — a directory-listing file and a
            per-episode file listing both work for this mode without
            needing separate formats. When False (``full``/``episodes_only``),
            every line must end in a recognized media extension, as before.

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

    is_media_file = path.suffix.lower() in _MEDIA_EXTENSIONS

    if directories_only and not is_media_file:
        return _parse_directory_line(path, root)

    # Need at least: root + show_dir + filename with one intermediate directory (4 parts).
    if len(parts) < 4:
        return None

    if not is_media_file:
        return None

    rel_parts = _relative_parts(path, root) if root else None

    if rel_parts is not None and len(rel_parts) >= 2:
        # Anchored resolution: the first segment below the configured library
        # root is the show directory, no matter what's nested beneath it.
        # A "Season N" match can appear at any depth in between.
        show_dir = rel_parts[0]
        show_root = str(path.parents[len(rel_parts) - 2])
        dir_season = _detect_season_from_segments(rel_parts[1:-1])
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
    fn_season, episode, absolute_candidate = _parse_episode(stem, dir_season=dir_season)

    # Season from directory takes precedence over season from filename.
    season = dir_season if dir_season is not None else fn_season
    is_absolute = season is None and episode is not None

    return ParsedPathEntry(
        raw_path=encode_path_bytes(line),
        show_dir=show_dir,
        show_root=show_root,
        season=season,
        episode=episode,
        is_absolute=is_absolute,
        absolute_candidate=absolute_candidate,
    )


def parse_file(
    content: str, root: str | None = None, directories_only: bool = False
) -> list[ParsedPathEntry]:
    """Parse every line of a path file.

    Args:
        content: Full text content of the path file (``\\n``-separated lines).
        root: Configured library root for this import's content type; see
            :func:`parse_line` for how it anchors show directory resolution.
        directories_only: True for the ``shows_only`` import mode; see
            :func:`parse_line`.

    Returns:
        List of successfully parsed entries; blank/comment/non-media lines skipped.
    """
    entries: list[ParsedPathEntry] = []
    for line in content.splitlines():
        entry = parse_line(line, root=root, directories_only=directories_only)
        if entry is not None:
            entries.append(entry)
    return entries


def _resolve_show_root(show_root: str) -> Path | None:
    """Resolve *show_root* to an actual on-disk directory.

    ``show_root`` (from ``Show.local_path``) is a clean UTF-8 string, but a
    directory that predates Jidou -- created by some other tool, e.g. an
    archive extractor or an older Windows/NAS workflow -- can have a name
    that's raw Latin-1/cp1252 bytes instead of UTF-8 for an accented
    character (cp1252 'é' is the single byte 0xE9; UTF-8 'é' is the two
    bytes 0xC3 0xA9). A plain ``Path(show_root).is_dir()`` then fails even
    though the directory is right there, because the byte sequences don't
    literally match. If the exact path isn't found, this falls back to
    scanning the parent directory for an entry whose raw on-disk bytes
    decode as cp1252 to the expected name.

    Args:
        show_root: Absolute container-side path to the show's own directory,
            as stored in the database.

    Returns:
        The resolved :class:`Path` (exact or cp1252-recovered), or ``None``
        if no matching directory exists.
    """
    exact = Path(show_root)
    if exact.is_dir():
        return exact

    parent = exact.parent
    if not parent.is_dir():
        return None

    target_name = exact.name
    for entry in parent.iterdir():
        if not entry.is_dir():
            continue
        raw = entry.name.encode("utf-8", errors="surrogateescape")
        try:
            if raw.decode("cp1252") == target_name:
                return entry
        except UnicodeDecodeError:
            continue
    return None


def scan_show_directory(show_root: str, recursive: bool = True) -> list[ParsedPathEntry]:
    """Walk an already-known show's own local directory and parse every media file.

    Unlike :func:`parse_line`, ``show_dir`` doesn't need to be inferred here —
    the caller already knows which show this directory belongs to (this is
    used by the show-scoped "scan local files" feature, not bulk path-import)
    — so this only needs season detection from any ``Season N`` ancestor
    directory and episode extraction from the filename, both reusing
    :func:`_parse_episode`/:func:`_detect_season_from_segments` so the two
    features never drift apart on parsing behavior. File and directory
    validity (extension allowlist, sample/screens/thumbs.db exclusion) reuses
    :mod:`~jidou.services.file_filters`, the same rules the SFTP scan
    pipeline already applies, so junk that's excluded there doesn't reappear
    as a scan candidate here.

    ``raw_path``/``show_dir``/``show_root`` are run through
    :func:`~jidou.services.path_transport.encode_path_bytes` — filenames on a
    POSIX filesystem aren't guaranteed to be valid UTF-8 (e.g. a legacy
    Latin-1/cp1252 name from an older Windows/NAS-authored library), and an
    unencoded surrogate would crash the API response. The encoding is
    lossless and reversible via ``decode_path_bytes``, so a confirmed match
    still resolves back to the exact file on disk.

    A directory that predates Jidou can also have a legacy Latin-1/cp1252-
    encoded name that doesn't literally byte-match ``show_root`` -- see
    :func:`_resolve_show_root`, which recovers it.

    The walk follows symlinked subdirectories (e.g. a season folder relocated
    to a different drive/mount and replaced with a symlink -- a common
    library-reorganization pattern). ``Path.rglob("*")`` was tried first, but
    pathlib's ``**`` matching never descends into a symlinked directory
    (true on every current Python version, not a 3.13-only regression) --
    it would silently scan only the seasons that are real directories. The
    SFTP scan pipeline (:meth:`~jidou.services.sftp_service.SFTPService.
    list_remote_files_recursive`) doesn't have this gap, since asyncssh's
    ``readdir`` resolves symlinks like any other directory -- ``os.walk``
    with ``followlinks=True`` brings local scanning in line with that. A
    directory's real (device, inode) identity is tracked as it's visited so
    a symlink cycle (e.g. one pointing back at an ancestor) is pruned
    instead of making the walk recurse forever.

    Args:
        show_root: Absolute container-side path to the show's own directory.
        recursive: When False, only list files directly in *show_root* —
            no descent into subdirectories at all. Used for movie libraries
            where ``show_root`` is the shared movies root rather than a
            directory exclusive to one title, so recursing would surface
            every other movie's files (and any of their own subfolders) as
            false candidates. Defaults to True (the TV/anime behavior,
            where ``show_root`` is exclusive to one show and season
            subdirectories must be descended into).

    Returns:
        List of :class:`ParsedPathEntry`, one per media file found, sorted
        by path. Empty if *show_root* doesn't exist or isn't a directory.
    """
    root = _resolve_show_root(show_root)
    if root is None:
        return []

    # root is invariant for the whole walk — encode its derived strings once
    # rather than redoing identical work for every matched file below.
    encoded_show_dir = encode_path_bytes(root.name)
    encoded_show_root = encode_path_bytes(str(root))

    file_paths: list[Path] = []
    if not recursive:
        try:
            for entry in root.iterdir():
                if entry.is_file() and is_valid_media_file(entry.name):
                    file_paths.append(entry)
        except OSError:
            return []
    else:
        # followlinks=True has no built-in cycle guard, so a symlink pointing
        # at an ancestor (or any symlink cycle) would otherwise make os.walk
        # recurse forever. Track each directory's real (device, inode)
        # identity the first time it's visited and prune any child that
        # resolves back to an already-seen identity before os.walk descends
        # into it again.
        visited_dirs: set[tuple[int, int]] = set()
        try:
            root_stat = root.stat()
        except OSError:
            return []
        visited_dirs.add((root_stat.st_dev, root_stat.st_ino))

        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            current_dir = Path(dirpath)
            kept_dirnames = []
            for name in dirnames:
                # Prune invalid directories (e.g. "Sample") before os.walk
                # descends into them, mirroring the SFTP walker's
                # skip-before-recursing rule in file_filters.is_valid_directory.
                if not is_valid_directory(name):
                    continue
                try:
                    child_stat = (current_dir / name).stat()
                except OSError:
                    continue
                identity = (child_stat.st_dev, child_stat.st_ino)
                if identity in visited_dirs:
                    continue
                visited_dirs.add(identity)
                kept_dirnames.append(name)
            dirnames[:] = kept_dirnames
            for filename in filenames:
                if is_valid_media_file(filename):
                    file_paths.append(current_dir / filename)

    entries: list[ParsedPathEntry] = []
    for file_path in sorted(file_paths):
        rel_parts = file_path.relative_to(root).parts
        dir_season = _detect_season_from_segments(rel_parts[:-1])

        fn_season, episode, absolute_candidate = _parse_episode(
            file_path.stem, dir_season=dir_season
        )
        season = dir_season if dir_season is not None else fn_season
        is_absolute = season is None and episode is not None

        entries.append(
            ParsedPathEntry(
                raw_path=encode_path_bytes(str(file_path)),
                show_dir=encoded_show_dir,
                show_root=encoded_show_root,
                season=season,
                episode=episode,
                is_absolute=is_absolute,
                absolute_candidate=absolute_candidate,
            )
        )
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


def _parse_episode(
    stem: str, dir_season: int | None = None
) -> tuple[int | None, int | None, int | None]:
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
        would otherwise yield S10E24 instead of remaining unmatched). The
        raw joined number is also returned as ``absolute_candidate`` since
        this guess is ambiguous — shows with pure absolute numbering (e.g.
        "One Piece 212") produce the same kind of bare 3-4 digit filename.

    Args:
        stem: Filename without extension.
        dir_season: Season already known from the directory name, if any.
            Used only to guard the ambiguous compact-code path.

    Returns:
        ``(season, episode, absolute_candidate)``. ``absolute_candidate`` is
        non-None only when the compact heuristic produced the guess.
    """
    m = _SE_PATTERN.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2)), None

    m = _SxE_PATTERN.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2)), None

    m = _SEASON_EPISODE_WORD.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2)), None

    m = _EPISODE_WORD.search(stem)
    if m:
        return None, int(m.group(1)), None

    m = _EP_WORD.search(stem)
    if m:
        return None, int(m.group(1)), None

    m = _DASH_EP.search(stem)
    if m:
        return None, int(m.group(1)), None

    m = _PREDASH_EP.search(stem)
    if m:
        return None, int(m.group(1)), None

    m = _LEADING_EP.search(stem)
    if m:
        return None, int(m.group(1)), None

    if not _NON_EPISODE_ASSET_WORD.search(stem):
        m = _BARE_TRAILING_EP.search(stem)
        if m:
            return None, int(m.group(1)), None

    for cm in _COMPACT_EP.finditer(stem):
        raw = cm.group(1)
        if raw in _COMPACT_QUALITY:
            continue
        n = int(raw)
        if _YEAR_EXCLUSION_MIN <= n <= date.today().year + _YEAR_EXCLUSION_HEADROOM_YEARS:
            continue
        s_num = int(raw[:-2])
        e_num = int(raw[-2:])
        if s_num >= 1 and e_num >= 1:
            if dir_season is not None and s_num != dir_season:
                continue
            return s_num, e_num, n

    return None, None, None
