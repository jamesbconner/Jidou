"""Serves cached TMDB poster/backdrop images, fetching from TMDB on a miss.

Deliberately registered without the ``X-API-Key`` dependency (see
``main.py``): plain ``<img src>`` tags can't send custom headers, and TMDB
poster/backdrop images aren't sensitive data, so gating them adds no real
confidentiality while breaking normal browser image loading and caching.
"""

import logging
import re

import httpx2 as httpx
from fastapi import APIRouter, HTTPException, Response

from jidou.config import settings
from jidou.services.image_cache import image_cache_backend
from jidou.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

_VALID_SIZES = frozenset({"w92", "w185", "w300", "w500"})
_FILENAME_RE = re.compile(r"^[A-Za-z0-9]+\.(jpg|png)$")
_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

# Browser-side caching, independent of the backend's own disk retention
# (settings.image_cache_retention_days).
_BROWSER_CACHE_MAX_AGE = 604_800  # 7 days

# Separate rate-limiter key from the metadata TMDB limiter (services.rate_limiter.rate_limiter)
# so bursty image loads — a single show detail page can request dozens of
# posters — never starve TMDBService's own API calls.
_image_rate_limiter = RateLimiter(
    rate=settings.tmdb_rate_limit_per_second,
    redis_url=settings.redis_url or None,
    key="tmdb_images",
)


def _validate_size(size: str) -> None:
    """Raise 400 if *size* isn't one of the supported TMDB image widths."""
    if size not in _VALID_SIZES:
        raise HTTPException(status_code=400, detail=f"Unsupported image size: {size!r}")


def _validate_filename(filename: str) -> None:
    """Raise 400 if *filename* doesn't match TMDB's image filename shape.

    Also rejects path traversal attempts (``..``, embedded separators) since
    anything not matching the alnum+extension pattern is refused.
    """
    if not _FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid image filename")


def _media_type_for(filename: str) -> str:
    """Return the response Content-Type for *filename* based on its extension."""
    return "image/png" if filename.endswith(".png") else "image/jpeg"


def _cache_headers() -> dict[str, str]:
    return {"Cache-Control": f"public, max-age={_BROWSER_CACHE_MAX_AGE}"}


@router.get("/{size}/{filename}")
async def get_image(size: str, filename: str) -> Response:
    """Serve a TMDB poster/backdrop image, caching it to disk on first request.

    Args:
        size: One of ``w92``, ``w185``, ``w300``, ``w500``.
        filename: TMDB image filename (e.g. ``abc123.jpg``).

    Returns:
        Raw image bytes with a Content-Type and browser Cache-Control header.

    Raises:
        HTTPException: 400 for an unsupported size or malformed filename,
            404 if TMDB has no such image, 502 for other upstream failures.
    """
    _validate_size(size)
    _validate_filename(filename)

    cached = await image_cache_backend.get(size, filename)
    if cached is not None:
        return Response(cached, media_type=_media_type_for(filename), headers=_cache_headers())

    url = f"{_TMDB_IMAGE_BASE}/{size}/{filename}"
    try:
        async with _image_rate_limiter.acquire(), httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 404:
            raise HTTPException(status_code=404, detail="Image not found on TMDB") from exc
        logger.warning("TMDB image fetch failed for %s: HTTP %s", url, status_code)
        raise HTTPException(status_code=502, detail="Upstream image fetch failed") from exc
    except httpx.HTTPError as exc:
        logger.warning("TMDB image fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail="Upstream image fetch failed") from exc

    data = response.content
    await image_cache_backend.put(size, filename, data)
    return Response(data, media_type=_media_type_for(filename), headers=_cache_headers())
