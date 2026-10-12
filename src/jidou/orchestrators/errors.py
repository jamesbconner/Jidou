"""Domain errors raised by orchestrators.

Orchestrators must not import FastAPI, so they signal "the request cannot be satisfied" with
these exceptions instead of ``HTTPException``. The HTTP layer maps each class to a status code
in exactly one place (``jidou.main``); adding a new error class is a subclass here plus a
one-line entry in that table.
"""


class OrchestratorError(Exception):
    """Base class for errors an orchestrator wants reported to the caller.

    Attributes:
        detail: User-safe explanation, returned verbatim as the response ``detail``.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(OrchestratorError):
    """A referenced resource does not exist (HTTP 404)."""


class InvalidRequestError(OrchestratorError):
    """The request is well-formed but cannot be acted on as given (HTTP 422)."""


class UpstreamError(OrchestratorError):
    """An upstream dependency such as TMDB failed (HTTP 502)."""
