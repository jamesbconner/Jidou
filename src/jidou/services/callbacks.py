"""Named callback types shared by services, orchestrators and workers.

Long-running operations report back through two async callbacks. Naming the
types once keeps every signature that accepts one identical, and lets callers
(the worker harness, the orchestrators, the services helpers) share them
without redefining the ``Callable`` shape.
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias

# ``(level, message, ctx)`` structured log event surfaced to the task event log.
# ``dict[str, Any]`` accepts both ``dict[str, object]`` and ``dict[str, Any]``
# call sites, so no caller needs to widen or narrow its context type.
OnEvent: TypeAlias = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]  # noqa: UP040

# ``(current, total, message)`` progress report. Errors raised from this
# callback must propagate: the worker harness uses it to deliver
# ``TaskCancelledError`` into the running orchestrator.
OnProgress: TypeAlias = Callable[[int, int, str], Awaitable[None]]  # noqa: UP040
