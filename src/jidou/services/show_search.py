"""Search the local show library by title, alias, system name, or folder name."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from sqlalchemy import case, func, literal, literal_column, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show

MatchedOn = Literal["title", "alias", "sys_name", "path"]

MIN_QUERY_LENGTH = 2

# Lower is better. Within a tier, earlier entries in _FIELD_PRIORITY win.
_TIER_EXACT = 0
_TIER_PREFIX = 1
_TIER_SUBSTRING = 2
_FIELD_PRIORITY: tuple[MatchedOn, ...] = ("title", "alias", "sys_name", "path")


@dataclass(frozen=True, slots=True)
class ShowSearchHit:
    """One local show that matched a search query.

    Attributes:
        id: Local show primary key.
        tmdb_id: TMDB identifier.
        title: Show title.
        media_type: ``"tv"`` or ``"movie"``.
        content_type: Routing category, if assigned.
        local_path: Library folder, if assigned.
        sys_name: Filesystem-safe directory name, if set.
        poster_path: TMDB poster path, if any.
        release_date: Release or first-air date string, if any.
        matched_on: Which field produced the best match.
    """

    id: int
    tmdb_id: int
    title: str
    media_type: str
    content_type: str | None
    local_path: str | None
    sys_name: str | None
    poster_path: str | None
    release_date: str | None
    matched_on: MatchedOn


def _escape_like(value: str) -> str:
    """Escape ``%``, ``_`` and the escape character itself for a LIKE pattern."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _folder_basename(local_path: str | None) -> str | None:
    """Return the last component of a container-side folder path."""
    if not local_path:
        return None
    return PurePosixPath(local_path).name or None


def _tier(needle: str, haystack: str) -> int | None:
    """Classify how *haystack* matches *needle* (both already lowercased)."""
    if haystack == needle:
        return _TIER_EXACT
    if haystack.startswith(needle):
        return _TIER_PREFIX
    if needle in haystack:
        return _TIER_SUBSTRING
    return None


def _best_match(
    needle: str,
    *,
    title: str,
    aliases: list[str] | None,
    sys_name: str | None,
    local_path: str | None,
) -> tuple[int, MatchedOn] | None:
    """Return ``(rank, matched_on)`` for the best-matching field, or None.

    Rank orders by match quality first, then by field priority.
    """
    candidates: dict[MatchedOn, int] = {}

    def consider(field: MatchedOn, values: list[str]) -> None:
        tiers = [t for v in values if (t := _tier(needle, v.lower())) is not None]
        if tiers:
            candidates[field] = min(tiers)

    consider("title", [title])
    consider("alias", list(aliases or []))
    consider("sys_name", [sys_name] if sys_name else [])
    basename = _folder_basename(local_path)
    consider("path", [basename] if basename else [])

    if not candidates:
        return None
    best_field = min(
        candidates,
        key=lambda f: (candidates[f], _FIELD_PRIORITY.index(f)),
    )
    rank = candidates[best_field] * len(_FIELD_PRIORITY) + _FIELD_PRIORITY.index(best_field)
    return rank, best_field


async def search_local_shows(
    session: AsyncSession,
    query: str,
    *,
    limit: int = 20,
) -> list[ShowSearchHit]:
    """Search local shows by title, alias, ``sys_name`` and folder basename.

    Matching is a case-insensitive substring match. Folder matching uses only
    the final path component of ``local_path`` so media-root directory names
    (e.g. ``anime``) never match. Results are ranked exact > prefix >
    substring, then by field (title, alias, sys_name, path), then title.

    Args:
        session: Active async SQLAlchemy session.
        query: Search text. Shorter than :data:`MIN_QUERY_LENGTH` after
            stripping returns no results.
        limit: Maximum number of results.

    Returns:
        Ranked list of :class:`ShowSearchHit`.
    """
    needle = query.strip().lower()
    if len(needle) < MIN_QUERY_LENGTH:
        return []

    pattern = f"%{_escape_like(needle)}%"
    basename = func.regexp_replace(func.rtrim(Show.local_path, "/"), "^.*/", "")
    # `aliases` can hold a JSON null (distinct from SQL NULL) or another
    # non-array value; jsonb_array_elements_text raises on those, which would
    # fail the whole query. Treat anything that is not an array as empty.
    aliases_json = Show.aliases.cast(JSONB)
    safe_aliases = case(
        (func.jsonb_typeof(aliases_json) == "array", aliases_json),
        else_=literal_column("'[]'::jsonb"),
    )
    alias_values = func.jsonb_array_elements_text(safe_aliases).table_valued("value")
    alias_match = (
        select(literal(1))
        .select_from(alias_values)
        .where(alias_values.c.value.ilike(pattern, escape="\\"))
        .correlate(Show)
        .exists()
    )

    stmt = select(
        Show.id,
        Show.tmdb_id,
        Show.title,
        Show.media_type,
        Show.content_type,
        Show.local_path,
        Show.sys_name,
        Show.poster_path,
        Show.release_date,
        Show.aliases,
    ).where(
        or_(
            Show.title.ilike(pattern, escape="\\"),
            Show.sys_name.ilike(pattern, escape="\\"),
            basename.ilike(pattern, escape="\\"),
            alias_match,
        )
    )
    rows = (await session.execute(stmt)).all()

    ranked: list[tuple[int, str, ShowSearchHit]] = []
    for row in rows:
        best = _best_match(
            needle,
            title=row.title,
            aliases=row.aliases,
            sys_name=row.sys_name,
            local_path=row.local_path,
        )
        # SQL ILIKE and Python lower() can disagree on exotic Unicode casing;
        # a row we cannot attribute to a field is dropped rather than mislabelled.
        if best is None:
            continue
        rank, matched_on = best
        ranked.append(
            (
                rank,
                row.title.lower(),
                ShowSearchHit(
                    id=row.id,
                    tmdb_id=row.tmdb_id,
                    title=row.title,
                    media_type=row.media_type,
                    content_type=row.content_type,
                    local_path=row.local_path,
                    sys_name=row.sys_name,
                    poster_path=row.poster_path,
                    release_date=row.release_date,
                    matched_on=matched_on,
                ),
            )
        )

    ranked.sort(key=lambda item: (item[0], item[1], item[2].id))
    return [hit for _, _, hit in ranked[:limit]]
