"""Shared FastAPI dependencies."""

from fastapi import Header, HTTPException, Request, status

from jidou.config import settings
from jidou.services.llm_service import LLMService, create_llm_service


def get_llm_service(request: Request) -> LLMService:
    """Return the shared :class:`LLMService` instance from application state.

    The service is pre-warmed by the FastAPI lifespan so the TTLCache persists
    across requests.  Outside the full lifespan (unit tests that do not enter
    lifespan) the service is lazily initialised and stored on ``app.state`` for
    the remainder of that process.

    Args:
        request: Current FastAPI request (injected by the dependency system).

    Returns:
        The shared :class:`LLMService` instance.
    """
    svc: LLMService | None = getattr(request.app.state, "llm_service", None)
    if svc is None:
        svc = create_llm_service(settings)
        request.app.state.llm_service = svc
    return svc


async def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Validate the ``X-API-Key`` request header against ``JIDOU_API_KEY``.

    When ``JIDOU_API_KEY`` is not configured the check is skipped entirely,
    preserving backward-compatible behaviour for local development.

    Args:
        x_api_key: Value of the ``X-API-Key`` header, or ``None`` if absent.

    Raises:
        HTTPException: 401 when a key is configured and the header is missing
            or does not match.
    """
    expected = settings.jidou_api_key
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
