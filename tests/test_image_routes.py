"""Tests for the /api/images route."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2 as httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import jidou.api.routes.images as images_module
from jidou.api.dependencies import verify_api_key
from jidou.config import settings
from jidou.main import app


@asynccontextmanager
async def _noop_acquire() -> AsyncGenerator[None]:
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestValidation:
    def test_invalid_size_returns_400(self, client: TestClient) -> None:
        response = client.get("/api/images/w999/abc123.jpg")

        assert response.status_code == 400

    @pytest.mark.parametrize("size", ["w92", "w185", "w300", "w500", "w780", "w1280"])
    def test_valid_size_passes_validation(self, client: TestClient, size: str) -> None:
        with patch.object(images_module.image_cache_backend, "get", AsyncMock(return_value=b"x")):
            response = client.get(f"/api/images/{size}/abc123.jpg")

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "filename",
        [
            "abc123.txt",
            "abc 123.jpg",
            "abc123",
        ],
    )
    def test_invalid_filename_returns_400(self, client: TestClient, filename: str) -> None:
        response = client.get(f"/api/images/w300/{filename}")

        assert response.status_code == 400

    def test_encoded_traversal_never_reaches_handler(self, client: TestClient) -> None:
        """An encoded slash splits the URL into extra path segments, so
        Starlette's own router returns 404 before our filename regex ever
        runs — a stronger guarantee than application-level validation."""
        response = client.get("/api/images/w300/..%2F..%2Fetc%2Fpasswd.jpg")

        assert response.status_code == 404


class TestCacheHit:
    def test_cache_hit_serves_bytes_without_http_call(self, client: TestClient) -> None:
        with (
            patch.object(
                images_module.image_cache_backend, "get", AsyncMock(return_value=b"cached-bytes")
            ),
            patch("httpx2.AsyncClient") as mock_client_cls,
        ):
            response = client.get("/api/images/w300/abc123.jpg")

        assert response.status_code == 200
        assert response.content == b"cached-bytes"
        assert response.headers["content-type"] == "image/jpeg"
        assert "max-age" in response.headers["cache-control"]
        mock_client_cls.assert_not_called()

    def test_cache_hit_png_content_type(self, client: TestClient) -> None:
        with patch.object(
            images_module.image_cache_backend, "get", AsyncMock(return_value=b"png-bytes")
        ):
            response = client.get("/api/images/w300/abc123.png")

        assert response.headers["content-type"] == "image/png"


class TestCacheMiss:
    def _mock_http_client(
        self, *, status_code: int = 200, content: bytes = b"fetched-bytes"
    ) -> AsyncMock:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.content = content
        if status_code >= 400:
            request = httpx.Request("GET", "https://image.tmdb.org/t/p/w300/abc123.jpg")
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "error", request=request, response=httpx.Response(status_code, request=request)
            )
        else:
            mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get = AsyncMock(return_value=mock_response)
        return mock_client

    def test_cache_miss_fetches_and_stores(self, client: TestClient) -> None:
        mock_client = self._mock_http_client()
        mock_put = AsyncMock()

        with (
            patch.object(images_module.image_cache_backend, "get", AsyncMock(return_value=None)),
            patch.object(images_module.image_cache_backend, "put", mock_put),
            patch.object(images_module.image_rate_limiter, "acquire", _noop_acquire),
            patch("httpx2.AsyncClient", return_value=mock_client),
        ):
            response = client.get("/api/images/w300/abc123.jpg")

        assert response.status_code == 200
        assert response.content == b"fetched-bytes"
        mock_put.assert_called_once_with("w300", "abc123.jpg", b"fetched-bytes")

    def test_upstream_404_returns_404(self, client: TestClient) -> None:
        mock_client = self._mock_http_client(status_code=404)

        with (
            patch.object(images_module.image_cache_backend, "get", AsyncMock(return_value=None)),
            patch.object(images_module.image_rate_limiter, "acquire", _noop_acquire),
            patch("httpx2.AsyncClient", return_value=mock_client),
        ):
            response = client.get("/api/images/w300/abc123.jpg")

        assert response.status_code == 404

    def test_upstream_server_error_returns_502(self, client: TestClient) -> None:
        mock_client = self._mock_http_client(status_code=500)

        with (
            patch.object(images_module.image_cache_backend, "get", AsyncMock(return_value=None)),
            patch.object(images_module.image_rate_limiter, "acquire", _noop_acquire),
            patch("httpx2.AsyncClient", return_value=mock_client),
        ):
            response = client.get("/api/images/w300/abc123.jpg")

        assert response.status_code == 502

    def test_network_error_returns_502(self, client: TestClient) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection failed"))

        with (
            patch.object(images_module.image_cache_backend, "get", AsyncMock(return_value=None)),
            patch.object(images_module.image_rate_limiter, "acquire", _noop_acquire),
            patch("httpx2.AsyncClient", return_value=mock_client),
        ):
            response = client.get("/api/images/w300/abc123.jpg")

        assert response.status_code == 502


def test_backend_not_configured_returns_503(client: TestClient) -> None:
    """An unconfigured image cache backend (see image_cache.py's graceful-init
    fallback) surfaces as 503, not an unhandled AttributeError."""
    with patch.object(images_module, "image_cache_backend", None):
        response = client.get("/api/images/w300/abc123.jpg")

    assert response.status_code == 503


class TestInFlightDedup:
    """Unit tests against _fetch_and_cache directly -- TestClient's synchronous
    request handling can't model true concurrency, so these exercise the
    dedup mechanism at the function level instead of through HTTP.
    """

    async def _fake_backend(self) -> MagicMock:
        backend = MagicMock()
        stored: dict[str, bytes] = {}

        async def fake_get(size: str, filename: str) -> bytes | None:
            return stored.get(f"{size}/{filename}")

        async def fake_put(size: str, filename: str, data: bytes) -> None:
            stored[f"{size}/{filename}"] = data

        backend.get = AsyncMock(side_effect=fake_get)
        backend.put = AsyncMock(side_effect=fake_put)
        return backend

    async def test_concurrent_callers_share_one_upstream_fetch(self) -> None:
        backend = await self._fake_backend()
        fetch_started = asyncio.Event()
        release_fetch = asyncio.Event()
        fetch_call_count = 0

        async def fake_fetch_from_tmdb(size: str, filename: str) -> bytes:
            nonlocal fetch_call_count
            fetch_call_count += 1
            fetch_started.set()
            await release_fetch.wait()
            return b"fetched-bytes"

        with patch.object(images_module, "_fetch_from_tmdb", fake_fetch_from_tmdb):
            task1 = asyncio.create_task(images_module._fetch_and_cache(backend, "w300", "abc.jpg"))
            await fetch_started.wait()
            task2 = asyncio.create_task(images_module._fetch_and_cache(backend, "w300", "abc.jpg"))
            await asyncio.sleep(0)  # let task2 register itself as a waiter
            release_fetch.set()
            result1, result2 = await asyncio.gather(task1, task2)

        assert fetch_call_count == 1
        assert result1 == b"fetched-bytes"
        assert result2 == b"fetched-bytes"

    async def test_owner_failure_does_not_poison_later_callers(self) -> None:
        """A failed owner fetch must not leave the key permanently stuck --
        the next caller gets its own fresh attempt."""
        backend = await self._fake_backend()
        call_count = 0

        async def fake_fetch_from_tmdb(size: str, filename: str) -> bytes:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise HTTPException(status_code=502, detail="upstream error")
            return b"second-attempt-bytes"

        with patch.object(images_module, "_fetch_from_tmdb", fake_fetch_from_tmdb):
            with pytest.raises(HTTPException):
                await images_module._fetch_and_cache(backend, "w300", "abc.jpg")
            result = await images_module._fetch_and_cache(backend, "w300", "abc.jpg")

        assert result == b"second-attempt-bytes"
        assert call_count == 2


def test_images_route_ignores_a_configured_api_key(client: TestClient) -> None:
    """/api/images/... is reachable without X-API-Key even when one is configured.

    tests/conftest.py's autouse fixture overrides verify_api_key globally for
    every test, so it's temporarily removed here to exercise the real
    dependency. A control request to an authenticated route in the same
    conditions confirms the override removal actually took effect.
    """
    app.dependency_overrides.pop(verify_api_key, None)
    try:
        with (
            patch.object(settings, "jidou_api_key", "configured-secret"),
            patch.object(images_module.image_cache_backend, "get", AsyncMock(return_value=b"x")),
        ):
            images_response = client.get("/api/images/w300/abc123.jpg")
            control_response = client.get("/api/shows/trending")
    finally:
        app.dependency_overrides[verify_api_key] = lambda: None

    assert images_response.status_code == 200
    assert control_response.status_code == 401
