"""API routes for admin operations: stats, cache, health."""

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.models.task import BackgroundTask
from jidou.models.watchlist import WatchlistEntry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def get_stats(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Return row counts for each major database table.

    Args:
        db_session: DB session (injected).

    Returns:
        Dictionary mapping table name to row count.
    """
    counts: dict[str, int] = {}
    for model, label in [
        (Show, "shows"),
        (Episode, "episodes"),
        (DownloadedFile, "downloaded_files"),
        (WatchlistEntry, "watchlist"),
        (BackgroundTask, "background_tasks"),
    ]:
        result = await db_session.execute(select(func.count()).select_from(model))
        counts[label] = result.scalar_one()

    return counts


@router.get("/cache")
async def get_cache() -> dict[str, Any]:
    """Inspect the in-memory TMDB response cache.

    Returns:
        Dictionary with current entry count, configured capacity and TTL,
        and a list of active entries with their TMDB endpoint labels.
    """
    from jidou.services.cache import cache

    return await cache.stats()


@router.post("/cache/flush")
async def flush_cache() -> dict[str, Any]:
    """Flush the in-memory TMDB response cache.

    Returns:
        ``{"ok": True, "cleared": N}`` where N is the number of entries removed.
    """
    from jidou.services.cache import cache

    async with cache._lock:
        count = len(cache._cache)
        cache._cache.clear()
        cache._labels.clear()

    logger.info("Admin: flushed %d cache entries", count)
    return {"ok": True, "cleared": count}


@router.get("/health")
async def system_health(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Run a comprehensive system health check.

    Checks the database, Redis (if configured), and TMDB API key presence.
    Each check reports ``ok``, ``latency_ms``, and an optional ``error`` field.

    Args:
        db_session: DB session (injected).

    Returns:
        Dictionary with an overall ``healthy`` flag and per-service results.
    """
    results: dict[str, Any] = {}

    # Database
    t0 = time.monotonic()
    try:
        await db_session.execute(text("SELECT 1"))
        results["database"] = {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as exc:
        results["database"] = {
            "ok": False,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "error": str(exc),
        }

    # Redis
    redis_url = settings.redis_url
    if redis_url:
        t0 = time.monotonic()
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url)
            try:
                await r.ping()
                results["redis"] = {
                    "ok": True,
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                }
            finally:
                await r.aclose()
        except Exception as exc:
            results["redis"] = {
                "ok": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "error": str(exc),
            }
    else:
        # Redis is optional — mark as not configured, not failed.
        # An unconfigured optional service must not drag overall health to false.
        results["redis"] = {"ok": True, "configured": False}

    # TMDB (config check only — no network call to avoid rate limit)
    results["tmdb"] = {
        "ok": bool(settings.tmdb_api_key),
        "configured": bool(settings.tmdb_api_key),
    }
    if not settings.tmdb_api_key:
        results["tmdb"]["error"] = "TMDB_API_KEY not set"

    overall = all(v.get("ok") for v in results.values())
    return {"healthy": overall, "services": results}
