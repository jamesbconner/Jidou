"""Fetch-or-404 helpers for route handlers.

These replace the hand-written ``select → scalar_one_or_none → raise 404``
blocks repeated across the route modules. They are plain coroutines rather
than FastAPI dependencies so that handler execution order (and therefore
422-vs-404 precedence) is unchanged at every call site.
"""

from fastapi import HTTPException
from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.base import Base
from jidou.models.show import Show


async def one_or_404[T](session: AsyncSession, stmt: Select[tuple[T]], *, detail: str) -> T:
    """Execute *stmt* and return its single row, or raise HTTP 404.

    Use this form when the statement needs loader options, a shared base
    statement, ordering, or a row lock that :func:`get_or_404` does not express.

    Args:
        session: Active async DB session.
        stmt: A ``select`` returning at most one row.
        detail: The exact 404 ``detail`` string the endpoint has always returned.

    Returns:
        The single row.

    Raises:
        HTTPException: 404 with *detail* when no row matches.
    """
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=detail)
    return row


async def get_or_404[ModelT: Base](
    session: AsyncSession,
    model: type[ModelT],
    *criteria: ColumnElement[bool],
    detail: str,
    for_update: bool = False,
) -> ModelT:
    """Fetch one *model* row matching all *criteria*, or raise HTTP 404.

    Args:
        session: Active async DB session.
        model: ORM class to select.
        *criteria: ``WHERE`` clauses, ANDed together.
        detail: The exact 404 ``detail`` string.
        for_update: Emit ``SELECT … FOR UPDATE`` (row lock) when True.

    Returns:
        The matching ORM instance.

    Raises:
        HTTPException: 404 with *detail* when no row matches.

    Example:
        >>> ep = await get_or_404(
        ...     db, Episode, Episode.id == eid, Episode.show_id == sid,
        ...     detail="Episode not found",
        ... )
    """
    stmt = select(model).where(*criteria)
    if for_update:
        stmt = stmt.with_for_update()
    return await one_or_404(session, stmt, detail=detail)


async def get_show_or_404(session: AsyncSession, show_id: int, *, for_update: bool = False) -> Show:
    """Fetch a :class:`Show` by primary key, or raise HTTP 404 ``"Show not found"``.

    Args:
        session: Active async DB session.
        show_id: Database primary key.
        for_update: Lock the row (``SELECT … FOR UPDATE``) when True.

    Returns:
        The show.

    Raises:
        HTTPException: 404 ``"Show not found"``.
    """
    return await get_or_404(
        session, Show, Show.id == show_id, detail="Show not found", for_update=for_update
    )
