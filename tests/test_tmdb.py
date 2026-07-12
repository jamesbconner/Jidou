"""Tests for TMDB service with mocked HTTP calls."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2 as httpx
import pytest

import jidou.services.tmdb as tmdb_module
from jidou.services.tmdb import TMDBService


class _FakeRedisPipeline:
    """Minimal fake of a redis.asyncio pipeline, backed by the parent's dict."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self._writes: list[tuple[str, str]] = []

    def set(self, key: str, value: str, **kwargs: object) -> "_FakeRedisPipeline":
        self._writes.append((key, value))
        return self

    def zadd(self, *args: object, **kwargs: object) -> "_FakeRedisPipeline":
        return self

    async def execute(self) -> list[object]:
        for key, value in self._writes:
            self._store[key] = value
        self._writes.clear()
        return []


class _FakeRedis:
    """In-memory fake of the CacheBackend subset of redis.asyncio.Redis, for tests
    that need genuine cache get/set round-trip semantics (not just call-shape mocks).
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline(self._store)

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def zcard(self, key: str) -> int:
        return 0

    async def zpopmin(self, key: str, count: int) -> list[tuple[str, float]]:
        return []

    async def aclose(self) -> None:
        pass


@asynccontextmanager
async def _patched_http(
    json_data: dict | None = None,
    *,
    raise_on_status: Exception | None = None,
    get_side_effect: Exception | None = None,
) -> AsyncGenerator[tuple[AsyncMock, AsyncMock]]:
    """Patch cache (forced miss), rate limiter (noop), and httpx for HTTP-layer tests.

    Yields:
        (mock_http_client, mock_cache_set) so callers can assert on them.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.elapsed.total_seconds.return_value = 0.05
    if raise_on_status is not None:
        mock_response.raise_for_status.side_effect = raise_on_status
    else:
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = json_data or {}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    if get_side_effect is not None:
        mock_client.get = AsyncMock(side_effect=get_side_effect)
    else:
        mock_client.get = AsyncMock(return_value=mock_response)

    @asynccontextmanager
    async def _noop_acquire() -> AsyncGenerator[None]:
        yield

    mock_cache_set = AsyncMock()

    with (
        patch.object(tmdb_module.cache, "get", AsyncMock(return_value=None)),
        patch.object(tmdb_module.cache, "set", mock_cache_set),
        patch.object(tmdb_module.rate_limiter, "acquire", _noop_acquire),
        patch("httpx2.AsyncClient", return_value=mock_client),
    ):
        yield mock_client, mock_cache_set


@pytest.fixture
def tmdb_service() -> TMDBService:
    """Create a TMDB service instance for testing."""
    return TMDBService(api_key="test-key")


