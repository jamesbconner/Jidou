"""Tests for the /shows discovery API routes (api/shows.py — TMDB delegation)."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_trending_delegates_to_tmdb() -> None:
    """get_trending() calls TMDBService.get_trending with the given params."""
    from jidou.api.shows import get_trending

    expected = {"results": [{"id": 1, "name": "Show A"}]}

    with patch(
        "jidou.api.shows.tmdb.get_trending",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_tmdb:
        result = await get_trending(media_type="tv", time_window="week")

    mock_tmdb.assert_called_once_with(media_type="tv", time_window="week")
    assert result == expected


@pytest.mark.asyncio
async def test_search_shows_delegates_to_tmdb() -> None:
    """search_shows() calls TMDBService.search with the given query and media_type."""
    from jidou.api.shows import search_shows

    expected = {"results": [{"id": 99, "name": "Found"}]}

    with patch(
        "jidou.api.shows.tmdb.search",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_tmdb:
        result = await search_shows(query="Breaking", media_type="tv")

    mock_tmdb.assert_called_once_with(query="Breaking", media_type="tv")
    assert result == expected


@pytest.mark.asyncio
async def test_get_show_details_delegates_to_tmdb() -> None:
    """get_show_details() calls TMDBService.get_details with tmdb_id and media_type."""
    from jidou.api.shows import get_show_details

    expected = {"id": 1396, "name": "Breaking Bad"}

    with patch(
        "jidou.api.shows.tmdb.get_details",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_tmdb:
        result = await get_show_details(tmdb_id=1396, media_type="tv")

    mock_tmdb.assert_called_once_with(tmdb_id=1396, media_type="tv")
    assert result == expected
