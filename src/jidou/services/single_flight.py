"""Elected single-flight: deduplicate concurrent identical work with owner re-election."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class ElectedSingleFlight[T]:
    """Collapse concurrent calls for one key into a single producer.

    The first caller for a key becomes the *owner* and runs ``produce``. Every other
    caller waits for the owner, then reads the result back through ``lookup`` (usually a
    cache read). If the owner left nothing behind (it failed, or produced something
    uncacheable), exactly one waiter is elected as the next owner so the remaining waiters
    don't all fire independent calls.

    Args:
        max_rounds: Maximum number of owners elected per batch before waiters fail fast
            with the last owner's error. ``None`` means unlimited.
        label: Short name used in log messages (e.g. ``"TMDB"``).
    """

    def __init__(self, *, max_rounds: int | None, label: str) -> None:
        self._max_rounds = max_rounds
        self._label = label
        self._in_flight: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        # How many owners have been elected for a key (reset to 1 whenever a brand-new batch
        # starts), and the latest owner's exception, so waiters that hit the cap can fail
        # fast with the real error instead of taking another serial turn.
        self._rounds: dict[str, int] = {}
        self._errors: dict[str, BaseException] = {}

    async def run(
        self,
        key: str,
        *,
        lookup: Callable[[], Awaitable[T | None]],
        produce: Callable[[], Awaitable[T]],
        on_owner_failure: Callable[[BaseException], Awaitable[None]] | None = None,
        fail_fast_message: str = "in-flight dedup fail-fast",
    ) -> T:
        """Run ``produce`` once per concurrent batch of callers for ``key``.

        Args:
            key: Identity of the work being deduplicated.
            lookup: Returns the shared result if the owner published one, else ``None``.
            produce: Does the real work; only ever run by the current owner.
            on_owner_failure: Awaited with the owner's exception before waiters wake.
            fail_fast_message: ``RuntimeError`` text when the round cap is hit and no
                owner error was recorded.

        Returns:
            The owner's ``produce`` result, or the value a waiter found via ``lookup``.

        Raises:
            Exception: The owner's own exception from ``produce``; or, for a waiter past
                ``max_rounds``, the last owner's stored exception.
            RuntimeError: ``fail_fast_message`` when the cap is hit with no stored error.
        """
        async with self._lock:
            existing = self._in_flight.get(key)
            if existing is None:
                event = asyncio.Event()
                self._in_flight[key] = event
                self._rounds[key] = 1
                is_owner = True
            else:
                event = existing
                is_owner = False

        if not is_owner:
            logger.debug(
                "%s in-flight dedup: waiting for concurrent call (key=%s)", self._label, key
            )
            found, elected = await self._wait_for_turn(key, event, lookup, fail_fast_message)
            if elected is None:
                # ``found`` is non-None whenever no new owner was elected.
                return found  # type: ignore[return-value]
            event = elected
            logger.warning(
                "%s in-flight dedup: owner failed; this coroutine retrying "
                "(election round %d/%s) key=%s",
                self._label,
                self._rounds[key],
                self._max_rounds,
                key,
            )

        try:
            result = await produce()
            self._rounds.pop(key, None)
            self._errors.pop(key, None)
            return result
        except Exception as exc:
            self._errors[key] = exc
            if on_owner_failure is not None:
                await on_owner_failure(exc)
            raise
        finally:
            async with self._lock:
                self._in_flight.pop(key, None)
            event.set()

    async def _wait_for_turn(
        self,
        key: str,
        event: asyncio.Event,
        lookup: Callable[[], Awaitable[T | None]],
        fail_fast_message: str,
    ) -> tuple[T | None, asyncio.Event | None]:
        """Wait on owners until a result appears or this caller is elected the next owner.

        Args:
            key: Identity of the work being deduplicated.
            event: The current owner's completion event.
            lookup: Returns the shared result if one was published, else ``None``.
            fail_fast_message: ``RuntimeError`` text when no owner error was recorded.

        Returns:
            ``(value, None)`` when ``lookup`` found a result, or ``(None, new_event)`` when
            this caller was elected owner and must run ``produce``.

        Raises:
            BaseException: The stored owner error once ``max_rounds`` is exceeded.
            RuntimeError: ``fail_fast_message`` if the cap is hit with no stored error.
        """
        while True:
            await event.wait()
            value = await lookup()
            if value is not None:
                return value, None
            # The owner left nothing behind: elect exactly one waiter as the new owner.
            async with self._lock:
                current = self._in_flight.get(key)
                if current is not None:
                    # Another waiter won the election; wait on their attempt.
                    event = current
                    continue
                round_number = self._rounds.get(key, 0) + 1
                if self._max_rounds is not None and round_number > self._max_rounds:
                    # Deliberately not popped: every sibling waiter must see the same
                    # capped round count and error so they all fail fast too, instead of
                    # the first clearing state and the next re-electing itself as fresh.
                    logger.warning(
                        "%s in-flight dedup: key=%s failed %d time(s) in a row; "
                        "failing fast instead of electing another retry owner",
                        self._label,
                        key,
                        self._max_rounds,
                    )
                    error = self._errors.get(key)
                    if error is not None:
                        raise error
                    raise RuntimeError(fail_fast_message)
                self._rounds[key] = round_number
                new_event = asyncio.Event()
                self._in_flight[key] = new_event
                return None, new_event
