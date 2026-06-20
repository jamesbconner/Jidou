"""API routes for watchlist management."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.show import Show
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus
from jidou.schemas.watchlist_schema import (
    WatchlistCreate,
    WatchlistList,
    WatchlistRead,
    WatchlistUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistList])
async def list_watchlist(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[WatchlistEntry]:
    """List all watchlist entries, ordered by position then creation time.

    Args:
        status: Optional filter by watchlist status.
        limit: Maximum results to return (default 50).
        offset: Number of results to skip for pagination.
        db_session: DB session (injected).

    Returns:
        List of watchlist entries.

    Raises:
        HTTPException: 400 if status is not a valid WatchlistStatus.
    """
    stmt = select(WatchlistEntry)

    if status is not None:
        try:
            WatchlistStatus(status)
        except ValueError:
            valid = [s.value for s in WatchlistStatus]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status {status!r}. Must be one of: {valid}",
            ) from None
        stmt = stmt.where(WatchlistEntry.status == status)

    stmt = stmt.order_by(WatchlistEntry.position.asc(), WatchlistEntry.created_at.asc())
    stmt = stmt.offset(offset).limit(limit)
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=WatchlistRead, status_code=201)
async def create_watchlist_entry(
    payload: WatchlistCreate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WatchlistEntry:
    """Add a show to the watchlist.

    If the show is already on the watchlist, the status is updated to the
    requested value and the entry is returned (idempotent — no duplicates).

    Args:
        payload: Show and initial status to track.
        db_session: DB session (injected).

    Returns:
        The created or existing WatchlistEntry record.

    Raises:
        HTTPException: 404 if the show does not exist.
    """
    show_stmt = select(Show).where(Show.id == payload.show_id)
    if (await db_session.execute(show_stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Show not found")

    existing_stmt = select(WatchlistEntry).where(WatchlistEntry.show_id == payload.show_id)
    existing = (await db_session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        if "status" in payload.model_fields_set and existing.status != payload.status:
            existing.status = WatchlistStatus(payload.status)
            await db_session.flush()
            logger.debug(
                "Show id=%d already on watchlist (entry id=%d); updated status to %s",
                payload.show_id,
                existing.id,
                payload.status,
            )
        else:
            logger.debug(
                "Show id=%d already on watchlist (entry id=%d)", payload.show_id, existing.id
            )
        return existing

    entry = WatchlistEntry(**payload.model_dump())
    db_session.add(entry)
    try:
        await db_session.flush()
    except IntegrityError:
        await db_session.rollback()
        existing_stmt = select(WatchlistEntry).where(WatchlistEntry.show_id == payload.show_id)
        existing = (await db_session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            logger.debug(
                "Show id=%d watchlist entry inserted concurrently (id=%d)",
                payload.show_id,
                existing.id,
            )
            return existing
        raise

    logger.info(
        "Added show id=%d to watchlist (entry id=%d, status=%s)",
        payload.show_id,
        entry.id,
        entry.status,
    )
    return entry


@router.get("/{entry_id}", response_model=WatchlistRead)
async def get_watchlist_entry(
    entry_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WatchlistEntry:
    """Get a single watchlist entry by its ID.

    Args:
        entry_id: Database primary key.
        db_session: DB session (injected).

    Returns:
        The matching WatchlistEntry record.

    Raises:
        HTTPException: 404 if the entry is not found.
    """
    stmt = select(WatchlistEntry).where(WatchlistEntry.id == entry_id)
    entry = (await db_session.execute(stmt)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    return entry


@router.patch("/{entry_id}", response_model=WatchlistRead)
async def update_watchlist_entry(
    entry_id: int,
    payload: WatchlistUpdate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WatchlistEntry:
    """Update a watchlist entry's status, notes, or position.

    Only fields explicitly provided in the request body are updated.

    Args:
        entry_id: Database primary key.
        payload: Fields to update.
        db_session: DB session (injected).

    Returns:
        The updated WatchlistEntry record.

    Raises:
        HTTPException: 404 if the entry is not found.
        HTTPException: 400 if the status value is invalid.
    """
    stmt = select(WatchlistEntry).where(WatchlistEntry.id == entry_id)
    entry = (await db_session.execute(stmt)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    if "status" in payload.model_fields_set and payload.status is not None:
        entry.status = WatchlistStatus(payload.status)
    if "notes" in payload.model_fields_set:
        entry.notes = payload.notes
    if "position" in payload.model_fields_set and payload.position is not None:
        entry.position = payload.position

    await db_session.flush()
    logger.info("Updated watchlist entry id=%d: %s", entry_id, payload.model_fields_set)
    return entry


@router.delete("/{entry_id}", status_code=204)
async def delete_watchlist_entry(
    entry_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Remove a show from the watchlist.

    Args:
        entry_id: Database primary key.
        db_session: DB session (injected).

    Raises:
        HTTPException: 404 if the entry is not found.
    """
    stmt = select(WatchlistEntry).where(WatchlistEntry.id == entry_id)
    entry = (await db_session.execute(stmt)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    await db_session.delete(entry)
    logger.info("Removed show id=%d from watchlist (entry id=%d)", entry.show_id, entry_id)
