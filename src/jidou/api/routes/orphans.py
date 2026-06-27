"""API routes for orphaned tracking record management."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.show import Show
from jidou.schemas.orphan_schema import OrphanRead, OrphanResolveRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orphans", tags=["orphans"])


def _to_read(record: OrphanedTrackingRecord, show_title: str) -> OrphanRead:
    """Convert an ORM record + show title to the response schema."""
    return OrphanRead(
        id=record.id,
        show_id=record.show_id,
        show_title=show_title,
        tracked_filename=record.tracked_filename,
        tracked_source=record.tracked_source,
        old_season_number=record.old_season_number,
        old_episode_number=record.old_episode_number,
        downloaded_file_id=record.downloaded_file_id,
        created_at=record.created_at,
    )


@router.get("", response_model=list[OrphanRead])
async def list_orphans(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[OrphanRead]:
    """List all orphaned tracking records across all shows.

    Args:
        db_session: DB session (injected).

    Returns:
        All orphaned tracking records joined with show title.
    """
    stmt = (
        select(OrphanedTrackingRecord, Show.title)
        .join(Show, OrphanedTrackingRecord.show_id == Show.id)
        .order_by(
            Show.title,
            OrphanedTrackingRecord.old_season_number,
            OrphanedTrackingRecord.old_episode_number,
        )
    )
    rows = (await db_session.execute(stmt)).all()
    return [_to_read(record, title) for record, title in rows]


@router.get("/show/{show_id}", response_model=list[OrphanRead])
async def list_orphans_for_show(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[OrphanRead]:
    """List orphaned tracking records for a specific show.

    Args:
        show_id: Database primary key of the show.
        db_session: DB session (injected).

    Returns:
        Orphaned tracking records for the given show.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    show = (await db_session.execute(select(Show).where(Show.id == show_id))).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    stmt = (
        select(OrphanedTrackingRecord)
        .where(OrphanedTrackingRecord.show_id == show_id)
        .order_by(
            OrphanedTrackingRecord.old_season_number,
            OrphanedTrackingRecord.old_episode_number,
        )
    )
    records = (await db_session.execute(stmt)).scalars().all()
    return [_to_read(r, show.title) for r in records]


@router.delete("/{orphan_id}", status_code=204)
async def dismiss_orphan(
    orphan_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Dismiss (delete) an orphaned tracking record without resolving it.

    Args:
        orphan_id: Database primary key of the orphan record.
        db_session: DB session (injected).

    Raises:
        HTTPException: 404 if the record is not found.
    """
    record = (
        await db_session.execute(
            select(OrphanedTrackingRecord).where(OrphanedTrackingRecord.id == orphan_id)
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Orphan record not found")
    await db_session.delete(record)
    await db_session.flush()
    logger.info("Dismissed orphan id=%d (show_id=%d)", orphan_id, record.show_id)


@router.post("/{orphan_id}/resolve", status_code=204)
async def resolve_orphan(
    orphan_id: int,
    payload: OrphanResolveRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Resolve an orphaned tracking record by linking it to a specific episode.

    For imported orphans (``downloaded_file_id is None``): writes tracking
    fields directly onto the target Episode row and deletes the orphan.

    For downloaded orphans (``downloaded_file_id is not None``): links the
    DownloadedFile to the target Episode and deletes the orphan.

    Args:
        orphan_id: Database primary key of the orphan record.
        payload: ``{ "episode_id": <target_episode_id> }``
        db_session: DB session (injected).

    Raises:
        HTTPException: 404 if the orphan record or target episode is not found.
    """
    record = (
        await db_session.execute(
            select(OrphanedTrackingRecord).where(OrphanedTrackingRecord.id == orphan_id)
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Orphan record not found")

    ep = (
        await db_session.execute(select(Episode).where(Episode.id == payload.episode_id))
    ).scalar_one_or_none()
    if ep is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    if ep.show_id != record.show_id:
        raise HTTPException(
            status_code=422,
            detail="Episode does not belong to the show associated with this orphan record",
        )

    if ep.file_tracked:
        raise HTTPException(
            status_code=409,
            detail="Episode is already tracked; dismiss the orphan record if this is intentional",
        )

    if record.downloaded_file_id is None:
        # No linked file: write tracking directly onto the Episode row using the
        # source from the orphan record (may be "import" or "match" when the file
        # was deleted or lacked parsed S/E numbers).
        ep.file_tracked = True
        ep.file_tracked_at = datetime.now(UTC)
        ep.tracked_filename = record.tracked_filename
        ep.tracked_source = record.tracked_source
        logger.info(
            "Resolved %s orphan id=%d → episode id=%d",
            record.tracked_source,
            orphan_id,
            payload.episode_id,
        )
    else:
        # Downloaded orphan: link the DownloadedFile to the target episode and mark it tracked.
        file = (
            await db_session.execute(
                select(DownloadedFile).where(DownloadedFile.id == record.downloaded_file_id)
            )
        ).scalar_one_or_none()
        if file is None:
            raise HTTPException(
                status_code=404,
                detail="The downloaded file linked to this orphan record no longer exists",
            )
        if file.show_id is not None and file.show_id != record.show_id:
            raise HTTPException(
                status_code=422,
                detail="The downloaded file linked to this orphan belongs to a different show",
            )
        file.episode_id = payload.episode_id
        ep.file_tracked = True
        ep.file_tracked_at = datetime.now(UTC)
        ep.tracked_filename = file.local_path or file.original_filename
        ep.tracked_source = "match"
        logger.info(
            "Resolved download orphan id=%d → file id=%d episode id=%d",
            orphan_id,
            record.downloaded_file_id,
            payload.episode_id,
        )

    await db_session.delete(record)
    await db_session.flush()
