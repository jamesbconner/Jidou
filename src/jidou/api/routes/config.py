"""API routes for configuration read and connection testing."""

import logging
from typing import Any

from fastapi import APIRouter

from jidou.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    """Return non-sensitive application configuration.

    Secrets (API keys, passwords) are redacted.  This endpoint is useful for
    verifying which settings are active without inspecting environment variables
    directly.

    Returns:
        Dictionary of visible configuration values.
    """
    return {
        "app_name": settings.app_name,
        "debug": settings.debug,
        "database_url": _redact(settings.database_url),
        "redis_url": _redact(settings.redis_url) if settings.redis_url else None,
        "tmdb_api_key_set": bool(settings.tmdb_api_key),
        "tmdb_base_url": settings.tmdb_base_url,
        "tmdb_rate_limit_per_second": settings.tmdb_rate_limit_per_second,
        "tmdb_cache_ttl": settings.tmdb_cache_ttl,
        "allowed_origins": settings.cors_origins,
        "sftp_host": settings.sftp_host,
        "sftp_port": settings.sftp_port,
        "sftp_username": settings.sftp_username,
        "sftp_remote_paths": settings.sftp_remote_paths,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_base_url": settings.llm_base_url or None,
        "llm_cache_ttl": settings.llm_cache_ttl,
    }


@router.post("/test/tmdb")
async def test_tmdb() -> dict[str, Any]:
    """Test TMDB API key by fetching a minimal trending result.

    Returns:
        ``{"ok": True}`` on success or ``{"ok": False, "error": "..."}`` on
        failure.
    """
    if not settings.tmdb_api_key:
        return {"ok": False, "error": "TMDB_API_KEY is not configured"}

    try:
        from jidou.services.tmdb import TMDBService

        tmdb = TMDBService()
        await tmdb.get_trending(media_type="movie", time_window="day")
        return {"ok": True}
    except Exception as exc:
        logger.warning("TMDB test failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/test/sftp")
async def test_sftp() -> dict[str, Any]:
    """Test SFTP connectivity by listing the configured remote base path.

    Returns:
        ``{"ok": True, "file_count": N}`` on success or
        ``{"ok": False, "error": "..."}`` on failure.
    """
    if not settings.sftp_host:
        return {"ok": False, "error": "SFTP_HOST is not configured"}

    try:
        from jidou.services.sftp_service import SFTPService

        sftp = SFTPService(
            host=settings.sftp_host,
            port=settings.sftp_port,
            username=settings.sftp_username or "",
            password=settings.sftp_password,
            key_path=settings.sftp_key_path,
            remote_base_path=settings.sftp_remote_paths_list[0]
            if settings.sftp_remote_paths_list
            else "/",
            max_retries=settings.sftp_max_retries,
            retry_delay=settings.sftp_retry_delay,
        )
        files = await sftp.list_remote_files()
        return {"ok": True, "file_count": len(files)}
    except Exception as exc:
        logger.warning("SFTP test failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/test/llm")
async def test_llm() -> dict[str, Any]:
    """Test LLM connectivity by sending a minimal completion request.

    Uses :meth:`LLMService.test_connection` which propagates real provider
    errors (auth failures, unreachable hosts) rather than swallowing them.

    Returns:
        ``{"ok": True, "message": "Nms (provider / model)"}`` on success or
        ``{"ok": False, "error": "..."}`` on failure.
    """
    if settings.llm_provider.lower() == "none":
        return {"ok": False, "error": "LLM provider is set to 'none'"}
    if not settings.llm_model:
        return {"ok": False, "error": "LLM_MODEL is not configured"}

    try:
        from jidou.services.llm_service import LLMService

        llm = LLMService(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
        )
        latency_s, model = await llm.test_connection()
        latency_ms = round(latency_s * 1000, 1)
        return {
            "ok": True,
            "message": f"{latency_ms}ms ({settings.llm_provider} / {model})",
        }
    except Exception as exc:
        logger.warning("LLM test failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/test/redis")
async def test_redis() -> dict[str, Any]:
    """Test Redis connectivity by sending a PING command.

    Returns:
        ``{"ok": True}`` on success or ``{"ok": False, "error": "..."}`` on
        failure.
    """
    redis_url = settings.redis_url
    if not redis_url:
        return {"ok": False, "error": "REDIS_URL is not configured"}

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url)
        try:
            await r.ping()
            return {"ok": True}
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("Redis test failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redact(url: str) -> str:
    """Replace the password portion of a database URL with ``***``.

    Args:
        url: A connection URL potentially containing credentials.

    Returns:
        The URL with any password replaced by ``***``.
    """
    # Simple heuristic: replace everything between :// ... @ with redacted creds
    if "://" not in url or "@" not in url:
        return url
    scheme_rest = url.split("://", 1)
    creds_host = scheme_rest[1].rsplit("@", 1)
    if ":" in creds_host[0]:
        user = creds_host[0].split(":", 1)[0]
        return f"{scheme_rest[0]}://{user}:***@{creds_host[1]}"
    return url
