"""Serves cached TMDB poster/backdrop images, fetching from TMDB on a miss.

Deliberately registered without the ``X-API-Key`` dependency (see
``main.py``): plain ``<img src>`` tags can't send custom headers, and TMDB
poster/backdrop images aren't sensitive data, so gating them adds no real
confidentiality while breaking normal browser image loading and caching.
"""

import asyncio
import logging
import re

import httpx2 as httpx
from fastapi import APIRouter, HTTPException, Response

from jidou.services.image_cache import ImageCacheBackend, image_cache_backend
from jidou.services.rate_limiter import image_rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

_VALID_SIZES = frozenset({"w92", "w185", "w300", "w500", "w780", "w1280"})
_FILENAME_RE = re.compile(r"^[A-Za-z0-9]+\.(jpg|png)$")
_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

# Transient transport failures (connect/read timeouts, refused/reset
# connections, DNS resolution blips) are retried with exponential backoff
# before giving up -- mirrors TMDBService._get_with_retry in services/tmdb.py.
_MAX_TRANSPORT_RETRIES = 3
_RETRY_BASE_DELAY_SECONDS = 0.5

# Browser-side caching, independent of the backend's own disk retention
# (settings.image_cache_retention_days).
_BROWSER_CACHE_MAX_AGE = 604_800  # 7 days

# In-flight de-duplication so concurrent requests for the same never-cached
# image share one upstream fetch instead of each independently fetching and
# writing the same bytes -- mirrors TMDBService._request's dedup in
# services/tmdb.py, which uses the same "waiter waits on the owner's event,
# falls through to its own attempt if the owner failed" shape.
_in_flight: dict[str, asyncio.Event] = {}
_flight_lock = asyncio.Lock()


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


async def _get_with_retry(url: str) -> httpx.Response:
    """Issue one rate-limited GET, retrying transient transport failures.

    Each attempt (including retries) re-acquires the rate limiter, since a
    retry is a fresh call to the external CDN and must respect the same
    budget as the original attempt. Mirrors TMDBService._get_with_retry in
    services/tmdb.py.

    Args:
        url: Fully-qualified image URL.

    Returns:
        The successful HTTP response.

    Raises:
        httpx.HTTPStatusError: If TMDB returns a non-2xx status.
        httpx.TransportError: If every attempt fails to connect.
    """
    for attempt in range(1, _MAX_TRANSPORT_RETRIES + 1):
        try:
            async with image_rate_limiter.acquire(), httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response
        except httpx.TransportError as exc:
            if attempt == _MAX_TRANSPORT_RETRIES:
                logger.error("TMDB image fetch %s failed after %d attempts: %s", url, attempt, exc)
                raise
            delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "TMDB image fetch %s transport error (attempt %d/%d): %s; retrying in %.1fs",
                url,
                attempt,
                _MAX_TRANSPORT_RETRIES,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # loop always returns or raises


async def _fetch_from_tmdb(size: str, filename: str) -> bytes:
    """Rate-limited fetch of one image's bytes from TMDB.

    Uses its own rate limiter (services.rate_limiter.image_rate_limiter),
    separate from the one TMDBService uses for metadata calls -- image.tmdb.org
    is a CDN, not the rate-limit-sensitive api.themoviedb.org metadata API, so
    poster/backdrop fetches don't queue behind (or steal budget from) TMDB
    metadata sync traffic.

    Transient transport failures (connect/read timeouts, DNS resolution
    blips) are retried with backoff via _get_with_retry before surfacing as
    a 502 -- see _get_with_retry's docstring.

    Raises:
        HTTPException: 404 if TMDB has no such image, 502 for other
            upstream failures.
    """
    url = f"{_TMDB_IMAGE_BASE}/{size}/{filename}"
    try:
        response = await _get_with_retry(url)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 404:
            raise HTTPException(status_code=404, detail="Image not found on TMDB") from exc
        logger.warning("TMDB image fetch failed for %s: HTTP %s", url, status_code)
        raise HTTPException(status_code=502, detail="Upstream image fetch failed") from exc
    except httpx.HTTPError as exc:
        logger.warning("TMDB image fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail="Upstream image fetch failed") from exc

    logger.info(
        "TMDB image fetch %s -> %s (%.1fs)",
        url,
        response.status_code,
        response.elapsed.total_seconds(),
    )
    return response.content


async def _fetch_and_cache(backend: ImageCacheBackend, size: str, filename: str) -> bytes:
    """Fetch *size*/*filename* from TMDB, cache it via *backend*, and return the bytes.

    Only the first concurrent caller for a given key performs the real
    fetch; other callers wait for it and read the freshly cached result. If
    the owner's fetch fails, waiters fall through to fetching independently
    (bounded by the same shared rate limiter) rather than replaying its
    exception.
    """
    key = f"{size}/{filename}"
    async with _flight_lock:
        existing = _in_flight.get(key)
        if existing is not None:
            is_owner = False
            event = existing
        else:
            is_owner = True
            event = asyncio.Event()
            _in_flight[key] = event

    if not is_owner:
        await event.wait()
        cached = await backend.get(size, filename)
        if cached is not None:
            return cached
        # Owner's fetch failed -- fall through and try independently below.

    try:
        data = await _fetch_from_tmdb(size, filename)
        await backend.put(size, filename, data)
        return data
    finally:
        if is_owner:
            async with _flight_lock:
                _in_flight.pop(key, None)
            event.set()


@router.get("/{size}/{filename}")
async def get_image(size: str, filename: str) -> Response:
    """Serve a TMDB poster/backdrop image, caching it to disk on first request.

    Args:
        size: One of ``w92``, ``w185``, ``w300``, ``w500``, ``w780``, ``w1280``.
        filename: TMDB image filename (e.g. ``abc123.jpg``).

    Returns:
        Raw image bytes with a Content-Type and browser Cache-Control header.

    Raises:
        HTTPException: 400 for an unsupported size or malformed filename,
            404 if TMDB has no such image, 502 for other upstream failures,
            503 if the image cache backend failed to initialise.
    """
    _validate_size(size)
    _validate_filename(filename)

    backend = image_cache_backend
    if backend is None:
        raise HTTPException(status_code=503, detail="Image cache is not configured")

    cached = await backend.get(size, filename)
    if cached is not None:
        return Response(cached, media_type=_media_type_for(filename), headers=_cache_headers())

    data = await _fetch_and_cache(backend, size, filename)
    return Response(data, media_type=_media_type_for(filename), headers=_cache_headers())
