"""Containment checks for client-supplied filesystem paths."""

from pathlib import Path


def is_within_directory(path: str, root: str) -> bool:
    """Return whether *path* resolves to a location inside *root*.

    Both arguments are resolved first (``..`` segments collapsed, symlinks
    followed), so traversal sequences and symlinks that point outside *root*
    are rejected. Neither path needs to exist. *root* itself counts as inside.

    Args:
        path: Client-supplied filesystem path, already decoded with
            :func:`~jidou.services.path_transport.decode_path_bytes`.
        root: Directory the path must stay within.

    Returns:
        ``True`` if the resolved *path* is *root* or a descendant of it;
        ``False`` otherwise, including when either path cannot be resolved
        (embedded NUL bytes, symlink loops, etc.).

    Examples:
        >>> is_within_directory("/media/movies/a.mkv", "/media/movies")
        True
        >>> is_within_directory("/media/movies/../etc/passwd", "/media/movies")
        False
    """
    try:
        resolved_root = Path(root).resolve()
        resolved_path = Path(path).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return resolved_path.is_relative_to(resolved_root)
