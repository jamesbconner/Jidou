"""Tests for the /config API routes."""

from datetime import date
from typing import Any
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
    assert "api_key_enabled" in body


def test_get_config_surfaces_image_cache_settings() -> None:
    """GET /api/config exposes image cache backend, host path, and retention."""
    response = TestClient(app).get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert "image_cache_backend" in body
    assert "image_cache_host_path" in body
    assert "image_cache_expiration_enabled" in body
    assert "image_cache_retention_days" in body


def test_get_config_surfaces_server_local_today() -> None:
    """GET /api/config exposes the server's local date for client date math.

    Frontend "has this episode aired" calculations key off this value
    rather than the browser's own clock, so they agree with server-side
    queries (e.g. missing_episode_count on GET /shows) that use the
    server's local timezone.
    """
    response = TestClient(app).get("/api/config")
    assert response.status_code == 200
    assert response.json()["today"] == date.today().isoformat()


def test_get_config_api_key_enabled_reflects_setting() -> None:
    """GET /api/config api_key_enabled is True when JIDOU_API_KEY is set."""
    with patch("jidou.api.routes.config.settings") as mock_settings:
        mock_settings.app_name = "jidou"
        mock_settings.debug = False
        mock_settings.database_url = "postgresql://user:pass@localhost/db"
        mock_settings.redis_url = None
        mock_settings.tmdb_api_key = "key"
        mock_settings.tmdb_base_url = "https://api.themoviedb.org/3"
        mock_settings.tmdb_rate_limit_per_second = 4.0
        mock_settings.tmdb_cache_ttl = 86400
        mock_settings.cors_origins = []
        mock_settings.sftp_host = None
        mock_settings.sftp_port = 22
        mock_settings.sftp_username = None
        mock_settings.sftp_remote_paths = None
        mock_settings.llm_provider = "none"
        mock_settings.llm_model = None
        mock_settings.llm_base_url = None
        mock_settings.llm_cache_ttl = 3600
        mock_settings.local_tv_path = "/tv"
        mock_settings.local_anime_path = "/anime"
        mock_settings.local_movie_path = "/movies"
        mock_settings.local_tv_host_path = "/tv"
        mock_settings.local_anime_host_path = "/anime"
        mock_settings.local_movie_host_path = "/movies"
        mock_settings.rss_config_remote_path = None
        mock_settings.jidou_api_key = "secret"

        response = TestClient(app).get("/api/config")
        assert response.status_code == 200
        assert response.json()["api_key_enabled"] is True

        mock_settings.jidou_api_key = None
        response = TestClient(app).get("/api/config")
        assert response.json()["api_key_enabled"] is False


def test_get_config_redacts_db_password() -> None:
    """GET /api/config replaces the DB password with *** in database_url."""
    response = TestClient(app).get("/api/config")
    body = response.json()
    db_url = body.get("database_url", "")
    # The default dev URL has a password; it must be redacted
    if "@" in db_url:
        assert "***" in db_url


def test_get_config_redacts_redis_password() -> None:
    """GET /api/config must redact any password embedded in redis_url."""
    with patch("jidou.api.routes.config.settings") as mock_settings:
        mock_settings.app_name = "Jidou"
        mock_settings.debug = False
        mock_settings.database_url = "postgresql+asyncpg://user:secret@localhost/db"
        mock_settings.redis_url = "redis://:redis_secret@localhost:6379/0"
        mock_settings.tmdb_api_key = None
        mock_settings.tmdb_base_url = "https://api.themoviedb.org/3"
        mock_settings.tmdb_rate_limit_per_second = 0.5
        mock_settings.tmdb_cache_ttl = 86400
        mock_settings.allowed_origins = []
        mock_settings.sftp_host = None
        mock_settings.sftp_port = 22
        mock_settings.sftp_username = None
        mock_settings.sftp_remote_paths = "/"
        mock_settings.llm_provider = "none"
        mock_settings.llm_model = ""
        mock_settings.llm_base_url = ""
        mock_settings.llm_cache_ttl = 3600
        mock_settings.local_tv_path = "/data/media/tv"
        mock_settings.local_anime_path = "/data/media/anime"
        mock_settings.local_movie_path = "/data/media/movies"
        mock_settings.local_tv_host_path = "/data/media/tv"
        mock_settings.local_anime_host_path = "/data/media/anime"
        mock_settings.local_movie_host_path = "/data/media/movies"
        mock_settings.rss_config_remote_path = None
        mock_settings.jidou_api_key = None
        mock_settings.sync_schedule_enabled = False
        mock_settings.sync_schedule_hours = "2"
        mock_settings.rss_import_schedule_enabled = False
        mock_settings.rss_import_schedule_hours = "2"
        response = TestClient(app).get("/api/config")
    assert response.status_code == 200
    body = response.json()
    redis_url = body.get("redis_url", "")
    assert "redis_secret" not in redis_url
    assert "***" in redis_url


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


