"""Show discovery API endpoints."""

from typing import Any

from fastapi import APIRouter

from jidou.services.tmdb import TMDBService

router = APIRouter(prefix="/shows", tags=["shows"])
tmdb = TMDBService()


@router.get("/trending")
async def get_trending(
    media_type: str = "multi",
    time_window: str = "day",
) -> dict[str, Any]:
    """Retrieve trending shows from TMDB.

    Args:
        media_type: Filter by media type ("movie", "tv", or "multi").
        time_window: Time window for trending ("day" or "week").

    Returns:
        Dictionary containing trending media results.
    """
    return await tmdb.get_trending(media_type=media_type, time_window=time_window)


@router.get("/search")
async def search_shows(query: str, media_type: str = "multi") -> dict[str, Any]:
    """Search for shows by title or keyword.

    Args:
        query: Search term.
        media_type: Filter by media type ("movie", "tv", or "multi").

    Returns:
        Dictionary containing search results.
    """
    return await tmdb.search(query=query, media_type=media_type)


@router.get("/{tmdb_id}")
async def get_show_details(tmdb_id: int, media_type: str = "tv") -> dict[str, Any]:
    """Get detailed information for a specific show.

    Args:
        tmdb_id: The TMDB identifier for the show.
        media_type: Either "movie" or "tv".

    Returns:
        Dictionary containing show details.
    """
    return await tmdb.get_details(tmdb_id=tmdb_id, media_type=media_type)
