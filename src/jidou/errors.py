"""Domain errors raised by services and orchestrators.

Neither layer may import FastAPI, so they signal "the request cannot be satisfied" with
these exceptions instead of ``HTTPException``. This module sits below every layer (it imports
nothing from ``jidou``) so services and orchestrators can both raise these errors. The HTTP
layer maps each class to a status code in exactly one place (``jidou.main``); adding a new
error class is a subclass here plus a one-line entry in that table.
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


class ServiceUnavailableError(OrchestratorError):
    """A required capability is temporarily unusable, e.g. an LLM call failed (HTTP 503)."""
