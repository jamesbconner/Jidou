"""API routes for dashboard "recently added" carousels.

Filtering, sorting, and limiting all happen server-side — unlike the Shows
page (which fetches the whole library and sorts client-side), these
endpoints return only the top N of what can be a much larger, joined
dataset, and the adult-content filter must be enforced in SQL so hidden
rows never leave the server.
"""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, Select, nullslast, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.schemas.dashboard_schema import (
    DashboardShowSummary,
    RecentEpisodeItem,
    RecentShowItem,
)
from jidou.services.settings_service import get_show_adult_content

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

SortOrder = Literal["tracked", "release"]

_SHOW_SORT_MAP: dict[str, ColumnElement[Any]] = {
    "tracked": Show.created_at.desc(),
    "release": nullslast(Show.release_date.desc()),
}

_EPISODE_SORT_MAP: dict[str, ColumnElement[Any]] = {
    "tracked": nullslast(Episode.file_tracked_at.desc()),
    "release": nullslast(Episode.air_date.desc()),
}


def _build_recent_shows_stmt(
    sort: SortOrder,
    content_type: str | None,
    genre: str | None,
    include_adult: bool,
    limit: int,
) -> Select[tuple[Show]]:
    """Build the SELECT for the "Recently Added Shows" carousel.

    Args:
        sort: ``"tracked"`` (Show.created_at) or ``"release"`` (Show.release_date).
        content_type: Optional exact-match filter (``"anime"``, ``"tv"``, ``"movie"``).
        genre: Optional TMDB genre name; matched via JSONB containment.
        include_adult: When ``False``, excludes shows with ``adult IS TRUE``.
        limit: Maximum number of rows to return.

    Returns:
        A ready-to-execute SQLAlchemy Select statement.
    """
    stmt = select(Show)
    if content_type is not None:
        stmt = stmt.where(Show.content_type == content_type)
    if genre is not None:
        stmt = stmt.where(Show.genres.contains([{"name": genre}]))
    if not include_adult:
        stmt = stmt.where(Show.adult.isnot(True))
    return stmt.order_by(_SHOW_SORT_MAP[sort]).limit(limit)


def _build_recent_episodes_stmt(
    sort: SortOrder,
    content_type: str | None,
    genre: str | None,
    include_adult: bool,
    limit: int,
) -> Select[tuple[Episode, Show]]:
    """Build the SELECT for the "Recently Added Episodes" carousel.

    Only episodes with a tracked file count as "added" — an episode that
    merely exists in TMDB's catalog but has no local file is not shown.

    Args:
        sort: ``"tracked"`` (Episode.file_tracked_at) or ``"release"`` (Episode.air_date).
        content_type: Optional exact-match filter on the episode's show.
        genre: Optional TMDB genre name on the episode's show.
        include_adult: When ``False``, excludes episodes whose show has ``adult IS TRUE``.
        limit: Maximum number of rows to return.

    Returns:
        A ready-to-execute SQLAlchemy Select statement yielding (Episode, Show) pairs.
    """
    stmt = (
        select(Episode, Show)
        .join(Show, Episode.show_id == Show.id)
        .where(Episode.file_tracked.is_(True))
    )
    if content_type is not None:
        stmt = stmt.where(Show.content_type == content_type)
    if genre is not None:
        stmt = stmt.where(Show.genres.contains([{"name": genre}]))
    if not include_adult:
        stmt = stmt.where(Show.adult.isnot(True))
    return stmt.order_by(_EPISODE_SORT_MAP[sort]).limit(limit)


@router.get("/recent-shows", response_model=list[RecentShowItem])
async def get_recent_shows(
    sort: SortOrder = Query(default="tracked"),  # noqa: B008
    content_type: str | None = Query(default=None),
    genre: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RecentShowItem]:
    """Return the most recently added shows for the dashboard carousel.

    Args:
        sort: ``"tracked"`` (when added to Jidou) or ``"release"`` (TMDB release date).
        content_type: Optional filter (``"anime"``, ``"tv"``, ``"movie"``).
        genre: Optional TMDB genre name filter.
        limit: Maximum number of shows to return (1-50).
        db_session: DB session (injected).

    Returns:
        Up to *limit* shows, most-recent first. Adult-flagged shows are
        excluded unless the ``dashboard.show_adult_content`` setting is
        enabled — this is not a caller-controlled query parameter.
    """
    include_adult = await get_show_adult_content(db_session)
    stmt = _build_recent_shows_stmt(sort, content_type, genre, include_adult, limit)
    shows = (await db_session.execute(stmt)).scalars().all()
    return [RecentShowItem.model_validate(show) for show in shows]


@router.get("/recent-episodes", response_model=list[RecentEpisodeItem])
async def get_recent_episodes(
    sort: SortOrder = Query(default="tracked"),  # noqa: B008
    content_type: str | None = Query(default=None),
    genre: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RecentEpisodeItem]:
    """Return the most recently tracked episodes for the dashboard carousel.

    Args:
        sort: ``"tracked"`` (when the file was ingested) or ``"release"`` (air date).
        content_type: Optional filter on the episode's show.
        genre: Optional TMDB genre name filter on the episode's show.
        limit: Maximum number of episodes to return (1-50).
        db_session: DB session (injected).

    Returns:
        Up to *limit* episodes with a tracked file, most-recent first.
        Adult-flagged shows' episodes are excluded unless the
        ``dashboard.show_adult_content`` setting is enabled.
    """
    include_adult = await get_show_adult_content(db_session)
    stmt = _build_recent_episodes_stmt(sort, content_type, genre, include_adult, limit)
    rows = (await db_session.execute(stmt)).all()
    return [
        RecentEpisodeItem(
            id=ep.id,
            show_id=ep.show_id,
            season_number=ep.season_number,
            episode_number=ep.episode_number,
            name=ep.name,
            overview=ep.overview,
            air_date=ep.air_date,
            file_tracked_at=ep.file_tracked_at,
            still_path=ep.still_path,
            runtime=ep.runtime,
            show=DashboardShowSummary.model_validate(show),
        )
        for ep, show in rows
    ]


@router.get("/genres", response_model=list[str])
async def get_dashboard_genres(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[str]:
    """Return the distinct set of TMDB genre names present across all shows.

    Used to populate the dashboard's genre filter dropdown without fetching
    every show (unlike the Shows page, which already has the full list in
    memory for its own filter dropdown).

    Args:
        db_session: DB session (injected).

    Returns:
        Sorted list of distinct genre names.
    """
    stmt = text(
        """
        SELECT DISTINCT g->>'name' AS genre_name
        FROM shows
        CROSS JOIN LATERAL jsonb_array_elements(coalesce(genres, '[]'::jsonb)) AS g
        WHERE g->>'name' IS NOT NULL
        ORDER BY 1
        """
    )
    result = await db_session.execute(stmt)
    return [row[0] for row in result.all()]
