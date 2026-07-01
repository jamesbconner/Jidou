"""Tests for progress service helpers — append_task_event."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_append_task_event_calls_execute_commit_and_emit() -> None:
    """append_task_event writes an event row and broadcasts via emit_progress."""
    from jidou.services.progress import append_task_event

    mock_session = AsyncMock()

    with (
        patch("jidou.services.progress.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        await append_task_event(mock_session, "task-123", "info", "Show created")

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_emit.assert_called_once()

    emitted = mock_emit.call_args[0][0]
    assert emitted["type"] == "event"
    assert emitted["celery_task_id"] == "task-123"
    assert emitted["data"]["msg"] == "Show created"
    assert emitted["data"]["level"] == "info"


@pytest.mark.asyncio
async def test_append_task_event_includes_ctx_when_provided() -> None:
    """append_task_event includes ctx field in event when passed."""
    from jidou.services.progress import append_task_event

    mock_session = AsyncMock()

    with patch("jidou.services.progress.emit_progress", new_callable=AsyncMock) as mock_emit:
        await append_task_event(
            mock_session, "task-456", "warn", "Skipped", ctx={"show": "Test Show"}
        )

    emitted = mock_emit.call_args[0][0]
    assert emitted["data"].get("ctx") == {"show": "Test Show"}
