"""Health check endpoint for Docker and operational monitoring."""

import logging
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from jidou.config import settings
from jidou.database import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """Check the health of all dependent services.

    Returns HTTP 200 when all dependencies are healthy, HTTP 503 when
    one or more are unreachable. Docker and orchestration probes can
    inspect the HTTP status to determine container health.
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
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis_client.ping()
            services["redis"] = {"status": "healthy"}
        except Exception as exc:
            logger.error("Redis health check failed: %s", exc)
            services["redis"] = {"status": "unhealthy", "error": str(exc)}
            overall_healthy = False
        finally:
            await redis_client.aclose()
    except Exception as exc:
        logger.error("Redis client creation failed: %s", exc)
        services["redis"] = {"status": "unhealthy", "error": str(exc)}
        overall_healthy = False

    # Check TMDB API key configured
    services["tmdb"] = {
        "status": "configured" if settings.tmdb_api_key else "not-configured",
    }

    body = {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": datetime.now(UTC).isoformat(),
        "services": services,
    }

    return JSONResponse(
        content=body,
        status_code=200 if overall_healthy else 503,
    )
