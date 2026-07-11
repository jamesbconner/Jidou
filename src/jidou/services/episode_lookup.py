"""Resolve a parsed season/episode number to an Episode row."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode


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
        stmt = select(Episode).where(
            Episode.show_id == show_id,
            Episode.season_number == season,
            Episode.episode_number == episode,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    stmt = select(Episode).where(
        Episode.show_id == show_id,
        Episode.absolute_episode_number == episode,
    )
    ep = (await session.execute(stmt)).scalar_one_or_none()
    if ep is not None:
        return ep

    stmt = select(Episode).where(
        Episode.show_id == show_id,
        Episode.season_number == 1,
        Episode.episode_number == episode,
    )
    return (await session.execute(stmt)).scalar_one_or_none()
