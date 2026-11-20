"""Tests for jidou.services.connection_errors."""

import errno
import socket

import pytest

from jidou.services.connection_errors import describe_connection_error


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _HTTPStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__("http://secret-host/path?api_key=abc")
        self.response = _Resp(status_code)


class _AuthenticationError(Exception):
    pass


class PermissionDenied(Exception):  # noqa: N818 - mirrors asyncssh's name
    pass


class _ReadTimeoutError(Exception):
    pass


class _ConnectError(Exception):
    pass


@pytest.mark.parametrize(
    ("exc", "expected_fragment"),
    [
        (_HTTPStatusError(401), "Authentication failed"),
        (_HTTPStatusError(403), "Authentication failed"),
        (_HTTPStatusError(429), "rate limiting"),
        (_HTTPStatusError(503), "server error"),
        (_AuthenticationError("bad key"), "Authentication failed"),
        (PermissionDenied("nope"), "Authentication failed"),
        (TimeoutError("slow"), "timed out"),
        (_ReadTimeoutError("slow"), "timed out"),
        (ConnectionRefusedError("refused"), "Could not connect"),
        (socket.gaierror("no such host"), "Could not connect"),
        (_ConnectError("boom"), "Could not connect"),
        (OSError(errno.EHOSTUNREACH, "no route"), "Could not connect"),
        (FileNotFoundError("/srv/keys/id_rsa"), "see server logs"),
        (PermissionError("/srv/keys/id_rsa"), "see server logs"),
        (OSError("plain"), "see server logs"),
        (RuntimeError("weird"), "see server logs"),
        (_HTTPStatusError(404), "see server logs"),
    ],
)
def test_describe_connection_error_categories(exc: BaseException, expected_fragment: str) -> None:
    """Each exception maps to its category message."""
    assert expected_fragment in describe_connection_error(exc)


def test_describe_connection_error_never_includes_exception_text() -> None:
    """The raw exception message is never part of the result."""
    exc = ConnectionRefusedError("secret-host.internal:6379 /srv/private/path")
    assert "secret-host" not in describe_connection_error(exc)
    assert "/srv/private" not in describe_connection_error(exc)
