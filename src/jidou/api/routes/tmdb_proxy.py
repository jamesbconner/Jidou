"""API routes that proxy TMDB lookups and the discovery feed under ``/shows/tmdb``."""

import logging
from typing import Any

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.api.dependencies import get_tmdb
from jidou.database import get_session
from jidou.schemas.discover_schema import DiscoverResult
from jidou.services.discover_feed import build_discover_feed
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shows", tags=["shows"])


# ---------------------------------------------------------------------------
# TMDB proxy endpoints under /tmdb (literal paths). main.py must register this router before
# shows.router so these win over /{show_id}.
# The ``:int`` convertor on /tmdb/{tmdb_id} keeps it from capturing /tmdb/search etc.
# ---------------------------------------------------------------------------


@router.get("/tmdb/trending")
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


@router.get("/tmdb/search")
async def search_tmdb(
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


@router.get("/tmdb/{tmdb_id:int}")
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

    Raises:
        HTTPException: 404 if no show or movie exists for *tmdb_id* under
            *media_type* on TMDB.
    """
    try:
        return await tmdb.get_details(tmdb_id=tmdb_id, media_type=media_type)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"No {media_type} found on TMDB for ID {tmdb_id}",
            ) from exc
        raise


@router.get("/tmdb/discover", response_model=list[DiscoverResult])
async def discover_shows(
    limit: int = Query(default=40, ge=1, le=100),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> list[DiscoverResult]:
    """Return a personalized discovery feed of shows not yet in the library.

    Seeded from TMDB recommendations for the user's most recently engaged
    watchlist shows (``watching``/``completed``), deduplicated and merged with
    trending TV/movies to fill out the feed. Shows already in the library are
    excluded. The assembled feed is cached for 24h, keyed by the current seed
    show set so a watchlist change invalidates it without waiting out the TTL.

    Args:
        limit: Maximum results to return (1-100, default 40).
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        List of :class:`DiscoverResult`, seeded items first.
    """
    return await build_discover_feed(db_session, tmdb, limit)
