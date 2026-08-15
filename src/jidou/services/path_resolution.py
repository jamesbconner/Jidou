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

    TV and anime shows get their own subdirectory (``base/sys_name``) since
    a season's worth of episodes needs somewhere to live. Movies resolve
    straight to ``local_movie_path`` with no per-title subdirectory --
    movie libraries are typically one flat file per title directly under
    the movies root, not a folder per movie -- so ``RouteOrchestrator``
    places the routed file directly in the shared root (see
    ``_final_path_for``'s ``is_movie`` branch). A movie that does need its
    own folder (e.g. one with extras) can still get one by setting
    ``show.local_path`` explicitly via the show detail page.

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
        # No sys_name subdirectory — see docstring above.
        return str(PurePosixPath(local_movie_path))
    elif ct == "anime":
        base = local_anime_path
    else:
        base = local_tv_path
    # PurePosixPath ensures forward slashes — these are always Linux container paths.
    return str(PurePosixPath(base) / sys_name)