class TestTMDBService:
    """Test suite for TMDBService."""

    @pytest.mark.asyncio
    async def test_tmdb_service_init(self, tmdb_service: TMDBService) -> None:
        """Service initialises with correct API key and base URL."""
        assert tmdb_service.api_key == "test-key"
        assert tmdb_service.base_url.endswith("/3")

    @pytest.mark.asyncio
    async def test_request_without_api_key_raises(self) -> None:
        """_request() without an API key raises ValueError."""
        service = TMDBService(api_key=None)
        with (
            patch.object(service, "api_key", None),
            pytest.raises(ValueError, match="TMDB_API_KEY"),
        ):
            await service.get_trending()

    # ------------------------------------------------------------------
    # Trending / Search / Details
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_trending_calls_request(self, tmdb_service: TMDBService) -> None:
        """get_trending() delegates to _request."""
        mock_response = {"results": [], "total_results": 0}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await tmdb_service.get_trending()

        assert result == mock_response
        mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_calls_request(self, tmdb_service: TMDBService) -> None:
        """search() delegates to _request."""
        mock_response = {"results": [], "total_results": 0}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await tmdb_service.search("test query")

        assert result == mock_response
        mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_trending_invalid_media_type_raises(self, tmdb_service: TMDBService) -> None:
        """get_trending() raises ValueError for unknown media_type."""
        with pytest.raises(ValueError, match="media_type"):
            await tmdb_service.get_trending(media_type="podcast")

    @pytest.mark.asyncio
    async def test_get_trending_invalid_time_window_raises(self, tmdb_service: TMDBService) -> None:
        """get_trending() raises ValueError for unknown time_window."""
        with pytest.raises(ValueError, match="time_window"):
            await tmdb_service.get_trending(time_window="month")

    @pytest.mark.asyncio
    async def test_get_details_invalid_media_type_raises(self, tmdb_service: TMDBService) -> None:
        """get_details() raises ValueError for unknown media_type."""
        with pytest.raises(ValueError, match="media_type"):
            await tmdb_service.get_details(tmdb_id=1, media_type="podcast")

    # ------------------------------------------------------------------
    # Season / Episode endpoints
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_show_seasons_delegates_to_request(self, tmdb_service: TMDBService) -> None:
        """get_show_seasons() calls _request with correct endpoint."""
        mock_response = {"id": 1, "seasons": []}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await tmdb_service.get_show_seasons(1)

        assert result == mock_response
        endpoint = mock_request.call_args.args[0]
        assert endpoint == "/tv/1"

    @pytest.mark.asyncio
    async def test_get_season_details_delegates_to_request(self, tmdb_service: TMDBService) -> None:
        """get_season_details() calls _request with correct endpoint."""
        mock_response = {"season_number": 1, "episodes": []}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await tmdb_service.get_season_details(42, season_number=2)

        assert result == mock_response
        endpoint = mock_request.call_args.args[0]
        assert endpoint == "/tv/42/season/2"

    @pytest.mark.asyncio
    async def test_get_season_details_invalid_season_raises(
        self, tmdb_service: TMDBService
    ) -> None:
        """get_season_details() raises ValueError for season_number < 1."""
        with pytest.raises(ValueError, match="season_number"):
            await tmdb_service.get_season_details(1, season_number=0)

    @pytest.mark.asyncio
    async def test_get_episode_details_delegates_to_request(
        self, tmdb_service: TMDBService
    ) -> None:
        """get_episode_details() calls _request with correct endpoint."""
        mock_response = {"episode_number": 3, "name": "Pilot"}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await tmdb_service.get_episode_details(42, season_number=1, episode_number=3)

        assert result == mock_response
        endpoint = mock_request.call_args.args[0]
        assert endpoint == "/tv/42/season/1/episode/3"

    @pytest.mark.asyncio
    async def test_get_episode_details_invalid_episode_raises(
        self, tmdb_service: TMDBService
    ) -> None:
        """get_episode_details() raises ValueError for episode_number < 1."""
        with pytest.raises(ValueError, match="episode_number"):
            await tmdb_service.get_episode_details(1, season_number=1, episode_number=0)

    # ------------------------------------------------------------------
    # Images endpoint
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_images_delegates_to_request(self, tmdb_service: TMDBService) -> None:
        """get_images() calls _request with correct endpoint."""
        mock_response = {"backdrops": [], "posters": []}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await tmdb_service.get_images(42)

        assert result == mock_response
        endpoint = mock_request.call_args.args[0]
        assert endpoint == "/tv/42/images"

    @pytest.mark.asyncio
    async def test_get_images_movie_uses_correct_path(self, tmdb_service: TMDBService) -> None:
        """get_images() uses correct path for movies."""
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {}
            await tmdb_service.get_images(10, media_type="movie")

        endpoint = mock_request.call_args.args[0]
        assert endpoint == "/movie/10/images"

    @pytest.mark.asyncio
    async def test_get_images_invalid_media_type_raises(self, tmdb_service: TMDBService) -> None:
        """get_images() raises ValueError for unknown media_type."""
        with pytest.raises(ValueError, match="media_type"):
            await tmdb_service.get_images(1, media_type="podcast")

    # ------------------------------------------------------------------
    # In-flight deduplication
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_inflight_dedup_single_http_call_for_concurrent_requests(
        self,
        tmdb_service: TMDBService,
    ) -> None:
        """Concurrent requests for the same endpoint must share one HTTP call.

        The first caller ("owner") makes the HTTP request; subsequent callers
        that arrive while the owner is in-flight wait on the owner's asyncio.Event
        and read from the populated cache rather than issuing their own requests.
        """
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        import jidou.services.tmdb as tmdb_module

        mock_response_data: dict = {"results": [{"id": 1}]}

        http_calls = 0

        async def slow_get(*args: object, **kwargs: object) -> MagicMock:
            """Simulate a slow HTTP response to let other coroutines queue up."""
            nonlocal http_calls
            http_calls += 1
            await asyncio.sleep(0.02)  # yield so Tasks 2 and 3 reach _in_flight check
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = mock_response_data
            resp.status_code = 200
            resp.elapsed.total_seconds.return_value = 0.02
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get = slow_get  # deliberately not AsyncMock to preserve await semantics

        @asynccontextmanager  # type: ignore[arg-type]
        async def noop_acquire() -> AsyncGenerator[None]:
            yield

        with (
            patch("httpx2.AsyncClient", return_value=mock_client),
            patch.object(tmdb_module.rate_limiter, "acquire", noop_acquire),
            patch("redis.asyncio.from_url", return_value=_FakeRedis()),
        ):
            results = await asyncio.gather(
                tmdb_service.get_trending(),
                tmdb_service.get_trending(),
                tmdb_service.get_trending(),
            )

        assert all(r == mock_response_data for r in results)
        assert http_calls == 1, f"Expected 1 HTTP call, got {http_calls}"

    @pytest.mark.asyncio
    async def test_inflight_dedup_owner_failure_elects_single_retry_owner(
        self,
        tmdb_service: TMDBService,
    ) -> None:
        """When the owner's request fails, exactly one waiter retries; others wait.

        Without the election fix all waiters would make independent HTTP calls
        on owner failure (a thundering-herd bug).  With the fix only the elected
        waiter makes the retry and the others read from the cache it populates.
        """
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        import jidou.services.tmdb as tmdb_module

        mock_response_data: dict = {"results": [{"id": 99}]}
        http_calls = 0

        async def failing_then_succeeding_get(*args: object, **kwargs: object) -> MagicMock:
            nonlocal http_calls
            http_calls += 1
            await asyncio.sleep(0.02)  # let waiters queue
            if http_calls == 1:
                raise RuntimeError("simulated network error")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = mock_response_data
            resp.status_code = 200
            resp.elapsed.total_seconds.return_value = 0.02
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get = failing_then_succeeding_get

        @asynccontextmanager  # type: ignore[arg-type]
        async def noop_acquire() -> AsyncGenerator[None]:
            yield

        with (
            patch("httpx2.AsyncClient", return_value=mock_client),
            patch.object(tmdb_module.rate_limiter, "acquire", noop_acquire),
            patch("redis.asyncio.from_url", return_value=_FakeRedis()),
        ):
            # Use media_type="movie" to get a distinct cache key from the
            # success-path dedup test which uses the default "multi" endpoint.
            results = await asyncio.gather(
                tmdb_service.get_trending(media_type="movie"),
                tmdb_service.get_trending(media_type="movie"),
                tmdb_service.get_trending(media_type="movie"),
                return_exceptions=True,
            )

        # Only 2 HTTP calls total: 1 owner (fails) + 1 elected retry owner (succeeds).
        # The third coroutine reads from cache populated by the retry owner.
        assert http_calls == 2, f"Expected 2 HTTP calls, got {http_calls}"
        successful = [r for r in results if isinstance(r, dict)]
        assert len(successful) >= 1
        assert all(r == mock_response_data for r in successful)


