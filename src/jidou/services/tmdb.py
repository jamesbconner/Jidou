"""TMDB API client with caching, rate limiting, and in-flight deduplication."""

import asyncio
import logging
from typing import Any

import httpx2 as httpx

from jidou.config import settings
from jidou.services.cache import cache
from jidou.services.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Endpoint-prefix TTL overrides (seconds), checked in order — first match wins.
# Everything not listed here falls back to the cache's configured default
# (settings.tmdb_cache_ttl), which is appropriate for data TMDB rarely changes
# and that Jidou only ever fetches once anyway (show/episode/season details,
# external_ids, episode_groups, alternative_titles, images, recommendations).
#
# Trending and search are different: they're read repeatedly by humans
# (Shows page search, re-match modals) and/or a scheduled refresh job, and
# staleness there is directly user-visible rather than a background
# data-quality nuance — see the "trending was serving week-old data" and
# "re-match modal showing stale search candidates" analysis.
_TTL_OVERRIDES: tuple[tuple[str, int], ...] = (
    ("/trending/", 86_400),  # 1 day — matches TMDB's own daily trending refresh
    ("/search/", 3_600),  # 1 hour — balances repeat-search hit rate against staleness
)


def _ttl_for_endpoint(endpoint: str) -> int | None:
    """Return a TTL override in seconds for *endpoint*, or None for the cache default.

    Args:
        endpoint: API endpoint path (e.g. ``"/trending/movie/day"``).

    Returns:
        The override TTL in seconds, or ``None`` if *endpoint* isn't in
        :data:`_TTL_OVERRIDES` (caller should fall back to the cache's
        configured default).
    """
    for prefix, ttl in _TTL_OVERRIDES:
        if endpoint.startswith(prefix):
            return ttl
    return None


