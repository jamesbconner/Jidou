"""File and directory filtering for SFTP scans.

Centralises the rules for which remote files and directories should be
included when scanning.  The same rules are applied during both listing
(``SFTPService.list_remote_files_recursive``) and any future pre-download
validation pass.
"""

import os
from datetime import datetime

EXCLUDED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".nfo",
        ".sfv",
        ".txt",
        ".idx",
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


def is_valid_media_file(name: str) -> bool:
    """Return True if *name* should be included in a scan result.

    A file is excluded when its extension is in ``EXCLUDED_EXTENSIONS`` or any
    keyword from ``EXCLUDED_KEYWORDS`` appears in the lower-cased filename.

    Args:
        name: Bare filename (not a full path).

    Returns:
        True when the file should be kept; False when it should be skipped.
    """
    lower = name.lower()
    ext = os.path.splitext(lower)[1]
    if ext in EXCLUDED_EXTENSIONS:
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
