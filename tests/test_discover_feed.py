"""Unit tests for jidou.services.discover_feed."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx2 as httpx

from jidou.services.discover_feed import collect_seeded, fill_from_trending


def _seed(show_id: int, tmdb_id: int, title: str, media_type: str = "tv") -> MagicMock:
    entry = MagicMock()
    entry.show.id = show_id
    entry.show.tmdb_id = tmdb_id
    entry.show.title = title
    entry.show.media_type = media_type
    return entry


def test_collect_seeded_merges_seeded_from_and_skips_existing() -> None:
    tmdb = AsyncMock()
    tmdb.get_recommendations = AsyncMock(
        side_effect=[
            {"results": [{"id": 1}, {"id": 2}]},
            {"results": [{"id": 1}, {"id": 3}]},
        ]
    )
    seeded = asyncio.run(
        collect_seeded(tmdb, [_seed(10, 100, "A"), _seed(11, 101, "B")], existing={(3, "tv")})
    )
    assert set(seeded) == {(1, "tv"), (2, "tv")}
    assert seeded[(1, "tv")].seeded_from == ["A", "B"]


def test_collect_seeded_skips_non_tv_movie_and_failed_lookups() -> None:
    tmdb = AsyncMock()
    tmdb.get_recommendations = AsyncMock(
        side_effect=httpx.HTTPStatusError("boom", request=MagicMock(), response=MagicMock())
    )
    seeds = [_seed(10, 100, "A", media_type="person"), _seed(11, 101, "B")]
    assert asyncio.run(collect_seeded(tmdb, seeds, existing=set())) == {}
    tmdb.get_recommendations.assert_awaited_once()


def test_fill_from_trending_stops_at_limit_and_dedupes() -> None:
    tmdb = AsyncMock()
    tmdb.get_trending = AsyncMock(
        return_value={
            "results": [
                {"id": 1, "media_type": "tv"},
                {"id": 2, "media_type": "person"},
                {"id": 3, "media_type": "movie"},
                {"id": 4, "media_type": "tv"},
            ]
        }
    )
    results = asyncio.run(fill_from_trending(tmdb, [], {}, existing={(1, "tv")}, limit=1))
    assert [(r.id, r.media_type) for r in results] == [(3, "movie")]


def test_fill_from_trending_returns_input_when_lookup_fails() -> None:
    tmdb = AsyncMock()
    tmdb.get_trending = AsyncMock(side_effect=ValueError("bad"))
    assert asyncio.run(fill_from_trending(tmdb, [], {}, existing=set(), limit=5)) == []
