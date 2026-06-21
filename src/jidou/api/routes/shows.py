"""API routes for show management and TMDB discovery."""

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.schemas.episode_schema import EpisodeList
from jidou.schemas.show_schema import ShowAliasesUpdate, ShowCreate, ShowList, ShowPaths, ShowRead
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shows", tags=["shows"])
_tmdb = TMDBService()

_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_sys_name(title: str) -> str:
    """Derive a Windows-safe directory name from a show title."""
    return _INVALID_FS_CHARS.sub("_", title).strip()


# ---------------------------------------------------------------------------
# TMDB discovery endpoints (literal paths — must come before /{show_id})
# ---------------------------------------------------------------------------


async def get_tmdb() -> TMDBService:
    """Return the shared TMDB service instance."""
    return _tmdb


@router.get("/trending")
async def get_trending(
    media_type: str = "tv",
    time_window: str = "day",
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> dict[str, Any]:
    """Return trending shows from TMDB.

    Args:
        media_type: ``"tv"``, ``"movie"``, or ``"multi"``.
        time_window: ``"day"`` or ``"week"``.
        tmdb: TMDB service (injected).

    Returns:
        Raw TMDB trending response dictionary.
    """
    return await tmdb.get_trending(media_type=media_type, time_window=time_window)


@router.get("/search")
async def search_shows(
    query: str,
    media_type: str = "multi",
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> dict[str, Any]:
    """Search TMDB for shows matching a query.

    Args:
        query: Search term.
        media_type: ``"tv"``, ``"movie"``, or ``"multi"``.
        tmdb: TMDB service (injected).

    Returns:
        Raw TMDB search response dictionary.
    """
    return await tmdb.search(query=query, media_type=media_type)


@router.get("/tmdb/{tmdb_id}")
async def get_tmdb_details(
    tmdb_id: int,
    media_type: str = "tv",
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> dict[str, Any]:
    """Return full TMDB metadata for a show by its TMDB ID.

    Args:
        tmdb_id: The TMDB identifier for the show or movie.
        media_type: ``"tv"`` or ``"movie"``.
        tmdb: TMDB service (injected).

    Returns:
        Raw TMDB detail response dictionary.
    """
    return await tmdb.get_details(tmdb_id=tmdb_id, media_type=media_type)


# ---------------------------------------------------------------------------
# Database CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ShowList])
async def list_shows(
    limit: int = 20,
    offset: int = 0,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[Show]:
    """List all shows stored in the database.

    Args:
        limit: Maximum results to return (default 20).
        offset: Number of results to skip for pagination.
        db_session: DB session (injected).

    Returns:
        List of shows ordered by title.
    """
    stmt = select(Show).order_by(Show.title).offset(offset).limit(limit)
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ShowRead, status_code=201)
async def create_show(
    payload: ShowCreate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Show:
    """Add a show to the database (upsert by TMDB ID).

    If the show already exists it is returned unchanged.  ``sys_name`` is
    auto-derived from the title if not provided.

    Args:
        payload: Show data from a TMDB search/trending result.
        db_session: DB session (injected).

    Returns:
        The created or existing :class:`Show` record.
    """
    stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
    existing = (await db_session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        logger.debug("Show tmdb_id=%d already exists (id=%d)", payload.tmdb_id, existing.id)
        return existing

    data = payload.model_dump()
    if not data.get("sys_name"):
        data["sys_name"] = _sanitize_sys_name(payload.title)

    show = Show(**data, cached=False)
    db_session.add(show)
    try:
        await db_session.flush()
    except IntegrityError:
        await db_session.rollback()
        stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
        existing = (await db_session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            logger.debug(
                "Show tmdb_id=%d inserted concurrently, returning existing (id=%d)",
                payload.tmdb_id,
                existing.id,
            )
            return existing
        raise

    logger.info("Added show tmdb_id=%d title=%r (id=%d)", show.tmdb_id, show.title, show.id)
    return show


@router.get("/{show_id}", response_model=ShowRead)
async def get_show(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Show:
    """Get a show by its database ID.

    Args:
        show_id: Database primary key.
        db_session: DB session (injected).

    Returns:
        The matching :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    return show


@router.put("/{show_id}/paths", response_model=ShowRead)
async def update_show_paths(
    show_id: int,
    payload: ShowPaths,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Show:
    """Update a show's local filesystem path.

    Passing ``null`` for the field clears the stored path.

    Args:
        show_id: Database primary key.
        payload: New path value.
        db_session: DB session (injected).

    Returns:
        The updated :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    if "local_path" in payload.model_fields_set:
        show.local_path = payload.local_path
    await db_session.flush()
    logger.info("Updated local_path for show id=%d: %r", show_id, show.local_path)
    return show


@router.put("/{show_id}/aliases", response_model=ShowRead)
async def update_show_aliases(
    show_id: int,
    payload: ShowAliasesUpdate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Show:
    """Replace the full aliases list for a show.

    Aliases are normalised to lowercase before storage.  Duplicate values
    are silently deduplicated.

    Args:
        show_id: Database primary key.
        payload: New list of alias strings.
        db_session: DB session (injected).

    Returns:
        The updated :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    normalised = list(dict.fromkeys(a.strip().lower() for a in payload.aliases if a.strip()))
    show.aliases = normalised or None
    await db_session.flush()
    logger.info("Updated aliases for show id=%d: %r", show_id, show.aliases)
    return show


@router.delete("/{show_id}", status_code=204)
async def delete_show(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Remove a show and all its cascaded data from the database.

    Args:
        show_id: Database primary key.
        db_session: DB session (injected).

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    await db_session.delete(show)
    logger.info("Deleted show id=%d title=%r", show_id, show.title)


@router.post("/{show_id}/sync-episodes", response_model=list[EpisodeList])
async def sync_episodes(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> list[Episode]:
    """Sync episodes from TMDB for a specific show and return the updated list.

    Args:
        show_id: Database primary key of the show to sync.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        Updated list of episodes ordered by season and episode number.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator

    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    orchestrator = TMDBOrchestrator(db_session, tmdb)
    await orchestrator.sync_show_episodes(show)

    ep_stmt = (
        select(Episode)
        .where(Episode.show_id == show_id)
        .order_by(Episode.season_number, Episode.episode_number)
    )
    result = await db_session.execute(ep_stmt)
    return list(result.scalars().all())


@router.get("/{show_id}/episodes", response_model=list[EpisodeList])
async def list_episodes(
    show_id: int,
    season: int | None = None,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[Episode]:
    """List episodes for a show, optionally filtered by season number.

    Args:
        show_id: Database primary key of the show.
        season: If provided, return only episodes from this season.
        db_session: DB session (injected).

    Returns:
        List of episodes ordered by season and episode number.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    show_stmt = select(Show).where(Show.id == show_id)
    if (await db_session.execute(show_stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Show not found")

    stmt = select(Episode).where(Episode.show_id == show_id)
    if season is not None:
        stmt = stmt.where(Episode.season_number == season)
    stmt = stmt.order_by(Episode.season_number, Episode.episode_number)

    result = await db_session.execute(stmt)
    return list(result.scalars().all())
