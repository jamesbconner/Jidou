"""API routes for admin operations: stats, cache, health."""

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import cast, func, select, text
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

_NEEDS_ATTENTION = ("unmatched", "error")


@router.get("/stats")
async def get_stats(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Return dashboard statistics.

    Args:
        db_session: DB session (injected).

    Returns:
        Dictionary of labelled counts for the dashboard stat cards.
    """
    now = datetime.now(UTC)

    episodes_tracked = await db_session.scalar(
        select(func.count()).select_from(Episode).where(Episode.file_tracked.is_(True))
    )
    episodes_total = await db_session.scalar(select(func.count()).select_from(Episode))

    files_needs_attention = await db_session.scalar(
        select(func.count())
        .select_from(DownloadedFile)
        .where(DownloadedFile.status.in_(_NEEDS_ATTENTION))
    )

    files_added_1d = await db_session.scalar(
        select(func.count())
        .select_from(Episode)
        .where(Episode.file_tracked_at >= now - timedelta(days=1))
    )
    files_added_7d = await db_session.scalar(
        select(func.count())
        .select_from(Episode)
        .where(Episode.file_tracked_at >= now - timedelta(days=7))
    )
    files_added_30d = await db_session.scalar(
        select(func.count())
        .select_from(Episode)
        .where(Episode.file_tracked_at >= now - timedelta(days=30))
    )

    shows = await db_session.scalar(select(func.count()).select_from(Show))
    watchlist = await db_session.scalar(select(func.count()).select_from(WatchlistEntry))
    background_tasks = await db_session.scalar(select(func.count()).select_from(BackgroundTask))

    return {
        "shows": shows or 0,
        "episodes_tracked": episodes_tracked or 0,
        "episodes_total": episodes_total or 0,
        "files_needs_attention": files_needs_attention or 0,
        "files_added_1d": files_added_1d or 0,
        "files_added_7d": files_added_7d or 0,
        "files_added_30d": files_added_30d or 0,
        "watchlist": watchlist or 0,
        "background_tasks": background_tasks or 0,
    }


@router.get("/stats/files-timeline")
async def get_files_timeline(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, Any]]:
    """Return daily file counts for the past 30 days.

    Args:
        db_session: DB session (injected).

    Returns:
        List of ``{"date": "YYYY-MM-DD", "count": N}`` ordered ascending by date.
    """
    cutoff = datetime.now(UTC) - timedelta(days=30)
    from sqlalchemy import Date

    stmt = (
        select(
            cast(Episode.file_tracked_at, Date).label("day"),
            func.count().label("count"),
        )
        .where(Episode.file_tracked_at >= cutoff)
        .group_by(cast(Episode.file_tracked_at, Date))
        .order_by(cast(Episode.file_tracked_at, Date))
    )
    rows = (await db_session.execute(stmt)).all()
    return [{"date": str(row.day), "count": row.count} for row in rows]


@router.get("/stats/pipeline-status")
async def get_pipeline_status(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, Any]]:
    """Return current file counts grouped by pipeline status.

    Args:
        db_session: DB session (injected).

    Returns:
        List of ``{"status": str, "count": N}`` ordered by count descending.
    """
    stmt = (
        select(DownloadedFile.status.label("status"), func.count().label("count"))
        .group_by(DownloadedFile.status)
        .order_by(func.count().desc())
    )
    rows = (await db_session.execute(stmt)).all()
    return [{"status": row.status, "count": row.count} for row in rows]


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

    # LLM (config check only — live test available via POST /config/test/llm)
    llm_configured = settings.llm_provider.lower() != "none" and bool(settings.llm_model)
    results["llm"] = {"ok": True, "configured": llm_configured}
    if llm_configured:
        results["llm"]["provider"] = settings.llm_provider
        results["llm"]["model"] = settings.llm_model
    else:
        results["llm"]["error"] = (
            "LLM_MODEL not set" if settings.llm_provider.lower() != "none" else "not configured"
        )

    overall = all(v.get("ok") for v in results.values())
    return {"healthy": overall, "services": results}
