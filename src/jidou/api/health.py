"""Health check endpoint for Docker and operational monitoring."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from jidou import __version__
from jidou.config import settings
from jidou.database import engine
from jidou.services.health_probes import ping_redis, run_probe

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """Check the health of all dependent services.

    Returns HTTP 200 when all dependencies are healthy, HTTP 503 when
    one or more are unreachable. Docker and orchestration probes can
    inspect the HTTP status to determine container health. The body also
    reports the running application ``version``.
    """
    services: dict[str, dict[str, Any]] = {}

    async def check_postgres() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    probes = {
        "postgres": await run_probe(check_postgres),
        # Redis is required for this probe (Docker HEALTHCHECK): failure -> 503.
        "redis": await run_probe(lambda: ping_redis(settings.redis_url, decode_responses=True)),
    }
    for name, result in probes.items():
        if result.ok:
            services[name] = {"status": "healthy"}
        else:
            logger.error("%s health check failed: %s", name, result.error)
            services[name] = {"status": "unhealthy", "error": result.error or ""}
    overall_healthy = all(r.ok for r in probes.values())

    # Check TMDB API key configured
    services["tmdb"] = {
        "status": "configured" if settings.tmdb_api_key else "not-configured",
    }

    # Check SFTP host configured
    services["sftp"] = {
        "status": "configured" if settings.sftp_host else "not-configured",
    }

    body = {
        "status": "healthy" if overall_healthy else "degraded",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
        "services": services,
    }

    return JSONResponse(
        content=body,
        status_code=200 if overall_healthy else 503,
    )
