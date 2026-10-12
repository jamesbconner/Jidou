"""API routes for admin operations: stats, cache, health."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Date, and_, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from jidou import __version__
from jidou.config import settings
from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.models.task import BackgroundTask
from jidou.models.watchlist import WatchlistEntry
from jidou.schemas.admin_schema import StatsResponse
from jidou.services.health_probes import ProbeFailedError, ping_redis, run_probe
from jidou.workers.celery_app import celery_app

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


async def _read_alembic_version(db_session: AsyncSession) -> str | None:
    """Return the applied alembic revision, or None if it can't be read.

    Args:
        db_session: DB session (injected).

    Returns:
        The revision id, or None when the lookup fails (the session is rolled back).
    """
    try:
        result = await db_session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("Could not read alembic_version: %s", exc)
        await db_session.rollback()
        return None


def _config_checks() -> dict[str, dict[str, Any]]:
    """Presence-only checks for TMDB, SFTP and LLM configuration.

    No network calls: TMDB is rate-limited, and live SFTP/LLM tests are available via
    POST /config/test/*.

    Returns:
        Per-service result dicts keyed ``tmdb``, ``sftp``, ``llm``.
    """
    results: dict[str, dict[str, Any]] = {
        "tmdb": {"ok": bool(settings.tmdb_api_key), "configured": bool(settings.tmdb_api_key)},
        "sftp": {"ok": bool(settings.sftp_host), "configured": bool(settings.sftp_host)},
    }
    if not settings.tmdb_api_key:
        results["tmdb"]["error"] = "TMDB_API_KEY not set"
    if not settings.sftp_host:
        results["sftp"]["error"] = "SFTP_HOST not set"
    llm_configured = settings.llm_provider.lower() != "none" and bool(settings.llm_model)
    results["llm"] = {"ok": True, "configured": llm_configured}
    if llm_configured:
        results["llm"]["provider"] = settings.llm_provider
        results["llm"]["model"] = settings.llm_model
    else:
        results["llm"]["error"] = (
            "LLM_MODEL not set" if settings.llm_provider.lower() != "none" else "not configured"
        )
    return results


@router.get("/health")
async def system_health(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Run a comprehensive system health check.

    Checks the database, Redis (if configured), Celery worker liveness, and
    TMDB/SFTP/LLM configuration presence. Each check reports ``ok`` and,
    where applicable, ``latency_ms`` and an optional ``error`` field.

    Args:
        db_session: DB session (injected).

    Returns:
        Dictionary with an overall ``healthy`` flag, the running application
        ``version``, and per-service results.
    """

    async def check_database() -> dict[str, Any]:
        await db_session.execute(text("SELECT 1"))
        # Surface the applied migration revision so a stale schema after a deploy
        # is visible here instead of only showing up as a downstream 500.
        return {"alembic_version": await _read_alembic_version(db_session)}

    async def check_celery() -> dict[str, Any]:
        # A reachable broker doesn't prove a worker is consuming; ping workers directly.
        pong = await asyncio.to_thread(celery_app.control.inspect(timeout=2.0).ping)
        if not pong:
            raise ProbeFailedError("No Celery workers responded to ping")
        return {"workers": list(pong.keys())}

    redis_url = settings.redis_url
    results: dict[str, Any] = {
        "database": (await run_probe(check_database)).as_dict(),
        # Redis is optional here: unconfigured must not drag overall health to false.
        "redis": (
            (await run_probe(lambda: ping_redis(redis_url))).as_dict()
            if redis_url
            else {"ok": True, "configured": False}
        ),
        "celery": (await run_probe(check_celery)).as_dict(),
        **_config_checks(),
    }
    overall = all(v.get("ok") for v in results.values())
    return {"healthy": overall, "version": __version__, "services": results}
