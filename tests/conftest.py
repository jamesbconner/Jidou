"""Shared pytest fixtures for the jidou test suite."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_external_services():
    """Automatically mock external service connections for all tests.

    Prevents Redis/PostgreSQL connections during test runs.
    """
    mock_init_db = AsyncMock()
    mock_close_db = AsyncMock()
    mock_pubsub_start = AsyncMock()
    mock_pubsub_stop = AsyncMock()

    # Mock the async Redis client returned by from_url
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.aclose = AsyncMock()

    with (
        patch("jidou.database.init_db", mock_init_db),
        patch("jidou.database.close_db", mock_close_db),
        patch("jidou.services.pubsub_subscriber.pubsub_subscriber.start", mock_pubsub_start),
        patch("jidou.services.pubsub_subscriber.pubsub_subscriber.stop", mock_pubsub_stop),
        patch("redis.asyncio.from_url", return_value=mock_redis),
    ):
        yield
