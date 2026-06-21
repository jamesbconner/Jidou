"""Tests for Celery worker and background tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

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


def test_download_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in download_files_task must call mark_task_timed_out."""
    from jidou.workers.download_tasks import download_files_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.download_tasks._download_files",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.download_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        # Celery bind=True tasks auto-inject self; do not pass mock as first arg.
        download_files_task(dry_run=False)

    assert len(mark_calls) == 1, "mark_task_timed_out must be called exactly once"


@pytest.mark.asyncio
async def test_download_files_skips_redelivery_for_terminal_task() -> None:
    """_download_files must exit early without re-running when the task row is terminal."""
    from jidou.models.task import BackgroundTask, TaskStatus
    from jidou.workers.download_tasks import _download_files

    terminal_task = MagicMock(spec=BackgroundTask)
    terminal_task.status = TaskStatus.COMPLETED.value
    terminal_task.celery_task_id = "redelivered-123"

    mock_engine = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = False
    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine),
        patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.download_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal_task,
        ),
        patch(
            "jidou.workers.download_tasks.update_task_status",
            new_callable=AsyncMock,
        ) as mock_update,
    ):
        result = await _download_files("redelivered-123", dry_run=False)

    mock_update.assert_not_called()
    assert result == "redelivered-123"


def test_scan_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in scan_remote_task must call mark_task_timed_out."""
    from jidou.workers.scan_tasks import scan_remote_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.scan_tasks._scan_remote",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.scan_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        scan_remote_task(dry_run=False)

    assert len(mark_calls) == 1, "mark_task_timed_out must be called exactly once"
