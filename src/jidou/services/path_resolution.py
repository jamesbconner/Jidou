"""Resolve a show's default local (container-side) path from its content type."""

from pathlib import PurePosixPath
from typing import Protocol

from jidou.services.sys_name import sanitize_sys_name


class AutoPathShow(Protocol):
    """The show fields :func:`auto_local_path_for` reads.

    Structural so the ``Show`` model (and test doubles) satisfy it without this
    service importing the model.
    """

    @property
    def content_type(self) -> str | None: ...
    @property
    def media_type(self) -> str | None: ...
    @property
    def sys_name(self) -> str | None: ...
    @property
    def title(self) -> str: ...


def library_root(content_type: str | None, *, tv: str, anime: str, movie: str) -> str:
    """Pick the library root for a content type from the three configured roots.

    Args:
        content_type: ``"movie"``, ``"anime"``, or anything else (including None).
        tv: Root used for TV and for any unrecognised or missing content type.
        anime: Root used for anime.
        movie: Root used for movies.

    Returns:
        The matching root, unchanged.
    """
    if content_type == "movie":
        return movie
    if content_type == "anime":
        return anime
    return tv


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
    base = library_root(ct, tv=local_tv_path, anime=local_anime_path, movie=local_movie_path)
    if ct == "movie":
        # No sys_name subdirectory — see docstring above.
        return str(PurePosixPath(base))
    # PurePosixPath ensures forward slashes — these are always Linux container paths.
    return str(PurePosixPath(base) / sys_name)


def auto_local_path_for(show: AutoPathShow, *, tv: str, anime: str, movie: str) -> str | None:
    """Return the ``local_path`` a show should get automatically, or None.

    The one auto-population rule shared by parse, path import and show
    creation. A path is only derived when the show's library is unambiguous:
    its own ``content_type`` is set, or TMDB says it is a movie. TMDB uses
    ``media_type="tv"`` for both TV and anime, so guessing a root from it would
    put an anime series under the TV library; such a show gets no path until
    its ``content_type`` is set.

    Callers decide *whether* to apply the result (e.g. never overwriting an
    existing ``local_path``); this only decides *what* it would be.

    Args:
        show: The show to place; reads ``content_type``, ``media_type``,
            ``sys_name`` and ``title``.
        tv: Container-side root for live-action TV.
        anime: Container-side root for anime.
        movie: Container-side root for movies.

    Returns:
        The container-side path, or None when the library is ambiguous.

    Examples:
        >>> from types import SimpleNamespace
        >>> roots = {"tv": "/tv", "anime": "/anime", "movie": "/movies"}
        >>> anime = SimpleNamespace(content_type="anime", media_type="tv", sys_name="X", title="X")
        >>> auto_local_path_for(anime, **roots)
        '/anime/X'
        >>> unknown = SimpleNamespace(content_type=None, media_type="tv", sys_name="X", title="X")
        >>> auto_local_path_for(unknown, **roots) is None
        True
    """
    if not show.content_type and show.media_type != "movie":
        return None
    # sys_name is pre-sanitized; fall back to the title with invalid chars replaced.
    dir_name = show.sys_name or sanitize_sys_name(show.title)
    return resolve_show_local_path(
        content_type=show.content_type,
        media_type=show.media_type,
        sys_name=dir_name,
        local_tv_path=tv,
        local_anime_path=anime,
        local_movie_path=movie,
    )
