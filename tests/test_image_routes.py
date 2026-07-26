"""Tests for the /api/images route."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2 as httpx
import pytest
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
            patch.object(images_module._image_rate_limiter, "acquire", _noop_acquire),
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
            patch.object(images_module._image_rate_limiter, "acquire", _noop_acquire),
            patch("httpx2.AsyncClient", return_value=mock_client),
        ):
            response = client.get("/api/images/w300/abc123.jpg")

        assert response.status_code == 404

    def test_upstream_server_error_returns_502(self, client: TestClient) -> None:
        mock_client = self._mock_http_client(status_code=500)

        with (
            patch.object(images_module.image_cache_backend, "get", AsyncMock(return_value=None)),
            patch.object(images_module._image_rate_limiter, "acquire", _noop_acquire),
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
            patch.object(images_module._image_rate_limiter, "acquire", _noop_acquire),
            patch("httpx2.AsyncClient", return_value=mock_client),
        ):
            response = client.get("/api/images/w300/abc123.jpg")

        assert response.status_code == 502


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
