"""TMDB API client with caching and rate limiting."""

import logging
from typing import Any

import httpx

from jidou.config import settings
from jidou.services.cache import cache
from jidou.services.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


class TMDBService:
    """Client for The Movie Database (TMDB) API v3.

    Handles authentication, caching, and rate limiting automatically.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = settings.tmdb_base_url,
    ) -> None:
        """Initialize the TMDB service.

        Args:
            api_key: TMDB API key. Falls back to settings if not provided.
            base_url: Base URL for TMDB API.
        """
        self.api_key = api_key or settings.tmdb_api_key
        self.base_url = base_url.rstrip("/")

    async def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an authenticated, rate-limited request to TMDB.

        Args:
            endpoint: API endpoint path (e.g., "/trending/movie/day").
            params: Additional query parameters.

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx status.
        """
        if not self.api_key:
            raise ValueError("TMDB_API_KEY is not configured")

        url = f"{self.base_url}{endpoint}"
        request_params = {"api_key": self.api_key, **(params or {})}

        # Check cache first
        cache_key = cache.make_key(url + str(sorted(request_params.items())))
        cached_result = await cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for %s", endpoint)
            return cached_result  # type: ignore[no-any-return]

        # Rate-limited request
        async with rate_limiter.acquire(), httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=request_params)
            response.raise_for_status()
            result: dict[str, Any] = response.json()

        logger.info(
            "TMDB %s returned status %s (%.1fs)",
            endpoint,
            response.status_code,
            response.elapsed.total_seconds(),
        )

        # Cache the result
        await cache.set(cache_key, result)
        return result

    async def get_trending(
        self, media_type: str = "multi", time_window: str = "day"
    ) -> dict[str, Any]:
        """Get trending media from TMDB.

        Args:
            media_type: One of "movie", "tv", or "multi".
            time_window: Either "day" or "week".

        Returns:
            Dictionary containing trending shows.

        Raises:
            ValueError: If media_type or time_window are invalid.
        """
        if media_type not in {"movie", "tv", "multi"}:
            raise ValueError(
                f"Invalid media_type: {media_type!r}. Must be 'movie', 'tv', or 'multi'."
            )
        if time_window not in {"day", "week"}:
            raise ValueError(f"Invalid time_window: {time_window!r}. Must be 'day' or 'week'.")
        return await self._request(f"/trending/{media_type}/{time_window}")

    async def search(self, query: str, media_type: str = "multi") -> dict[str, Any]:
        """Search TMDB for matching media.

        Args:
            query: Search term.
            media_type: One of "movie", "tv", or "multi".

        Returns:
            Dictionary containing search results.
        """
        return await self._request(f"/search/{media_type}", params={"query": query})

    async def get_details(self, tmdb_id: int, media_type: str = "tv") -> dict[str, Any]:
        """Get detailed information for a specific show.

        Args:
            tmdb_id: The TMDB identifier for the show.
            media_type: Either "movie" or "tv".

        Returns:
            Dictionary containing show details.

        Raises:
            ValueError: If media_type is invalid.
        """
        if media_type not in {"movie", "tv"}:
            raise ValueError(f"Invalid media_type: {media_type!r}. Must be 'movie' or 'tv'.")
        return await self._request(f"/{media_type}/{tmdb_id}")

    async def get_recommendations(self, tmdb_id: int, media_type: str = "tv") -> dict[str, Any]:
        """Get recommendations for a show.

        Args:
            tmdb_id: The TMDB identifier for the show.
            media_type: Either "movie" or "tv".

        Returns:
            Dictionary containing recommended shows.

        Raises:
            ValueError: If media_type is invalid.
        """
        if media_type not in {"movie", "tv"}:
            raise ValueError(f"Invalid media_type: {media_type!r}. Must be 'movie' or 'tv'.")
        return await self._request(f"/{media_type}/{tmdb_id}/recommendations")
