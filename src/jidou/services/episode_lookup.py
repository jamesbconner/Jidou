"""Resolve a parsed season/episode number to an Episode row."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode


async def resolve_episode(
    session: AsyncSession,
    show_id: int,
    season: int | None,
    episode: int | None,
    *,
    positional_fallback: bool = False,
) -> Episode | None:
    """Look up an Episode by season/episode number, with anime-friendly fallbacks.

    Lookup chain:

    1. If *season* is given, match on ``(season_number, episode_number)``
       only — no further fallback is attempted even on a miss. A known
       season number means the caller has confident data; guessing further
       risks a wrong match (e.g. a Season 3 file should never silently
       resolve to a Season 1 episode).
    2. If *season* is None, *episode* is treated as an absolute episode
       number:

       a. Match on ``Episode.absolute_episode_number`` (TMDB-populated via
          episode groups).
       b. If (a) misses, the second fallback depends on *positional_fallback*:

          - ``True`` — match on sequential position: episodes for the show
            ordered by ``(season_number, episode_number)``, excluding
            season 0 specials, matched by row position. Handles shows
            where fansub filenames use continuous absolute numbering but
            TMDB stores episodes per-season without populating
            ``absolute_episode_number``.
          - ``False`` — match on ``(season_number=1, episode_number=episode)``,
            correct for the vast majority of anime distributed without
            season markers.

       These two strategies are mutually exclusive, not stacked: positional
       fallback is a deliberately different (and for path-list import,
       more reliable) guess than a literal Season 1 assumption, not an
       additional attempt on top of it.

    Args:
        session: Active async SQLAlchemy session.
        show_id: Database ID of the parent show.
        season: Season number, or None for absolute/anime-style numbering.
        episode: Episode number (or absolute episode number when *season*
            is None). None short-circuits to no match.
        positional_fallback: Use the sequential-position fallback instead
            of the Season-1 fallback when *season* is None and the
            absolute-number lookup misses. Off by default (Season-1
            fallback); path-list import opts in.

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

    if positional_fallback:
        numbered = (
            select(
                Episode.id,
                func.row_number()
                .over(order_by=[Episode.season_number, Episode.episode_number])
                .label("row_num"),
            )
            .where(Episode.show_id == show_id, Episode.season_number > 0)
            .subquery()
        )
        stmt = (
            select(Episode)
            .join(numbered, Episode.id == numbered.c.id)
            .where(numbered.c.row_num == episode)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    stmt = select(Episode).where(
        Episode.show_id == show_id,
        Episode.season_number == 1,
        Episode.episode_number == episode,
    )
    return (await session.execute(stmt)).scalar_one_or_none()
