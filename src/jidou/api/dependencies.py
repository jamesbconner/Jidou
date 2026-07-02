"""Shared FastAPI dependencies."""

from fastapi import Header, HTTPException, status

from jidou.config import settings


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
