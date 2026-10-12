"""Personalized discovery feed: watchlist-seeded TMDB recommendations + trending fill."""

import logging
from collections.abc import Sequence
from typing import Any

import httpx2 as httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.models.show import Show
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus
from jidou.schemas.discover_schema import DiscoverResult
from jidou.services.cache import cache
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

_MEDIA_TYPES = frozenset({"movie", "tv"})
type _Key = tuple[int, str]

# Number of most-recently-updated watching/completed watchlist entries used to
# seed recommendations. Each seed show costs one rate-limited TMDB call
# (~2s, serialized — the shared RateLimiter holds a single lock across all
# callers, so concurrency doesn't help here), so this also bounds worst-case
# latency on a cache-cold request to roughly _DISCOVER_SEED_LIMIT * 2s.
_DISCOVER_SEED_LIMIT = 5
# Recommendations taken from each seed show, before dedup/exclusion.
_DISCOVER_PER_SHOW_LIMIT = 10
_DISCOVER_CACHE_TTL = 86_400  # 24h — the assembled/deduped feed, not the underlying TMDB calls


def to_discover_result(
    raw: dict[str, Any], media_type: str, seeded_from: list[str]
) -> DiscoverResult:
    """Build a :class:`DiscoverResult` from a raw TMDB result dict.

    Args:
        raw: Raw TMDB result entry (from a recommendations or trending response).
        media_type: ``"tv"`` or ``"movie"`` — recommendations responses are
            already scoped to one type and don't include this field themselves.
        seeded_from: Watchlist show titles this result was recommended because
            of. Empty for trending-only fill items.

    Returns:
        A populated :class:`DiscoverResult`.
    """
    return DiscoverResult(
        id=raw["id"],
        media_type=media_type,
        name=raw.get("name"),
        title=raw.get("title"),
        overview=raw.get("overview"),
        poster_path=raw.get("poster_path"),
        backdrop_path=raw.get("backdrop_path"),
        vote_average=raw.get("vote_average"),
        vote_count=raw.get("vote_count"),
        release_date=raw.get("release_date"),
        first_air_date=raw.get("first_air_date"),
        original_language=raw.get("original_language"),
        genre_ids=raw.get("genre_ids"),
        origin_country=raw.get("origin_country"),
        adult=raw.get("adult"),
        seeded_from=seeded_from,
    )


async def build_discover_feed(
    session: AsyncSession, tmdb: TMDBService, limit: int
) -> list[DiscoverResult]:
    """Return the discovery feed, served from a 24h cache keyed by the seed set.

    Seeded from TMDB recommendations for the user's most recently engaged
    watchlist shows, deduplicated against the library and topped up with
    weekly-trending titles when the seeded results fall short of *limit*.

    Args:
        session: Active async DB session.
        tmdb: TMDB service.
        limit: Maximum results.

    Returns:
        Seeded results first (most seeds, then rating), then trending fill.
    """
    seed_entries = await _load_seed_entries(session)
    cache_key = cache.make_key(
        "discover:"
        + ",".join(sorted(f"{e.show.tmdb_id}:{e.show.media_type}" for e in seed_entries))
    )
    cached = await cache.get(cache_key)
    if cached is not None:
        return [DiscoverResult(**item) for item in cached][:limit]

    existing: set[_Key] = {
        (t, m) for t, m in (await session.execute(select(Show.tmdb_id, Show.media_type))).all()
    }
    seeded = await collect_seeded(tmdb, seed_entries, existing)
    results = sorted(seeded.values(), key=lambda r: (-len(r.seeded_from), -(r.vote_average or 0)))
    if len(results) < limit:
        results = await fill_from_trending(tmdb, results, seeded, existing, limit=limit)

    results = results[:limit]
    await cache.set(
        cache_key, [r.model_dump() for r in results], label="discover", ttl=_DISCOVER_CACHE_TTL
    )
    return results


async def _load_seed_entries(session: AsyncSession) -> Sequence[WatchlistEntry]:
    """Return the most recently updated watching/completed watchlist entries."""
    stmt = (
        select(WatchlistEntry)
        .where(WatchlistEntry.status.in_([WatchlistStatus.WATCHING, WatchlistStatus.COMPLETED]))
        .options(selectinload(WatchlistEntry.show))
        .order_by(WatchlistEntry.updated_at.desc())
        .limit(_DISCOVER_SEED_LIMIT)
    )
    return (await session.execute(stmt)).scalars().all()


async def collect_seeded(
    tmdb: TMDBService, seed_entries: Sequence[WatchlistEntry], existing: set[_Key]
) -> dict[_Key, DiscoverResult]:
    """Gather TMDB recommendations for each seed, merging ``seeded_from`` on repeats.

    Args:
        tmdb: TMDB service.
        seed_entries: Watchlist entries whose shows seed the feed.
        existing: ``(tmdb_id, media_type)`` keys already in the library.

    Returns:
        Results keyed by ``(tmdb_id, media_type)``.
    """
    seeded: dict[_Key, DiscoverResult] = {}
    for entry in seed_entries:
        show = entry.show
        if show.media_type not in _MEDIA_TYPES:
            continue
        try:
            data = await tmdb.get_recommendations(show.tmdb_id, show.media_type)
        except (ValueError, httpx.HTTPStatusError):
            logger.warning("Discover: recommendations failed for show_id=%d", show.id)
            continue
        for raw in data.get("results", [])[:_DISCOVER_PER_SHOW_LIMIT]:
            key = (raw["id"], show.media_type)
            if key in existing:
                continue
            if key in seeded:
                seeded[key].seeded_from.append(show.title)
            else:
                seeded[key] = to_discover_result(raw, show.media_type, [show.title])
    return seeded


async def fill_from_trending(
    tmdb: TMDBService,
    results: list[DiscoverResult],
    seeded: dict[_Key, DiscoverResult],
    existing: set[_Key],
    *,
    limit: int,
) -> list[DiscoverResult]:
    """Append weekly-trending items not already present until *limit* is reached.

    Args:
        tmdb: TMDB service.
        results: Seeded results so far (extended in place and returned).
        seeded: Keys already used (extended in place).
        existing: Library keys to exclude.
        limit: Target result count.

    Returns:
        *results*, extended.
    """
    try:
        trending = await tmdb.get_trending(media_type="multi", time_window="week")
    except (ValueError, httpx.HTTPStatusError):
        logger.warning("Discover: trending fallback failed")
        return results
    for raw in trending.get("results", []):
        media_type = raw.get("media_type")
        if media_type not in _MEDIA_TYPES:
            continue
        key = (raw["id"], media_type)
        if key in existing or key in seeded:
            continue
        seeded[key] = to_discover_result(raw, media_type, [])
        results.append(seeded[key])
        if len(results) >= limit:
            break
    return results
