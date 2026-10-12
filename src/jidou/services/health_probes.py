"""Timed, exception-safe dependency probes shared by the health endpoints."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from jidou.services.redis_conn import redis_session


class ProbeFailedError(Exception):
    """Raised by a probe check to report failure with a specific message."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of one dependency probe.

    Attributes:
        ok: Whether the dependency is usable.
        latency_ms: Wall time of the check, rounded to 0.1 ms.
        error: Failure message when ``ok`` is False.
        details: Extra fields merged into the serialized result on success.
    """

    ok: bool
    latency_ms: float
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialize as ``{"ok", "latency_ms", **details, ["error"]}``.

        Returns:
            JSON-ready dictionary.
        """
        out: dict[str, Any] = {"ok": self.ok, "latency_ms": self.latency_ms, **self.details}
        if self.error is not None:
            out["error"] = self.error
        return out


def _elapsed_ms(t0: float) -> float:
    """Return milliseconds since *t0* (a ``time.monotonic()`` value), 0.1 ms resolution."""
    return round((time.monotonic() - t0) * 1000, 1)


async def run_probe(check: Callable[[], Awaitable[dict[str, Any] | None]]) -> ProbeResult:
    """Run *check*, timing it and converting any exception into a failed result.

    A health probe must report, never raise: every exception is captured as
    ``ProbeResult(ok=False, error=str(exc))``.

    Args:
        check: Zero-arg coroutine factory; may return extra detail fields.

    Returns:
        The probe result.
    """
    t0 = time.monotonic()
    try:
        details = await check()
    except Exception as exc:
        return ProbeResult(ok=False, latency_ms=_elapsed_ms(t0), error=str(exc))
    return ProbeResult(ok=True, latency_ms=_elapsed_ms(t0), details=details or {})


async def ping_redis(url: str, *, decode_responses: bool = False) -> None:
    """PING the Redis server at *url*, always closing the client.

    Args:
        url: Redis connection URL.
        decode_responses: Passed through to the client; each health endpoint keeps
            the connection mode it has always used.

    Raises:
        Exception: Whatever the client raises on connect or ping.
    """
    async with redis_session(url, decode_responses=decode_responses) as client:
        await client.ping()
