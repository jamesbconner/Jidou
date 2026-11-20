"""Map connection-test exceptions to short, safe, user-facing messages.

The "Test connection" endpoints used to return ``str(exc)`` to the caller, which
can leak hostnames, file paths and driver internals (CWE-209).  This module
classifies an exception into a fixed category message instead.  Classification
is duck-typed (exception class names and a ``status_code`` attribute) so it
works across TMDB/httpx, asyncssh, redis and any LLM provider SDK without
importing them.
"""

from __future__ import annotations

import errno
import socket

_AUTH_NAME_HINTS = ("auth", "permissiondenied", "unauthorized", "forbidden")
_TIMEOUT_NAME_HINTS = ("timeout", "timedout")
_CONNECT_NAME_HINTS = ("connect", "disconnect", "unreachable", "dns", "gaierror")

# OSErrors that represent a network-level failure.  Other OSErrors (missing or
# unreadable key file, permissions) are local problems, not host/port problems,
# so they fall through to the generic message that points at the server logs.
_NETWORK_ERRNOS = frozenset({errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN})


def _is_network_error(exc: BaseException) -> bool:
    """Return True if *exc* is a network-level (not local filesystem) failure."""
    if isinstance(exc, ConnectionError | socket.gaierror | socket.herror):
        return True
    return isinstance(exc, OSError) and exc.errno in _NETWORK_ERRNOS


_MSG_AUTH = "Authentication failed (check the configured credentials)"
_MSG_RATE_LIMIT = "The service is rate limiting requests; try again shortly"
_MSG_TIMEOUT = "The connection timed out"
_MSG_CONNECT = "Could not connect to the service (check the host, port and network)"
_MSG_SERVER = "The service returned a server error"
_MSG_UNKNOWN = "Connection test failed (see server logs for details)"


def _status_code(exc: BaseException) -> int | None:
    """Return an HTTP status code carried by *exc* or its response, if any."""
    for holder in (exc, getattr(exc, "response", None)):
        code = getattr(holder, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _class_names(exc: BaseException) -> list[str]:
    """Return lower-cased class names across *exc*'s MRO (excluding ``object``)."""
    return [cls.__name__.lower() for cls in type(exc).__mro__ if cls is not object]


def describe_connection_error(exc: BaseException) -> str:
    """Return a safe, generic description of why a connection test failed.

    The returned text never includes the exception message, so it cannot leak
    internal detail.  Log the exception separately for diagnostics.

    Args:
        exc: The exception raised by the connection test.

    Returns:
        One of a small fixed set of messages.

    Examples:
        >>> describe_connection_error(TimeoutError("db at 10.0.0.5"))
        'The connection timed out'
    """
    status = _status_code(exc)
    if status in (401, 403):
        return _MSG_AUTH
    if status == 429:
        return _MSG_RATE_LIMIT
    if status is not None and status >= 500:
        return _MSG_SERVER

    names = _class_names(exc)
    if any(hint in name for name in names for hint in _AUTH_NAME_HINTS):
        return _MSG_AUTH
    if isinstance(exc, TimeoutError) or any(
        hint in name for name in names for hint in _TIMEOUT_NAME_HINTS
    ):
        return _MSG_TIMEOUT
    if _is_network_error(exc) or any(
        hint in name for name in names for hint in _CONNECT_NAME_HINTS
    ):
        return _MSG_CONNECT
    return _MSG_UNKNOWN
