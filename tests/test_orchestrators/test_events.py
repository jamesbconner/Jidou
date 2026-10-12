"""Tests for ``EventSink`` and ``log_only_event``."""

import logging
from unittest.mock import AsyncMock

import pytest

from jidou.orchestrators._events import EventSink, log_only_event


async def test_sink_without_callback_is_noop() -> None:
    """A sink with no callback accepts events and does nothing, in either mode."""
    await EventSink(None, swallow_errors=True)("info", "hello")
    await EventSink(None, swallow_errors=False)("info", "hello", {"k": 1})


async def test_sink_forwards_arguments() -> None:
    """The callback receives level, message and ctx exactly as emitted."""
    callback = AsyncMock()
    sink = EventSink(callback, swallow_errors=False)

    await sink("warn", "msg", {"k": "v"})
    await sink("info", "no ctx")

    assert [c.args for c in callback.await_args_list] == [
        ("warn", "msg", {"k": "v"}),
        ("info", "no ctx", None),
    ]


async def test_sink_swallow_true_logs_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    """With swallow_errors=True a raising callback is logged, not propagated."""
    callback = AsyncMock(side_effect=RuntimeError("log down"))

    with caplog.at_level(logging.WARNING):
        await EventSink(callback, swallow_errors=True)("info", "msg")

    assert callback.await_count == 1
    assert "Event logging failed; continuing" in caplog.text


async def test_sink_swallow_false_propagates() -> None:
    """With swallow_errors=False the callback's exception reaches the caller."""
    callback = AsyncMock(side_effect=RuntimeError("log down"))

    with pytest.raises(RuntimeError, match="log down"):
        await EventSink(callback, swallow_errors=False)("info", "msg")


@pytest.mark.parametrize(
    ("level", "expected"), [("info", logging.INFO), ("error", logging.WARNING)]
)
async def test_log_only_event_maps_level(
    level: str, expected: int, caplog: pytest.LogCaptureFixture
) -> None:
    """Info events log at INFO; every other level logs at WARNING."""
    with caplog.at_level(logging.DEBUG):
        await log_only_event(level, "hello", None)

    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [(expected, "hello")]
