"""Shared event-emission helpers for orchestrators."""

import logging
from typing import Any

from jidou.services.callbacks import OnEvent

logger = logging.getLogger(__name__)


class EventSink:
    """Forwards ``(level, msg, ctx)`` events to an optional callback.

    An instance is itself an :data:`~jidou.services.callbacks.OnEvent`, so it can be
    passed straight to service helpers that take ``on_event=``.

    Args:
        callback: Destination for events, or ``None`` to drop them.
        swallow_errors: When ``True``, an exception raised by ``callback`` is logged
            and the caller continues. When ``False`` it propagates. Orchestrators
            differ on this today, so the choice is explicit rather than defaulted.
    """

    def __init__(self, callback: OnEvent | None, *, swallow_errors: bool) -> None:
        self._callback = callback
        self._swallow_errors = swallow_errors

    async def __call__(self, level: str, msg: str, ctx: dict[str, Any] | None = None) -> None:
        """Emit one event.

        Args:
            level: Event severity, such as ``"info"``, ``"warn"`` or ``"error"``.
            msg: Human-readable message.
            ctx: Optional structured context.

        Raises:
            Exception: Whatever the callback raises, when ``swallow_errors`` is ``False``.
        """
        if self._callback is None:
            return
        if not self._swallow_errors:
            await self._callback(level, msg, ctx)
            return
        try:
            await self._callback(level, msg, ctx)
        except Exception:
            # Event logging is best-effort here: a broken log sink must not abort the work.
            logger.warning("Event logging failed; continuing", exc_info=True)


async def log_only_event(level: str, msg: str, ctx: dict[str, Any] | None = None) -> None:
    """Event callback used when the caller provides none: write to the module logger.

    Args:
        level: Event severity; ``"info"`` logs at INFO, anything else at WARNING.
        msg: Human-readable message.
        ctx: Ignored structured context.
    """
    logger.log(logging.INFO if level == "info" else logging.WARNING, "%s", msg)
