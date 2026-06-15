"""Tests for TMDB service with mocked HTTP calls."""

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
        """Test service initializes with correct API key."""
        assert tmdb_service.api_key == "test-key"
        assert tmdb_service.base_url.endswith("/3")

    @pytest.mark.asyncio
    async def test_request_without_api_key_raises(self) -> None:
        """Test that request without API key raises ValueError."""
        service = TMDBService(api_key=None)
        with (
            patch.object(service, "api_key", None),
            pytest.raises(ValueError, match="TMDB_API_KEY"),
        ):
            await service.get_trending()

    @pytest.mark.asyncio
    async def test_get_trending_calls_request(self, tmdb_service: TMDBService) -> None:
        """Test that get_trending delegates to _request."""
        mock_response = {"results": [], "total_results": 0}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await tmdb_service.get_trending()

            assert result == mock_response
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_calls_request(self, tmdb_service: TMDBService) -> None:
        """Test that search delegates to _request."""
        mock_response = {"results": [], "total_results": 0}
        with patch.object(tmdb_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await tmdb_service.search("test query")

            assert result == mock_response
            mock_request.assert_called_once()
