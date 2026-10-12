"""Unit tests for jidou.services.health_probes."""

import asyncio
import dataclasses
from unittest.mock import AsyncMock, patch

import pytest

from jidou.services.health_probes import ProbeFailedError, ProbeResult, ping_redis, run_probe


def test_run_probe_success_includes_details_and_latency() -> None:
    async def check() -> dict[str, object]:
        return {"workers": ["w1"]}

    result = asyncio.run(run_probe(check))
    assert result.ok is True
    assert result.latency_ms >= 0
    assert result.as_dict() == {"ok": True, "latency_ms": result.latency_ms, "workers": ["w1"]}


def test_run_probe_none_details_is_empty() -> None:
    async def check() -> None:
        return None

    assert asyncio.run(run_probe(check)).as_dict().keys() == {"ok", "latency_ms"}


def test_run_probe_exception_becomes_error_result() -> None:
    async def check() -> None:
        raise RuntimeError("db down")

    result = asyncio.run(run_probe(check))
    assert result.as_dict() == {"ok": False, "latency_ms": result.latency_ms, "error": "db down"}


def test_probe_failed_error_message_is_reported() -> None:
    async def check() -> None:
        raise ProbeFailedError("No Celery workers responded to ping")

    assert asyncio.run(run_probe(check)).error == "No Celery workers responded to ping"


def test_run_probe_reports_timeout_errors() -> None:
    async def check() -> None:
        raise TimeoutError("timed out")

    result = asyncio.run(run_probe(check))
    assert result.ok is False
    assert result.error == "timed out"


def test_ping_redis_pings_and_always_closes() -> None:
    client = AsyncMock()
    client.ping = AsyncMock(side_effect=ConnectionError("refused"))
    with patch("redis.asyncio.from_url", return_value=client):
        result = asyncio.run(run_probe(lambda: ping_redis("redis://x")))
    assert result.ok is False
    assert result.error == "refused"
    client.aclose.assert_awaited_once()


def test_ping_redis_success_closes_client() -> None:
    client = AsyncMock()
    with patch("redis.asyncio.from_url", return_value=client) as from_url:
        asyncio.run(ping_redis("redis://x", decode_responses=True))
    from_url.assert_called_once_with("redis://x", decode_responses=True)
    client.ping.assert_awaited_once()
    client.aclose.assert_awaited_once()


def test_probe_result_is_frozen() -> None:
    r = ProbeResult(ok=True, latency_ms=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.ok = False  # type: ignore[misc]
