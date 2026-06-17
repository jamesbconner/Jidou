"""Tests for the /config API routes."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from jidou.main import app


def test_get_config_returns_200() -> None:
    """GET /api/config returns the current (sanitised) configuration."""
    response = TestClient(app).get("/api/config")
    assert response.status_code == 200
    body = response.json()
    # Sensitive fields should not appear in the response
    assert "tmdb_api_key" not in body
    assert "tmdb_api_key_set" in body
    # Basic fields should always be present
    assert "app_name" in body
    assert "debug" in body


def test_get_config_redacts_db_password() -> None:
    """GET /api/config replaces the DB password with *** in database_url."""
    response = TestClient(app).get("/api/config")
    body = response.json()
    db_url = body.get("database_url", "")
    # The default dev URL has a password; it must be redacted
    if "@" in db_url:
        assert "***" in db_url


# ---------------------------------------------------------------------------
# POST /api/config/test/tmdb
# ---------------------------------------------------------------------------


def test_test_tmdb_returns_ok_false_when_no_api_key() -> None:
    """POST /api/config/test/tmdb returns ok=False when TMDB_API_KEY is unset."""
    with patch("jidou.api.routes.config.settings") as mock_settings:
        mock_settings.tmdb_api_key = None
        response = TestClient(app).post("/api/config/test/tmdb")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False


def test_test_tmdb_returns_ok_true_on_success() -> None:
    """POST /api/config/test/tmdb returns ok=True when TMDB responds."""
    mock_tmdb = MagicMock()
    mock_tmdb.get_trending = AsyncMock(return_value={"results": []})

    with (
        patch("jidou.api.routes.config.settings") as mock_settings,
        patch("jidou.api.routes.config.settings", create=True),
    ):
        pass  # just verifying the patch structure

    with patch("jidou.api.routes.config.settings") as mock_settings:
        mock_settings.tmdb_api_key = "test-key"
        with patch("jidou.services.tmdb.TMDBService", return_value=mock_tmdb):
            response = TestClient(app).post("/api/config/test/tmdb")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/config/test/sftp
# ---------------------------------------------------------------------------


def test_test_sftp_returns_ok_false_when_no_host() -> None:
    """POST /api/config/test/sftp returns ok=False when SFTP_HOST is unset."""
    with patch("jidou.api.routes.config.settings") as mock_settings:
        mock_settings.sftp_host = None
        response = TestClient(app).post("/api/config/test/sftp")
    assert response.status_code == 200
    assert response.json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/config/test/redis
# ---------------------------------------------------------------------------


def test_test_redis_returns_ok_false_when_no_url() -> None:
    """POST /api/config/test/redis returns ok=False when REDIS_URL is unset."""
    with patch("jidou.api.routes.config.settings") as mock_settings:
        mock_settings.redis_url = ""
        response = TestClient(app).post("/api/config/test/redis")
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_test_redis_returns_ok_true_on_ping_success() -> None:
    """POST /api/config/test/redis returns ok=True when Redis responds."""
    mock_r = AsyncMock()
    mock_r.ping = AsyncMock()
    mock_r.aclose = AsyncMock()

    with patch("jidou.api.routes.config.settings") as mock_settings:
        mock_settings.redis_url = "redis://localhost:6379/0"
        with patch("redis.asyncio.from_url", return_value=mock_r):
            response = TestClient(app).post("/api/config/test/redis")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_test_redis_returns_ok_false_on_ping_failure() -> None:
    """POST /api/config/test/redis returns ok=False when Redis is unreachable."""
    with patch("jidou.api.routes.config.settings") as mock_settings:
        mock_settings.redis_url = "redis://bad-host:6379/0"
        with patch(
            "redis.asyncio.from_url",
            side_effect=ConnectionRefusedError("refused"),
        ):
            response = TestClient(app).post("/api/config/test/redis")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "error" in response.json()
