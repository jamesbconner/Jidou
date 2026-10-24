"""Resolve a show name (directory name or LLM-parsed title) to a Show row."""

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show
from jidou.services.alias_handling import arc_splits, sanitize_alias, season_for_name
from jidou.services.show_search import escape_like


async def find_show_by_name(
    session: AsyncSession,
    name: str,
    *,
    fuzzy: bool = False,
) -> Show | None:
    """Look up a show in the database by alias or title.

    Lookup chain:

    1. GIN-indexed alias containment — fastest path, and the one hit on
       every re-import once a name has been added via ``alias_handling.add_alias``.
       The same query also matches a key of ``Show.season_aliases``, so a
       season name finds its show without being copied into ``aliases``.
    2. Title match. Exact case-insensitive equality when *fuzzy* is False;
       a substring match (``ILIKE '%name%'``) when *fuzzy* is True. These
       are alternatives, not stacked tiers — a substring match already
       covers the exact case, so running both would be a wasted query.
    3. Season-name prefix. A ``"<show> - <label>"`` name whose label is a
       season name stored as just the arc title: each ``" - "`` prefix is
       looked up exactly, and its show is returned only when the label is
       one of that show's season names.

    *fuzzy* defaults to False because substring matching can false-positive
    on franchise titles that share a prefix — "Daredevil" would otherwise
    match "Daredevil: Born Again". Callers that enable it must not treat a
    fuzzy hit as proof the searched name is a valid alias for the matched
    show (see ``ParseOrchestrator._find_show``, which checks the returned
    show's own title/aliases before adding a new one).

    Args:
        session: Active async SQLAlchemy session.
        name: Show name to search for — a directory name, or an LLM/heuristic
            parsed show name.
        fuzzy: Use a substring title match instead of an exact one. Off by
            default.

    Returns:
        Matching :class:`Show`, or None.
    """
    normalised = sanitize_alias(name)

    alias_stmt = (
        select(Show)
        .where(
            or_(
                Show.aliases.cast(JSONB).contains([normalised]),
                Show.season_aliases.cast(JSONB).has_key(normalised),
            )
        )
        .order_by(Show.id)
        .limit(1)
    )
    show = (await session.execute(alias_stmt)).scalars().first()
    if show is not None:
        return show

    if fuzzy:
        # Escape % and _ so parsed names containing SQL wildcard characters
        # do not match arbitrary shows.
        escaped = escape_like(name)
        # A substring match can hit multiple shows (e.g. "Daredevil" also
        # matches "Daredevil: Born Again"). Order the exact title match first
        # -- `!=` is False (sorts first) for the exact match, True for every
        # other substring hit -- rather than picking whichever row happens to
        # have the lowest id, which is unrelated to which match is correct.
        title_stmt = (
            select(Show)
            .where(Show.title.ilike(f"%{escaped}%", escape="\\"))
            .order_by(func.lower(Show.title) != normalised, Show.id)
            .limit(1)
        )
    else:
        title_stmt = (
            select(Show).where(func.lower(Show.title) == normalised).order_by(Show.id).limit(1)
        )
    show = (await session.execute(title_stmt)).scalars().first()
    if show is not None:
        return show
    return await _find_show_by_season_name(session, name)


async def _find_show_by_season_name(session: AsyncSession, name: str) -> Show | None:
    """Find the show a ``"<show> - <season name>"`` name belongs to.

    A season name is usually stored as just the arc title, so the full parsed
    name matches neither an alias key nor a title. Each ``" - "`` prefix is
    looked up exactly (never by substring), and its show is accepted only
    when the rest of the name is one of that show's season names.

    Args:
        session: Active async SQLAlchemy session.
        name: The full name that missed the alias and title lookups.

    Returns:
        The show whose season names cover *name*, or None.
    """
    for prefix, _label in arc_splits(name):
        show = await find_show_by_name(session, prefix)
        if show is not None and season_for_name(name, show) is not None:
            return show
    return None


async def find_show_by_tmdb_id(session: AsyncSession, tmdb_id: int) -> Show | None:
    """Look up a show by its TMDB ID.

    ``Show.tmdb_id`` is unique, so this is the lookup that identifies the row a
    concurrent insert of the same TMDB show created; a title or alias match could
    be a different show that merely shares the name.

    Args:
        session: Active async SQLAlchemy session.
        tmdb_id: TMDB ID to look up.

    Returns:
        Matching :class:`Show`, or None.
    """
    stmt = select(Show).where(Show.tmdb_id == tmdb_id)
    return (await session.execute(stmt)).scalar_one_or_none()
