"""Resolve a show's default local (container-side) path from its content type."""

from pathlib import PurePosixPath


def resolve_show_local_path(
    *,
    content_type: str | None,
    media_type: str | None,
    sys_name: str,
    local_tv_path: str,
    local_anime_path: str,
    local_movie_path: str,
) -> str:
    """Compute the default local path for a show from configured media roots.

    Priority chain: *content_type* -> *media_type* -> default ``"tv"``. A
    show's own ``content_type`` classification (when set) is always
    authoritative over the coarser TMDB ``media_type``.

    Args:
        content_type: One of ``"anime"``, ``"movie"``, ``"tv"``, or None.
        media_type: TMDB media type (``"movie"`` or ``"tv"``), used as a
            fallback when *content_type* is unset. May be None.
        sys_name: Filesystem-safe show directory name.
        local_tv_path: Base directory for live-action TV series.
        local_anime_path: Base directory for anime series.
        local_movie_path: Base directory for movies.

    Returns:
        Absolute container-side path string.
    """
    ct = content_type or media_type or "tv"
    if ct == "movie":
        base = local_movie_path
    elif ct == "anime":
        base = local_anime_path
    else:
        base = local_tv_path
    # PurePosixPath ensures forward slashes — these are always Linux container paths.
    return str(PurePosixPath(base) / sys_name)
