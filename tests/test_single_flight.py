"""Tests for :class:`jidou.services.single_flight.ElectedSingleFlight`.

Concurrency is sequenced with events and ``asyncio.sleep(0)`` yields, never wall-clock sleeps.
"""

import asyncio
from typing import Any

import pytest

from jidou.services.single_flight import ElectedSingleFlight


async def _settle() -> None:
    """Yield enough event-loop turns for started tasks to reach their wait points."""
    for _ in range(20):
        await asyncio.sleep(0)


class _Harness:
    """Shared store + gated producer so tests control exactly when the owner finishes."""

    def __init__(self, *, outcomes: list[str | Exception]) -> None:
        self.store: dict[str, str] = {}
        self.calls = 0
        self.gate = asyncio.Event()
        self.log: list[str] = []
        self._outcomes = outcomes

    async def lookup(self) -> str | None:
        self.log.append("lookup")
        return self.store.get("k")

    async def produce(self) -> str:
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        await self.gate.wait()
        if isinstance(outcome, Exception):
            raise outcome
        self.store["k"] = outcome
        return outcome

    async def cleanup(self, exc: BaseException) -> None:
        self.log.append("cleanup")

    def spawn(self, flight: ElectedSingleFlight[str], n: int, **kw: Any) -> list[asyncio.Task[str]]:
        return [
            asyncio.create_task(flight.run("k", lookup=self.lookup, produce=self.produce, **kw))
            for _ in range(n)
        ]


async def test_concurrent_callers_share_one_produce() -> None:
    h = _Harness(outcomes=["v"])
    flight: ElectedSingleFlight[str] = ElectedSingleFlight(max_rounds=None, label="T")
    tasks = h.spawn(flight, 3)
    await _settle()
    h.gate.set()
    assert await asyncio.gather(*tasks) == ["v", "v", "v"]
    assert h.calls == 1


async def test_owner_failure_elects_exactly_one_new_owner() -> None:
    h = _Harness(outcomes=[ValueError("first"), "v"])
    flight: ElectedSingleFlight[str] = ElectedSingleFlight(max_rounds=None, label="T")
    tasks = h.spawn(flight, 3)
    await _settle()
    h.gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert h.calls == 2
    assert isinstance(results[0], ValueError)
    assert results[1:] == ["v", "v"]


async def test_max_rounds_reraises_owner_error_without_new_produce() -> None:
    h = _Harness(outcomes=[ValueError("boom")])
    flight: ElectedSingleFlight[str] = ElectedSingleFlight(max_rounds=2, label="T")
    tasks = h.spawn(flight, 4)
    await _settle()
    h.gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert h.calls == 2
    assert len(results) == 4
    assert all(isinstance(r, ValueError) and str(r) == "boom" for r in results)


async def test_fail_fast_without_stored_error_raises_message() -> None:
    """A waiter past the cap with no recorded error gets the supplied RuntimeError."""
    flight: ElectedSingleFlight[str] = ElectedSingleFlight(max_rounds=0, label="T")
    owner_started = asyncio.Event()
    release = asyncio.Event()

    async def produce() -> str:
        owner_started.set()
        await release.wait()
        return "unused"

    async def lookup() -> str | None:
        return None

    owner = asyncio.create_task(
        flight.run("k", lookup=lookup, produce=produce, fail_fast_message="capped")
    )
    await owner_started.wait()
    waiter = asyncio.create_task(
        flight.run("k", lookup=lookup, produce=produce, fail_fast_message="capped")
    )
    await _settle()
    release.set()
    assert await owner == "unused"
    # Owner succeeded but published nothing, and no round is allowed past the owner's own.
    with pytest.raises(RuntimeError, match="capped"):
        await waiter


async def test_on_owner_failure_runs_before_waiters_wake() -> None:
    h = _Harness(outcomes=[ValueError("x"), "v"])
    flight: ElectedSingleFlight[str] = ElectedSingleFlight(max_rounds=None, label="T")
    tasks = h.spawn(flight, 2, on_owner_failure=h.cleanup)
    await _settle()
    h.gate.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert h.log[0] == "cleanup"
    assert "lookup" in h.log


async def test_new_batch_after_fail_fast_gets_fresh_owner() -> None:
    h = _Harness(outcomes=[ValueError("boom"), ValueError("boom"), "v"])
    flight: ElectedSingleFlight[str] = ElectedSingleFlight(max_rounds=2, label="T")
    tasks = h.spawn(flight, 3)
    await _settle()
    h.gate.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert h.calls == 2
    # Fully settled: a later call starts a fresh batch and invokes produce again.
    assert await flight.run("k", lookup=h.lookup, produce=h.produce) == "v"
    assert h.calls == 3