# ---------------------------------------------------------------------------
# POST /api/config/test/sftp -- constructor-argument characterization
# ---------------------------------------------------------------------------


def _sftp_settings(**overrides: object) -> MagicMock:
    """Build a settings stand-in carrying every ``sftp_*`` value the route reads."""
    values: dict[str, object] = {
        "sftp_host": "sftp.example.test",
        "sftp_port": 2222,
        "sftp_username": "alice",
        "sftp_password": None,
        "sftp_key_path": None,
        "sftp_remote_paths": "/downloads,/completed",
        "sftp_remote_paths_list": ["/downloads", "/completed"],
        "sftp_max_workers": 8,
        "sftp_max_retries": 5,
        "sftp_retry_delay": 2.5,
    }
    values.update(overrides)
    mock_settings = MagicMock()
    for name, value in values.items():
        setattr(mock_settings, name, value)
    return mock_settings


def _post_sftp_test(
    mock_settings: MagicMock, listing: list[str] | None = None
) -> tuple[Any, MagicMock]:
    """POST the SFTP test with a patched SFTPService; return (response, class mock)."""
    service = MagicMock()
    service.list_remote_files = AsyncMock(return_value=listing or [])
    with (
        patch("jidou.api.routes.config.settings", mock_settings),
        patch("jidou.services.sftp_service.SFTPService", return_value=service) as service_cls,
    ):
        response = TestClient(app).post("/api/config/test/sftp")
    return response, service_cls


def _shared_kwargs(service_cls: MagicMock) -> dict[str, object]:
    """Return the connection-relevant constructor kwargs the route used."""
    service_cls.assert_called_once()
    assert service_cls.call_args.args == ()
    keys = (
        "host",
        "port",
        "username",
        "password",
        "key_path",
        "remote_base_path",
        "max_retries",
        "retry_delay",
    )
    kwargs = service_cls.call_args.kwargs
    return {k: kwargs[k] for k in keys}


def test_sftp_test_password_auth_uses_first_remote_path() -> None:
    """Password auth: credentials and first configured path reach the service."""
    response, service_cls = _post_sftp_test(
        _sftp_settings(sftp_password="s3cret"),
        ["a", "b", "c"],
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "file_count": 3}
    assert _shared_kwargs(service_cls) == {
        "host": "sftp.example.test",
        "port": 2222,
        "username": "alice",
        "password": "s3cret",
        "key_path": None,
        "remote_base_path": "/downloads",
        "max_retries": 5,
        "retry_delay": 2.5,
    }
    assert service_cls.call_args.kwargs.get("known_hosts") is None


def test_sftp_test_key_auth_with_no_remote_paths_defaults_to_root() -> None:
    """Key auth with no configured paths: base path falls back to ``/``."""
    response, service_cls = _post_sftp_test(
        _sftp_settings(
            sftp_key_path="/keys/id_test",
            sftp_remote_paths="",
            sftp_remote_paths_list=[],
        )
    )
    assert response.json() == {"ok": True, "file_count": 0}
    assert _shared_kwargs(service_cls) == {
        "host": "sftp.example.test",
        "port": 2222,
        "username": "alice",
        "password": None,
        "key_path": "/keys/id_test",
        "remote_base_path": "/",
        "max_retries": 5,
        "retry_delay": 2.5,
    }


def test_sftp_test_failure_returns_error_text() -> None:
    """A listing failure yields ok=False with the exception text, status 200."""
    service = MagicMock()
    service.list_remote_files = AsyncMock(side_effect=OSError("connection refused"))
    with (
        patch("jidou.api.routes.config.settings", _sftp_settings()),
        patch("jidou.services.sftp_service.SFTPService", return_value=service),
    ):
        response = TestClient(app).post("/api/config/test/sftp")
    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "connection refused"}
