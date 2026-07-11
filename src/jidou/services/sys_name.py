"""Derive a filesystem-safe directory name (``Show.sys_name``) from a title."""

import re

_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')
_MULTIPLE_SPACES = re.compile(r"\s+")


def sanitize_sys_name(title: str) -> str:
    """Derive a Windows-safe directory name from a show title.

    Characters invalid in Windows paths are replaced with a space rather
    than dropped or replaced with an underscore, so ``"Re:Zero"`` becomes
    ``"Re Zero"``. Runs of whitespace this substitution can produce (e.g. a
    colon already followed by a space, as in ``"Show: Part Two"``) are
    collapsed to one.

    Args:
        title: The show title to sanitize.

    Returns:
        A filesystem-safe directory name derived from the title. Never
        empty -- a title consisting entirely of invalid characters (e.g.
        ``":::"``) would otherwise sanitize down to an empty string,
        which callers use to build ``local_path`` (``base_dir / sys_name``);
        an empty ``sys_name`` collapses that to the bare base directory
        with no show subdirectory at all.
    """
    replaced = _INVALID_FS_CHARS.sub(" ", title)
    sanitized = _MULTIPLE_SPACES.sub(" ", replaced).strip()
    return sanitized or "Untitled"
