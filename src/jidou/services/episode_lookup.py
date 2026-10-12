"""Resolve a parsed season/episode number to an Episode row."""

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode


async def _first_episode(
    session: AsyncSession, show_id: int, *criteria: ColumnElement[bool]
) -> Episode | None:
    """Return the lowest-id Episode of *show_id* matching *criteria*, or None.

    Every episode lookup goes through here so the ``ORDER BY id LIMIT 1`` that
    makes duplicate rows degrade deterministically (see :func:`resolve_episode`)
    cannot be forgotten on one branch.

    Args:
        session: Active async SQLAlchemy session.
        show_id: Database ID of the parent show.
        *criteria: Extra WHERE conditions, ANDed with the show filter.

    Returns:
        The first matching Episode by id, or None.
    """
    stmt = (
        select(Episode).where(Episode.show_id == show_id, *criteria).order_by(Episode.id).limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def resolve_episode(
    session: AsyncSession,
    show_id: int,
    season: int | None,
    episode: int | None,
) -> Episode | None:
    """Look up an Episode by season/episode number, with anime-friendly fallbacks.

    Lookup chain:

    1. If *season* is given, match on ``(season_number, episode_number)``
       only — no further fallback is attempted even on a miss. A known
       season number means the caller has confident data; guessing further
       risks a wrong match (e.g. a Season 3 file should never silently
       resolve to a Season 1 episode). Callers that need to resolve a
       declared season disagreeing with TMDB's own structure (e.g. a fansub
       cour-folder for a show TMDB tracks as one absolute season) should
       consult ``services.episode_group_mapping.resolve_declared_season``
       and retry with the remapped season/episode instead.
    2. If *season* is None, *episode* is treated as an absolute episode
       number:

       a. Match on ``Episode.absolute_episode_number`` — populated from TMDB
          episode_groups during sync (see ``services.episode_group_mapping``)
          when available for the show.
       b. If (a) misses, match on ``(season_number=1, episode_number=episode)``
          — correct for the vast majority of anime distributed without
          season markers.

    ``(show_id, season_number, episode_number)`` has no DB-level uniqueness
    constraint — only ``tmdb_id`` is unique — since we don't control TMDB's
    data quality and a hard constraint would turn an upstream inconsistency
    into a failed sync instead of a degraded match. Every query below is
    therefore ordered by ``Episode.id`` and capped with ``LIMIT 1``: the
    database enforces the cap before the ORM's one-row check ever runs, so a
    duplicate degrades deterministically (lowest id wins) instead of raising
    ``MultipleResultsFound`` (issue #313).

    Args:
        session: Active async SQLAlchemy session.
        show_id: Database ID of the parent show.
        season: Season number, or None for absolute/anime-style numbering.
        episode: Episode number (or absolute episode number when *season*
            is None). None short-circuits to no match.

    Returns:
        The matching Episode, or None.
    """
    if episode is None:
        return None

    if season is not None:
        return await _first_episode(
            session, show_id, Episode.season_number == season, Episode.episode_number == episode
        )

    ep = await _first_episode(session, show_id, Episode.absolute_episode_number == episode)
    if ep is not None:
        return ep

    return await _first_episode(
        session, show_id, Episode.season_number == 1, Episode.episode_number == episode
    )
