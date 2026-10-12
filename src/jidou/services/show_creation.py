"""Pure helpers for creating a library show from TMDB data.

Content-type inference and default local-path computation. The create-or-get
workflow itself lives in ``jidou.orchestrators.show_creation_orchestrator``.
"""

from typing import Protocol

from jidou.services.path_resolution import resolve_show_local_path


class ContentTypeInputs(Protocol):
    """The TMDB metadata :func:`infer_content_type` reads.

    Structural so both the HTTP ``ShowCreate`` schema and the orchestrator's
    ``ShowSeed`` satisfy it without this service importing either.
    """

    @property
    def media_type(self) -> str: ...
    @property
    def genres(self) -> list[dict[str, object]] | None: ...
    @property
    def genre_ids(self) -> list[int] | None: ...
    @property
    def original_language(self) -> str | None: ...
    @property
    def origin_country(self) -> list[str] | None: ...


# TMDB genre ID 16 = Animation
_ANIMATION_GENRE_ID = 16


def infer_content_type(payload: ContentTypeInputs) -> str:
    """Infer routing content type from TMDB metadata.

    Rules (applied in order):
    - ``movie`` media type → ``"movie"``
    - Animation genre AND (Japanese language OR JP origin) → ``"anime"``
    - Everything else → ``"tv"``

    Accepts both TMDB response shapes:
    - Search/trending cards supply ``genre_ids: [16, 18]`` (flat int list).
    - Detail endpoints supply ``genres: [{"id": 16, "name": "Animation"}]``.

    Args:
        payload: Show creation payload containing TMDB metadata.

    Returns:
        One of ``"movie"``, ``"anime"``, or ``"tv"``.
    """
    if payload.media_type == "movie":
        return "movie"
    # Collect genre IDs from whichever field the caller populated.
    ids_from_objects = {g.get("id") for g in (payload.genres or [])}
    ids_from_list = set(payload.genre_ids or [])
    all_genre_ids = ids_from_objects | ids_from_list
    is_animated = _ANIMATION_GENRE_ID in all_genre_ids
    is_japanese = payload.original_language == "ja" or "JP" in (payload.origin_country or [])
    if is_animated and is_japanese:
        return "anime"
    return "tv"


def auto_local_path(content_type: str, sys_name: str) -> str:
    """Compute the default local path for a new show from configured media roots.

    Args:
        content_type: One of ``"anime"``, ``"movie"``, or ``"tv"``.
        sys_name: Filesystem-safe show directory name.

    Returns:
        Absolute container-side path string.
    """
    from jidou.config import settings

    return resolve_show_local_path(
        content_type=content_type,
        media_type=None,
        sys_name=sys_name,
        local_tv_path=settings.local_tv_path,
        local_anime_path=settings.local_anime_path,
        local_movie_path=settings.local_movie_path,
    )
