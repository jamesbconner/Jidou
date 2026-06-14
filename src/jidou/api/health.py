"""Health check endpoint for Docker and operational monitoring."""

import logging
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from jidou.config import settings
from jidou.database import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/")
async def health_check() -> dict[str, Any]:
    """Check the health of all dependent services.

    Returns:
        Dictionary with overall status and per-service health details.

    Raises:
        HTTPException: 503 when core dependencies are unhealthy.
    """
    services: dict[str, dict[str, Any]] = {}
    overall_healthy = True

    # Check PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        services["postgres"] = {"status": "healthy"}
    except Exception as exc:
        logger.error("PostgreSQL health check failed: %s", exc)
        services["postgres"] = {"status": "unhealthy", "error": str(exc)}
        overall_healthy = False

    # Check Redis
    try:
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        try:
            await redis_client.ping()
            services["redis"] = {"status": "healthy"}
        finally:
            await redis_client.close()
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        services["redis"] = {"status": "unhealthy", "error": str(exc)}
        overall_healthy = False

    # Check TMDB API key configured
    services["tmdb"] = {
        "status": "configured" if settings.tmdb_api_key else "not-configured",
    }

    if not overall_healthy:
        raise HTTPException(status_code=503, detail={
            "status": "degraded",
            "timestamp": datetime.now(UTC).isoformat(),
            "services": services,
        })

    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "services": services,
    }