class TestTMDBPublicMethodsCoverage:
    """Cover public methods not yet reached by TestTMDBService."""

    @pytest.mark.asyncio
    async def test_search_invalid_media_type_raises(self, tmdb_service: TMDBService) -> None:
        """search() raises ValueError for unknown media_type."""
        with pytest.raises(ValueError, match="media_type"):
            await tmdb_service.search("query", media_type="podcast")

    @pytest.mark.asyncio
    async def test_get_details_tv_correct_endpoint(self, tmdb_service: TMDBService) -> None:
        """get_details() uses /tv/{id} for media_type='tv'."""
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": 42}
            await tmdb_service.get_details(42, media_type="tv")
        assert mock_req.call_args.args[0] == "/tv/42"

    @pytest.mark.asyncio
    async def test_get_details_movie_correct_endpoint(self, tmdb_service: TMDBService) -> None:
        """get_details() uses /movie/{id} for media_type='movie'."""
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": 10}
            await tmdb_service.get_details(10, media_type="movie")
        assert mock_req.call_args.args[0] == "/movie/10"

    @pytest.mark.asyncio
    async def test_get_recommendations_delegates_to_request(
        self, tmdb_service: TMDBService
    ) -> None:
        """get_recommendations() calls _request with correct endpoint."""
        expected = {"results": []}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = expected
            result = await tmdb_service.get_recommendations(7)
        assert result == expected
        assert mock_req.call_args.args[0] == "/tv/7/recommendations"

    @pytest.mark.asyncio
    async def test_get_recommendations_invalid_media_type_raises(
        self, tmdb_service: TMDBService
    ) -> None:
        """get_recommendations() raises ValueError for unknown media_type."""
        with pytest.raises(ValueError, match="media_type"):
            await tmdb_service.get_recommendations(1, media_type="podcast")

    @pytest.mark.asyncio
    async def test_get_external_ids_delegates_to_request(self, tmdb_service: TMDBService) -> None:
        """get_external_ids() calls _request with correct endpoint."""
        expected = {"imdb_id": "tt0108778"}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = expected
            result = await tmdb_service.get_external_ids(1668)
        assert result == expected
        assert mock_req.call_args.args[0] == "/tv/1668/external_ids"

    @pytest.mark.asyncio
    async def test_get_external_ids_invalid_media_type_raises(
        self, tmdb_service: TMDBService
    ) -> None:
        """get_external_ids() raises ValueError for unknown media_type."""
        with pytest.raises(ValueError, match="media_type"):
            await tmdb_service.get_external_ids(1, media_type="podcast")

    @pytest.mark.asyncio
    async def test_get_episode_groups_correct_endpoint(self, tmdb_service: TMDBService) -> None:
        """get_episode_groups() calls _request with correct endpoint."""
        expected = {"results": [{"id": "abc", "type": 6}]}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = expected
            result = await tmdb_service.get_episode_groups(1398)
        assert result == expected
        assert mock_req.call_args.args[0] == "/tv/1398/episode_groups"


