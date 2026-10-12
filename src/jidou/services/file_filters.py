"""File and directory filtering for SFTP scans.

Centralises the rules for which remote files and directories should be
included when scanning.  The same rules are applied during both listing
(``SFTPService.list_remote_files_recursive``) and any future pre-download
validation pass.

It also holds the filename tokens shared by ``filename_parser`` and
``path_parser`` (resolution and quality words, the release-year range), so the
two parsers cannot drift apart on what counts as noise rather than an episode.
"""

import os
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import PurePosixPath

# Allowlist, not a denylist: an SFTP source is commonly mixed-use (archives,
# subtitles, images, docs alongside the media itself), so excluding known-junk
# extensions let anything else — .rar, .zip, .srt, .docx, .xlsx, etc. — through
# uncontested. .srt/.ass are deliberately not included: most releases already
# embed subtitles in the container, so a loose .srt/.ass sidecar is rarely the
# file that should be tracked/downloaded.
MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mkv",
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".m4v",
        ".flv",
        ".ts",
        ".m2ts",
        ".iso",
        ".av1",
        ".ogm",
    }
)

EXCLUDED_KEYWORDS: frozenset[str] = frozenset(
    {
        "sample",
        "screens",
        "thumbs.db",
        ".ds_store",
    }
)

_UPLOAD_GRACE_SECONDS: int = 60

# Video heights that appear as bare numbers in release names ("1080p", "720").
# Shared by both filename parsers: stripped as quality noise, and never read as
# an episode number. Ordered because the parsers build regex alternations from it.
RESOLUTION_TOKENS: tuple[str, ...] = ("480", "576", "720", "1080", "2160", "4320")

# Source, codec and release-quality words stripped from a filename before the
# episode patterns run. Matched case-insensitively as whole words.
QUALITY_TOKENS: tuple[str, ...] = (
    "4K",
    "UHD",
    "FHD",
    "HD",
    "SD",
    "BluRay",
    "BDRip",
    "BRRip",
    "DVDRip",
    "WEBRip",
    "WEB-DL",
    "HDTV",
    "x264",
    "x265",
    "HEVC",
    "AVC",
    "AAC",
    "AC3",
    "DTS",
    "FLAC",
    "MP3",
    "Remux",
    "Repack",
    "PROPER",
)

# A bare 4-digit number in this range reads as a release-year tag (e.g.
# "Show.Name.2024.1080p.WEB-DL"), not an episode. The upper bound tracks the
# current year plus headroom for near-future release dates, so it never goes stale.
RELEASE_YEAR_MIN: int = 1900
RELEASE_YEAR_HEADROOM_YEARS: int = 2


def release_year_max() -> int:
    """Return the newest year treated as a release-year tag.

    Returns:
        The current year plus ``RELEASE_YEAR_HEADROOM_YEARS``, read from the
        clock on every call.
    """
    return date.today().year + RELEASE_YEAR_HEADROOM_YEARS


def is_release_year(n: int) -> bool:
    """Return True if *n* falls in the release-year range (1900 to current year + 2).

    Args:
        n: A bare number taken from a filename.

    Returns:
        True when the number should be read as a year, not an episode.
    """
    return RELEASE_YEAR_MIN <= n <= release_year_max()


def is_valid_media_file(name: str) -> bool:
    """Return True if *name* should be included in a scan result.

    A file is kept only when its extension is in ``MEDIA_EXTENSIONS`` and no
    keyword from ``EXCLUDED_KEYWORDS`` appears in the lower-cased filename.

    Args:
        name: Bare filename (not a full path).

    Returns:
        True when the file should be kept; False when it should be skipped.
    """
    lower = name.lower()
    ext = os.path.splitext(lower)[1]
    if ext not in MEDIA_EXTENSIONS:
        return False
    return not any(kw in lower for kw in EXCLUDED_KEYWORDS)


def is_valid_directory(name: str) -> bool:
    """Return True if *name* is a directory that should be recursed into.

    Directories containing any ``EXCLUDED_KEYWORDS`` keyword (e.g. ``screens``,
    ``sample``) are skipped entirely.

    Args:
        name: Bare directory name (not a full path).

    Returns:
        True when the directory should be descended; False to skip it.
    """
    lower = name.lower()
    return not any(kw in lower for kw in EXCLUDED_KEYWORDS)


def is_recently_modified(mtime: datetime, grace_seconds: int = _UPLOAD_GRACE_SECONDS) -> bool:
    """Return True if the file was modified within the upload grace window.

    Files modified within the last ``grace_seconds`` seconds are likely still
    being uploaded and should be skipped to avoid partial downloads.

    Args:
        mtime: File modification time (timezone-aware or naive; compared to
            ``datetime.now`` with the same tzinfo).
        grace_seconds: Seconds within which a file is considered in-flight.
            Defaults to 60.

    Returns:
        True when the file is too recent and should be skipped.
    """
    now = datetime.now(tz=mtime.tzinfo)
    elapsed = (now - mtime).total_seconds()
    # Negative elapsed means the SFTP host clock is ahead of ours. Treat that
    # as "not recently modified" so clock skew never blocks all downloads.
    return 0 <= elapsed < grace_seconds


def is_under_any_path(path: str, roots: Iterable[str]) -> bool:
    """Return True if *path* is equal to, or nested under, any of *roots*.

    Comparison is segment-aware, not a raw string prefix: root
    ``/downloads/doc`` matches ``/downloads/doc/movie.mkv`` but not
    ``/downloads/documentary/x.mkv`` (a naive ``str.startswith`` would
    wrongly match the latter).

    Args:
        path: Full remote path to test (typically a file path).
        roots: Candidate root paths.

    Returns:
        True if *path* falls under any root in *roots*.
    """
    segments = PurePosixPath(path).parts
    for root in roots:
        root_segments = PurePosixPath(root).parts
        if segments[: len(root_segments)] == root_segments:
            return True
    return False


def find_noscan_scan_overlaps(
    scan_paths: Iterable[str], noscan_paths: Iterable[str]
) -> list[tuple[str, str]]:
    """Find scan paths that are swallowed by a noscan path.

    A noscan path that is an ancestor of (or identical to) a configured scan
    path is almost certainly a misconfiguration: every file under that scan
    path — including real TV/movie content — would be silently excluded
    from matching. This does *not* flag the (intended, common) opposite
    case of a noscan path nested inside a scan path.

    Args:
        scan_paths: Configured SFTP paths that are scanned and matched.
        noscan_paths: Configured SFTP paths excluded from matching.

    Returns:
        ``(scan_path, noscan_path)`` pairs where *noscan_path* would swallow
        *scan_path*.
    """
    return [
        (scan_path, noscan_path)
        for scan_path in scan_paths
        for noscan_path in noscan_paths
        if is_under_any_path(scan_path, [noscan_path])
    ]
