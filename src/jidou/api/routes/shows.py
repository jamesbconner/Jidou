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
from jidou.schemas.show_schema import (
    RematchRequest,
    ShowAliasesUpdate,
    ShowCreate,
    ShowList,
    ShowPaths,
    ShowRead,
)
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


@router.post("/{show_id}/rematch", response_model=ShowRead)
async def rematch_show(
    show_id: int,
    payload: RematchRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> Show:
    """Re-match a show to a different TMDB entry.

    Replaces all TMDB-sourced metadata on the show row, purges every episode
    that was synced from the old entry, and syncs fresh episodes from the new
    TMDB ID.  User-managed fields (``local_path``, ``content_type``, ``aliases``)
    are preserved.

    Args:
        show_id: Database primary key of the show to re-match.
        payload: ``{ "tmdb_id": <new_tmdb_id> }``
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        The updated :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
        HTTPException: 409 if the target TMDB ID is already tracked as a
            different show.
        HTTPException: 502 if TMDB details cannot be fetched.
    """
    from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator

    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    if payload.tmdb_id != show.tmdb_id:
        conflict = (
            await db_session.execute(select(Show).where(Show.tmdb_id == payload.tmdb_id))
        ).scalar_one_or_none()
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"TMDB ID {payload.tmdb_id} is already tracked as"
                    f" '{conflict.title}' (id={conflict.id})"
                ),
            )

    try:
        data = await tmdb.get_details(payload.tmdb_id, media_type=payload.media_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to fetch TMDB details") from exc

    # TV uses "name" + "first_air_date"; movies use "title" + "release_date".
    title: str = data.get("name") or data.get("title") or show.title
    release_date: str | None = data.get("first_air_date") or data.get("release_date")
    ep_runtimes: list[int] = data.get("episode_run_time") or []

    # Update all TMDB-sourced fields; preserve user-managed ones.
    show.tmdb_id = payload.tmdb_id
    show.media_type = payload.media_type
    show.title = title
    show.overview = data.get("overview")
    show.poster_path = data.get("poster_path")
    show.backdrop_path = data.get("backdrop_path")
    show.vote_average = data.get("vote_average")
    show.vote_count = data.get("vote_count", 0)
    show.release_date = release_date
    show.original_language = data.get("original_language")
    show.sys_name = _sanitize_sys_name(title)
    show.genres = data.get("genres") or []
    show.origin_country = data.get("origin_country") or []
    show.last_air_date = data.get("last_air_date")
    show.last_episode_to_air = data.get("last_episode_to_air")
    show.next_episode_to_air = data.get("next_episode_to_air")
    show.homepage = data.get("homepage")
    show.status = data.get("status")
    show.in_production = data.get("in_production")
    show.number_of_seasons = data.get("number_of_seasons")
    show.number_of_episodes = data.get("number_of_episodes")
    show.networks = data.get("networks") or []
    show.show_type = data.get("type")
    show.runtime = data.get("runtime") or (ep_runtimes[0] if ep_runtimes else None)
    show.tagline = data.get("tagline")

    # Purge episodes from the old match — they belong to a different show.
    await db_session.execute(
        Episode.__table__.delete().where(Episode.show_id == show_id)  # type: ignore[attr-defined]
    )

    await db_session.flush()
    logger.info("Re-matched show id=%d → tmdb_id=%d title=%r", show_id, payload.tmdb_id, title)

    # Movies have no episode structure; skip TV-specific season sync.
    if payload.media_type != "movie":
        try:
            await TMDBOrchestrator(db_session, tmdb).sync_show_episodes(show)
        except Exception as exc:
            logger.exception("Episode sync failed after rematch for show id=%d", show_id)
            raise HTTPException(
                status_code=502, detail="TMDB episode sync failed; rematch aborted"
            ) from exc

    return show


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