class TestTMDBRequestHTTPLayer:
    """Test _request behaviour at the HTTP transport level."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http_call(self, tmdb_service: TMDBService) -> None:
        """When the cache is warm, no HTTP call is made."""
        cached = {"results": [{"id": 1}], "cached": True}
        with (
            patch.object(tmdb_module.cache, "get", AsyncMock(return_value=cached)),
            patch("httpx2.AsyncClient") as mock_cls,
        ):
            result = await tmdb_service.get_trending()

        assert result == cached
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_returns_json_and_populates_cache(
        self, tmdb_service: TMDBService
    ) -> None:
        """A 200 response is returned and stored in the cache."""
        payload = {"results": [{"id": 42}]}
        async with _patched_http(json_data=payload) as (_, mock_cache_set):
            result = await tmdb_service.get_trending(media_type="tv")

        assert result == payload
        mock_cache_set.assert_called_once()
        _, cached_value = mock_cache_set.call_args.args[:2]
        assert cached_value == payload

    @pytest.mark.asyncio
    async def test_http_404_raises_http_status_error(self, tmdb_service: TMDBService) -> None:
        """A 404 response propagates as httpx.HTTPStatusError."""
        req = httpx.Request("GET", "https://api.themoviedb.org/3/tv/99999")
        error = httpx.HTTPStatusError("404 Not Found", request=req, response=httpx.Response(404))
        async with _patched_http(raise_on_status=error):
            with pytest.raises(httpx.HTTPStatusError):
                await tmdb_service.get_details(99999)

    @pytest.mark.asyncio
    async def test_http_429_raises_http_status_error(self, tmdb_service: TMDBService) -> None:
        """A 429 rate-limit response propagates as httpx.HTTPStatusError."""
        req = httpx.Request("GET", "https://api.themoviedb.org/3/trending/multi/day")
        error = httpx.HTTPStatusError(
            "429 Too Many Requests", request=req, response=httpx.Response(429)
        )
        async with _patched_http(raise_on_status=error):
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await tmdb_service.get_trending()
        assert exc_info.value.response.status_code == 429

    @pytest.mark.asyncio
    async def test_network_timeout_propagates(self, tmdb_service: TMDBService) -> None:
        """A network timeout propagates as httpx.TimeoutException."""
        async with _patched_http(get_side_effect=httpx.ReadTimeout("timed out")):
            with pytest.raises(httpx.TimeoutException):
                await tmdb_service.get_trending()

    @pytest.mark.asyncio
    async def test_http_error_does_not_populate_cache(self, tmdb_service: TMDBService) -> None:
        """A failed HTTP request must not write anything to the cache."""
        req = httpx.Request("GET", "https://api.themoviedb.org/3/search/multi")
        error = httpx.HTTPStatusError("500 Server Error", request=req, response=httpx.Response(500))
        async with _patched_http(raise_on_status=error) as (_, mock_cache_set):
            with pytest.raises(httpx.HTTPStatusError):
                await tmdb_service.search("test")
        mock_cache_set.assert_not_called()
