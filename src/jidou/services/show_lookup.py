"""Resolve a show name (directory name or LLM-parsed title) to a Show row."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show


async def find_show_by_name(
    session: AsyncSession,
    name: str,
    *,
    fuzzy: bool = False,
) -> Show | None:
    """Look up a show in the database by alias or title.

    Lookup chain:

    1. GIN-indexed alias containment — fastest path, and the one hit on
       every re-import once a name has been taught via ``_add_alias``.
    2. Title match. Exact case-insensitive equality when *fuzzy* is False;
       a substring match (``ILIKE '%name%'``) when *fuzzy* is True. These
       are alternatives, not stacked tiers — a substring match already
       covers the exact case, so running both would be a wasted query.

    *fuzzy* defaults to False because substring matching can false-positive
    on franchise titles that share a prefix — "Daredevil" would otherwise
    match "Daredevil: Born Again". Callers that enable it must not treat a
    fuzzy hit as proof the searched name is a valid alias for the matched
    show (see ``ParseOrchestrator._find_show``, which checks the returned
    show's own title/aliases before teaching a new one).

    Args:
        session: Active async SQLAlchemy session.
        name: Show name to search for — a directory name, or an LLM/heuristic
            parsed show name.
        fuzzy: Use a substring title match instead of an exact one. Off by
            default.

    Returns:
        Matching :class:`Show`, or None.
    """
    normalised = name.strip().lower()

    alias_stmt = (
        select(Show)
        .where(Show.aliases.cast(JSONB).contains([normalised]))
        .order_by(Show.id)
        .limit(1)
    )
    show = (await session.execute(alias_stmt)).scalars().first()
    if show is not None:
        return show

    if fuzzy:
        # Escape % and _ so parsed names containing SQL wildcard characters
        # do not match arbitrary shows.
        escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        title_stmt = (
            select(Show)
            .where(Show.title.ilike(f"%{escaped}%", escape="\\"))
            .order_by(Show.id)
            .limit(1)
        )
    else:
        title_stmt = (
            select(Show).where(func.lower(Show.title) == normalised).order_by(Show.id).limit(1)
        )
    return (await session.execute(title_stmt)).scalars().first()
