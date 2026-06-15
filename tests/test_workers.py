"""Tests for Celery worker and background tasks."""

from unittest.mock import AsyncMock, patch

from jidou.workers.celery_app import celery_app
from jidou.workers.tasks import fetch_trending_shows_task


class TestCeleryApp:
    """Test Celery application configuration."""

    def test_celery_app_configured(self) -> None:
        """Test that Celery app is created with correct broker."""
        assert celery_app is not None
        config = celery_app.conf
        assert config.broker_url.startswith("redis://")

    def test_celery_autodiscover(self) -> None:
        """Test that tasks are auto-discovered."""
        registered = celery_app.tasks
        assert any("fetch_trending" in name for name in registered)


def test_fetch_trending_shows_task() -> None:
    """Test that the trending task calls TMDB and returns count."""
    # fetch_trending_shows_task is a sync Celery task that uses asyncio.run()
    # internally, so we patch the async helper it calls.
    with patch(
        "jidou.workers.tasks._fetch_trending",
        new_callable=AsyncMock,
        return_value=42,
    ) as mock_fetch:
        result = fetch_trending_shows_task()

        # asyncio.run() wraps the async call; verify the helper was invoked
        mock_fetch.assert_called_once()
        assert result == 42
