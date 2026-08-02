"""Tests for configuration loading."""

from jidou.config import Settings, settings


def test_settings_default_app_name() -> None:
    """Test that app name defaults to Jidou."""
    assert settings.app_name == "Jidou"


def test_settings_database_url() -> None:
    """Test that database URL contains asyncpg driver."""
    assert "asyncpg" in settings.database_url


def test_settings_redis_url() -> None:
    """Test that Redis URL defaults to localhost when no env override is present."""
    default = Settings(_env_file=None)
    assert default.redis_url == "redis://localhost:6379/0"


def test_settings_celery_urls_fallback_to_redis() -> None:
    """Test that Celery broker/backend fall back to Redis URL."""
    assert settings.celery_broker_url == settings.redis_url
    assert settings.celery_result_backend == settings.redis_url


def test_settings_creation() -> None:
    """Test that Settings can be instantiated without error."""
    new_settings = Settings()
    assert new_settings.app_name is not None


def test_settings_image_cache_defaults() -> None:
    """Image cache settings default to a disk backend with 180-day retention."""
    default = Settings(_env_file=None)
    assert default.image_cache_backend == "disk"
    assert default.image_cache_path == "/data/image-cache"
    assert default.image_cache_expiration_enabled is True
    assert default.image_cache_retention_days == 180


def test_settings_download_stale_downloading_default() -> None:
    """Stale-DOWNLOADING reclaim threshold defaults to one hour."""
    default = Settings(_env_file=None)
    assert default.download_stale_downloading_seconds == 3600