class TMDBService:
    """Client for The Movie Database (TMDB) API v3.

    Handles authentication, response caching, rate limiting, and in-flight
    request deduplication automatically.  All callers within the same process
    that request the same URL simultaneously share a single HTTP round-trip.
    """

    # Transient transport failures (connect/read timeouts, refused/reset
    # connections) are retried with exponential backoff before giving up.
    _MAX_TRANSPORT_RETRIES = 3
    _RETRY_BASE_DELAY_SECONDS = 0.5

    # Cap on how many times a *new* owner is elected to retry the same
    # deduplicated request after a failure, independent of how many callers
    # (N) are waiting. Without this cap, a sustained outage serializes all N
    # callers through their own full retry cycle one after another -- the
    # Nth caller only learns the endpoint is down after N elections' worth of
    # rate-limited attempts, even though the 1st caller knew at t=0.
    _MAX_DEDUP_ELECTION_ROUNDS = 2

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = settings.tmdb_base_url,
    ) -> None:
        """Initialise the TMDB service.

        Args:
            api_key: TMDB API key.  Falls back to ``settings.tmdb_api_key``.
            base_url: Base URL for the TMDB API.
        """
        self.api_key = api_key or settings.tmdb_api_key
        self.base_url = base_url.rstrip("/")
        # Per-instance in-flight deduplication state.
        self._in_flight: dict[str, asyncio.Event] = {}
        self._flight_lock = asyncio.Lock()
        # How many owners have been elected so far for a given cache key
        # (reset to 1 whenever a brand-new dedup batch starts), and the most
        # recent owner's exception, so waiters that hit the election cap can
        # fail fast with the real error instead of taking another serial turn.
        self._in_flight_rounds: dict[str, int] = {}
        self._in_flight_error: dict[str, BaseException] = {}

    async def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an authenticated, rate-limited, deduplicated request to TMDB.

        Args:
            endpoint: API endpoint path (e.g. ``"/trending/movie/day"``).
            params: Additional query parameters.

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            ValueError: If ``TMDB_API_KEY`` is not configured.
            httpx.HTTPStatusError: If the API returns a non-2xx status.
            httpx.TransportError: If the connection still fails after
                :attr:`_MAX_TRANSPORT_RETRIES` attempts.
            Exception: The last owner's error, re-raised to any waiter that
                arrives once :attr:`_MAX_DEDUP_ELECTION_ROUNDS` elected owners
                have already failed in a row for this key (fail-fast).
        """
        if not self.api_key:
            raise ValueError("TMDB_API_KEY is not configured")

        url = f"{self.base_url}{endpoint}"
        request_params = {"api_key": self.api_key, **(params or {})}
        cache_key = cache.make_key(url + str(sorted(request_params.items())))

        # --- Cache hit ---
        cached_result = await cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for %s", endpoint)
            return cached_result  # type: ignore[no-any-return]

        # --- In-flight deduplication ---
        async with self._flight_lock:
            if cache_key in self._in_flight:
                event = self._in_flight[cache_key]
                is_owner = False
            else:
                event = asyncio.Event()
                self._in_flight[cache_key] = event
                self._in_flight_rounds[cache_key] = 1
                is_owner = True

        if not is_owner:
            logger.debug("In-flight dedup: waiting for concurrent request for %s", endpoint)
            while True:
                await event.wait()
                refreshed = await cache.get(cache_key)
                if refreshed is not None:
                    return refreshed  # type: ignore[no-any-return]
                # Owner's request failed.  Elect one waiter as new owner so the
                # remaining waiters don't all make independent HTTP calls --
                # unless the election cap is already reached, in which case
                # this (and every remaining) waiter fails fast instead of
                # taking its own serial turn against a demonstrably-down endpoint.
                async with self._flight_lock:
                    if cache_key in self._in_flight:
                        # Another waiter won the election — wait on their attempt.
                        event = self._in_flight[cache_key]
                        continue
                    round_number = self._in_flight_rounds.get(cache_key, 0) + 1
                    if round_number > self._MAX_DEDUP_ELECTION_ROUNDS:
                        # Deliberately not popped: every remaining sibling
                        # waiter must see the same capped round count and the
                        # same error so they all fail fast too, instead of the
                        # first one clearing state and the next re-electing
                        # itself as a "fresh" owner.
                        error = self._in_flight_error.get(cache_key)
                        logger.warning(
                            "In-flight dedup: %s failed %d time(s) in a row; "
                            "failing fast instead of electing another retry owner",
                            endpoint,
                            self._MAX_DEDUP_ELECTION_ROUNDS,
                        )
                        if error is not None:
                            raise error
                        raise RuntimeError(
                            f"TMDB {endpoint} request failed (in-flight dedup fail-fast)"
                        )
                    self._in_flight_rounds[cache_key] = round_number
                    event = asyncio.Event()
                    self._in_flight[cache_key] = event
                    is_owner = True
                    break
            logger.warning(
                "In-flight dedup: owner request failed for %s; this coroutine retrying "
                "(election round %d/%d)",
                endpoint,
                self._in_flight_rounds[cache_key],
                self._MAX_DEDUP_ELECTION_ROUNDS,
            )

        # --- Rate-limited HTTP request ---
        try:
            # One final cache check before acquiring the rate-limit slot.
            # Covers two races:
            # (a) elected-retry owner: a sibling may have populated the cache
            #     between when this coroutine won the election and now.
            # (b) cross-process: another worker may have completed an identical
            #     request between the initial cache miss and this point.
            pre_request_cached = await cache.get(cache_key)
            if pre_request_cached is not None:
                self._in_flight_rounds.pop(cache_key, None)
                self._in_flight_error.pop(cache_key, None)
                return pre_request_cached  # type: ignore[no-any-return]

            response = await self._get_with_retry(url, request_params, endpoint)
            result: dict[str, Any] = response.json()

            logger.info(
                "TMDB %s → %s (%.1fs)",
                endpoint,
                response.status_code,
                response.elapsed.total_seconds(),
            )
            await cache.set(cache_key, result, label=endpoint, ttl=_ttl_for_endpoint(endpoint))
            self._in_flight_rounds.pop(cache_key, None)
            self._in_flight_error.pop(cache_key, None)
            return result
        except Exception as exc:
            if is_owner:
                self._in_flight_error[cache_key] = exc
            raise
        finally:
            if is_owner:
                async with self._flight_lock:
                    self._in_flight.pop(cache_key, None)
                event.set()

    async def _get_with_retry(
        self, url: str, params: dict[str, Any], endpoint: str
    ) -> "httpx.Response":
        """Issue one rate-limited GET, retrying transient transport failures.

        Each attempt (including retries) re-acquires the rate limiter, since a
        retry is a fresh call to the external API and must respect the same
        per-endpoint budget as the original attempt.

        Args:
            url: Fully-qualified request URL.
            params: Query parameters, including the API key.
            endpoint: Endpoint path, used only for log messages.

        Returns:
            The successful HTTP response.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx status.
            httpx.TransportError: If every attempt fails to connect.
        """
        for attempt in range(1, self._MAX_TRANSPORT_RETRIES + 1):
            try:
                async with rate_limiter.acquire(), httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    return response
            except httpx.TransportError as exc:
                if attempt == self._MAX_TRANSPORT_RETRIES:
                    logger.error(
                        "TMDB %s failed after %d attempts: %s",
                        endpoint,
                        attempt,
                        exc,
                    )
                    raise
                delay = self._RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "TMDB %s transport error (attempt %d/%d): %s; retrying in %.1fs",
                    endpoint,
                    attempt,
                    self._MAX_TRANSPORT_RETRIES,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")  # loop always returns or raises

    # ------------------------------------------------------------------
    # Trending / Search / Details
    # ------------------------------------------------------------------

    async def get_trending(
        self, media_type: str = "multi", time_window: str = "day"
    ) -> dict[str, Any]:
        """Get trending media from TMDB.

        Args:
            media_type: One of ``"movie"``, ``"tv"``, or ``"multi"``.
            time_window: Either ``"day"`` or ``"week"``.

        Returns:
            Dictionary containing trending shows.

        Raises:
            ValueError: If *media_type* or *time_window* are invalid.
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
            media_type: One of ``"movie"``, ``"tv"``, or ``"multi"``.

        Returns:
            Dictionary containing search results.

        Raises:
            ValueError: If *media_type* is invalid.
        """
        if media_type not in {"movie", "tv", "multi"}:
            raise ValueError(
                f"Invalid media_type: {media_type!r}. Must be 'movie', 'tv', or 'multi'."
            )
        return await self._request(f"/search/{media_type}", params={"query": query})

    async def get_details(self, tmdb_id: int, media_type: str = "tv") -> dict[str, Any]:
        """Get detailed information for a specific show or movie.

        Args:
            tmdb_id: The TMDB identifier.
            media_type: Either ``"movie"`` or ``"tv"``.

        Returns:
            Dictionary containing show / movie details.

        Raises:
            ValueError: If *media_type* is invalid.
        """
        if media_type not in {"movie", "tv"}:
            raise ValueError(f"Invalid media_type: {media_type!r}. Must be 'movie' or 'tv'.")
        return await self._request(f"/{media_type}/{tmdb_id}")

    async def get_recommendations(self, tmdb_id: int, media_type: str = "tv") -> dict[str, Any]:
        """Get recommendations for a show or movie.

        Args:
            tmdb_id: The TMDB identifier.
            media_type: Either ``"movie"`` or ``"tv"``.

        Returns:
            Dictionary containing recommended items.

        Raises:
            ValueError: If *media_type* is invalid.
        """
        if media_type not in {"movie", "tv"}:
            raise ValueError(f"Invalid media_type: {media_type!r}. Must be 'movie' or 'tv'.")
        return await self._request(f"/{media_type}/{tmdb_id}/recommendations")

    # ------------------------------------------------------------------
    # Season / Episode data (TV only)
    # ------------------------------------------------------------------

    async def get_show_seasons(self, tmdb_id: int) -> dict[str, Any]:
        """Get the season list for a TV show.

        Equivalent to ``get_details`` but makes the intent explicit when only
        the season list is required.

        Args:
            tmdb_id: TMDB identifier of the TV show.

        Returns:
            Dictionary containing show details including ``seasons`` list.
        """
        return await self._request(f"/tv/{tmdb_id}")

    async def get_season_details(self, tmdb_id: int, season_number: int) -> dict[str, Any]:
        """Get all episode details for a specific season.

        Args:
            tmdb_id: TMDB identifier of the TV show.
            season_number: Season number (1-based).

        Returns:
            Dictionary containing season metadata and ``episodes`` list.

        Raises:
            ValueError: If *season_number* is not a positive integer.
        """
        if season_number < 1:
            raise ValueError(f"season_number must be >= 1, got {season_number}")
        return await self._request(f"/tv/{tmdb_id}/season/{season_number}")

    async def get_episode_details(
        self, tmdb_id: int, season_number: int, episode_number: int
    ) -> dict[str, Any]:
        """Get details for a specific episode.

        Args:
            tmdb_id: TMDB identifier of the TV show.
            season_number: Season number (1-based).
            episode_number: Episode number within the season (1-based).

        Returns:
            Dictionary containing episode metadata.

        Raises:
            ValueError: If *season_number* or *episode_number* are not positive.
        """
        if season_number < 1:
            raise ValueError(f"season_number must be >= 1, got {season_number}")
        if episode_number < 1:
            raise ValueError(f"episode_number must be >= 1, got {episode_number}")
        return await self._request(f"/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}")

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    async def get_alternative_titles(self, tmdb_id: int, media_type: str = "tv") -> dict[str, Any]:
        """Get alternative titles for a show or movie from TMDB.

        TV response has ``results`` key; movie response has ``titles`` key.
        Both contain objects with ``iso_3166_1``, ``title``, and ``type`` fields.

        Args:
            tmdb_id: The TMDB identifier.
            media_type: Either ``"movie"`` or ``"tv"``.

        Returns:
            Raw TMDB response dict.

        Raises:
            ValueError: If *media_type* is invalid.
        """
        if media_type not in {"movie", "tv"}:
            raise ValueError(f"Invalid media_type: {media_type!r}. Must be 'movie' or 'tv'.")
        return await self._request(f"/{media_type}/{tmdb_id}/alternative_titles")

    async def get_external_ids(self, tmdb_id: int, media_type: str = "tv") -> dict[str, Any]:
        """Get external IDs (IMDb, TVDB, etc.) for a show or movie.

        Args:
            tmdb_id: The TMDB identifier.
            media_type: Either ``"movie"`` or ``"tv"``.

        Returns:
            Dictionary with keys like ``imdb_id``, ``tvdb_id``, ``wikidata_id``, etc.

        Raises:
            ValueError: If *media_type* is invalid.
        """
        if media_type not in {"movie", "tv"}:
            raise ValueError(f"Invalid media_type: {media_type!r}. Must be 'movie' or 'tv'.")
        return await self._request(f"/{media_type}/{tmdb_id}/external_ids")

    async def get_episode_groups(self, tmdb_id: int) -> dict[str, Any]:
        """Get episode groups for a TV show.

        Episode groups (especially type 6 — Production) provide correct
        season/episode numbering for anime and other non-standard shows.

        Args:
            tmdb_id: TMDB identifier of the TV show.

        Returns:
            Dictionary containing ``results`` list of episode group objects.
        """
        return await self._request(f"/tv/{tmdb_id}/episode_groups")

    async def get_episode_group(self, group_id: str) -> dict[str, Any]:
        """Get the full per-episode breakdown for one episode group.

        ``get_episode_groups`` only returns a summary (id/name/type/counts);
        this fetches a specific group's actual sub-group structure, each
        with its own ordered ``episodes`` list.

        Args:
            group_id: TMDB episode group ID (the ``id`` field from a
                ``get_episode_groups`` result entry).

        Returns:
            Dictionary with a ``groups`` list of sub-groups, each carrying
            ``name``, ``order``, and an ``episodes`` list.
        """
        return await self._request(f"/tv/episode_group/{group_id}")

    async def get_images(self, tmdb_id: int, media_type: str = "tv") -> dict[str, Any]:
        """Get available images (posters, backdrops, logos) for a show or movie.

        Args:
            tmdb_id: The TMDB identifier.
            media_type: Either ``"movie"`` or ``"tv"``.

        Returns:
            Dictionary containing image lists (``backdrops``, ``posters``, etc.).

        Raises:
            ValueError: If *media_type* is invalid.
        """
        if media_type not in {"movie", "tv"}:
            raise ValueError(f"Invalid media_type: {media_type!r}. Must be 'movie' or 'tv'.")
        return await self._request(f"/{media_type}/{tmdb_id}/images")
