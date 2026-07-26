"""Tests for the image cache purge Celery task."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from jidou.workers.image_cache_tasks import _purge_stale_images, purge_stale_images_task


@pytest.mark.asyncio
async def test_purge_stale_images_uses_configured_retention() -> None:
    """The cutoff passed to the backend is now() minus the configured retention."""
    mock_purge = AsyncMock(return_value=3)

    with (
        patch("jidou.workers.image_cache_tasks.image_cache_backend.purge_older_than", mock_purge),
        patch("jidou.workers.image_cache_tasks.settings.image_cache_retention_days", 90),
    ):
        before = datetime.now(UTC) - timedelta(days=90)
        result = await _purge_stale_images()
        after = datetime.now(UTC) - timedelta(days=90)

    mock_purge.assert_called_once()
    (cutoff,) = mock_purge.call_args.args
    assert before <= cutoff <= after
    assert result == {"purged": 3}


def test_purge_stale_images_task_runs_the_async_body() -> None:
    """The Celery task wrapper drives _purge_stale_images via asyncio.run."""
    with patch(
        "jidou.workers.image_cache_tasks._purge_stale_images",
        AsyncMock(return_value={"purged": 5}),
    ) as mock_purge:
        result = purge_stale_images_task()

    mock_purge.assert_called_once()
    assert result == {"purged": 5}
