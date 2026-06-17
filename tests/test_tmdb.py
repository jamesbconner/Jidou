"""Tests for TMDB service with mocked HTTP calls."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

from jidou.services.tmdb import TMDBService


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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = slow_get  # deliberately not AsyncMock to preserve await semantics

        @asynccontextmanager  # type: ignore[arg-type]
        async def noop_acquire() -> AsyncGenerator[None]:
            yield

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch.object(tmdb_module.rate_limiter, "acquire", noop_acquire),
        ):
            results = await asyncio.gather(
                tmdb_service.get_trending(),
                tmdb_service.get_trending(),
                tmdb_service.get_trending(),
            )

        assert all(r == mock_response_data for r in results)
        assert http_calls == 1, f"Expected 1 HTTP call, got {http_calls}"
