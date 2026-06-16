"""Shared pytest fixtures for the jidou test suite."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.main import app


@pytest.fixture
def client():
    """Create a test client that skips external service connections.

    Patches init_db, pubsub_subscriber.start/stop, and close_db so tests
    run without requiring Redis or PostgreSQL.
    """
    mock_init_db = AsyncMock()
    mock_close_db = AsyncMock()
    mock_pubsub_start = AsyncMock()
    mock_pubsub_stop = AsyncMock()

    with (
        patch("jidou.database.init_db", mock_init_db),
        patch("jidou.database.close_db", mock_close_db),
        patch("jidou.services.pubsub_subscriber.pubsub_subscriber.start", mock_pubsub_start),
        patch("jidou.services.pubsub_subscriber.pubsub_subscriber.stop", mock_pubsub_stop),
        TestClient(app) as test_client,
    ):
        yield test_client
