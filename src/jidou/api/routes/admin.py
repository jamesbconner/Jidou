"""API routes for admin operations: stats, cache, health."""

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Date, and_, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.models.task import BackgroundTask
from jidou.models.watchlist import WatchlistEntry
from jidou.schemas.admin_schema import StatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_NEEDS_ATTENTION = ("unmatched", "error")


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StatsResponse:
    """Return dashboard statistics.

    Args:
        db_session: DB session (injected).

    Returns:
        Labelled counts for the dashboard stat cards.
    """
    now = datetime.now(UTC)

    # Correlated subqueries for per-show aggregates used in DQ checks.
    ep_count_sq = (
        select(func.count(Episode.id))
        .where(Episode.show_id == Show.id)
        .correlate(Show)
        .scalar_subquery()
    )
    file_count_sq = (
        select(func.count(DownloadedFile.id))
        .where(DownloadedFile.show_id == Show.id)
        .correlate(Show)
        .scalar_subquery()
    )

    episodes_tracked = await db_session.scalar(
        select(func.count()).select_from(Episode).where(Episode.file_tracked.is_(True))
    )
    episodes_total = await db_session.scalar(select(func.count()).select_from(Episode))

    files_needs_attention = await db_session.scalar(
        select(func.count())
        .select_from(DownloadedFile)
        .where(DownloadedFile.status.in_(_NEEDS_ATTENTION))
    )

    # Use UTC calendar-day boundaries so stat cards align with the bar chart.
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    files_added_1d = await db_session.scalar(
        select(func.count()).select_from(Episode).where(Episode.file_tracked_at >= today_start)
    )
    files_added_7d = await db_session.scalar(
        select(func.count())
        .select_from(Episode)
        .where(Episode.file_tracked_at >= today_start - timedelta(days=6))
    )
    files_added_30d = await db_session.scalar(
        select(func.count())
        .select_from(Episode)
        .where(Episode.file_tracked_at >= today_start - timedelta(days=29))
    )

    shows = await db_session.scalar(select(func.count()).select_from(Show))
    watchlist = await db_session.scalar(select(func.count()).select_from(WatchlistEntry))
    background_tasks = await db_session.scalar(select(func.count()).select_from(BackgroundTask))

    # Data quality counts — mirrors the checks in the frontend DQ tab.
    dq_no_path = await db_session.scalar(
        select(func.count()).select_from(Show).where(Show.local_path.is_(None))
    )
    dq_no_content_type = await db_session.scalar(
        select(func.count()).select_from(Show).where(Show.content_type.is_(None))
    )
    dq_no_episodes = await db_session.scalar(
        select(func.count()).select_from(Show).where(Show.media_type != "movie", ep_count_sq == 0)
    )
    dq_orphan = await db_session.scalar(
        select(func.count())
        .select_from(Show)
        .where(
            Show.media_type != "movie",
            or_(Show.media_type == "tv", Show.content_type == "anime"),
            ep_count_sq == 0,
            file_count_sq == 0,
        )
    )
    # Total unique shows with any DQ issue (union of the first three checks;
    # orphan is a subset of no_episodes so it doesn't add new shows here).
    dq_total = await db_session.scalar(
        select(func.count())
        .select_from(Show)
        .where(
            or_(
                Show.local_path.is_(None),
                Show.content_type.is_(None),
                and_(Show.media_type != "movie", ep_count_sq == 0),
            )
        )
    )

    return StatsResponse(
        shows=shows or 0,
        episodes_tracked=episodes_tracked or 0,
        episodes_total=episodes_total or 0,
        files_needs_attention=files_needs_attention or 0,
        files_added_1d=files_added_1d or 0,
        files_added_7d=files_added_7d or 0,
        files_added_30d=files_added_30d or 0,
        watchlist=watchlist or 0,
        background_tasks=background_tasks or 0,
        dq_total=dq_total or 0,
        dq_no_path=dq_no_path or 0,
        dq_no_content_type=dq_no_content_type or 0,
        dq_no_episodes=dq_no_episodes or 0,
        dq_orphan=dq_orphan or 0,
    )


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
    # Start of day 29 days ago UTC — aligns with the 30 calendar-day window the frontend builds.
    today_utc = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today_utc - timedelta(days=29)

    # func.timezone converts TIMESTAMPTZ to a UTC TIMESTAMP before DATE cast,
    # so bucketing is always UTC regardless of the DB session timezone.
    utc_day = cast(func.timezone("UTC", Episode.file_tracked_at), Date)
    stmt = (
        select(utc_day.label("day"), func.count().label("count"))
        .where(Episode.file_tracked_at >= cutoff)
        .group_by(utc_day)
        .order_by(utc_day)
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
    """Inspect the shared Redis-backed TMDB response cache.

    Returns:
        Dictionary with current entry count, configured capacity and TTL,
        and a list of active entries with their TMDB endpoint labels.
    """
    from jidou.services.cache import cache

    return await cache.stats()


@router.post("/cache/flush")
async def flush_cache() -> dict[str, Any]:
    """Flush the shared Redis-backed TMDB response cache.

    Returns:
        ``{"ok": True, "cleared": N}`` where N is the number of entries removed.
    """
    from jidou.services.cache import cache

    count = await cache.flush()

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
