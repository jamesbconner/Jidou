"""API routes for downloaded file management."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.show import Show
from jidou.schemas.file_schema import FileMatchRequest, FilePatch, FileRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


@router.get("", response_model=list[FileRead])
async def list_files(
    status: str | None = None,
    show_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DownloadedFile]:
    """List tracked downloaded files with optional filters.

    Args:
        status: Filter by file status (``discovered``, ``downloaded``, etc.).
        show_id: Filter by matched show ID.
        limit: Maximum results to return (default 50).
        offset: Number of results to skip for pagination.
        db_session: DB session (injected).

    Returns:
        List of files ordered by creation time descending.

    Raises:
        HTTPException: 400 if *status* is not a valid :class:`FileStatus`.
    """
    stmt = select(DownloadedFile)

    if status is not None:
        try:
            file_status = FileStatus(status)
        except ValueError:
            valid = [s.value for s in FileStatus]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status {status!r}. Must be one of: {valid}",
            ) from None
        stmt = stmt.where(DownloadedFile.status == file_status)

    if show_id is not None:
        stmt = stmt.where(DownloadedFile.show_id == show_id)

    stmt = stmt.order_by(DownloadedFile.created_at.desc()).offset(offset).limit(limit)
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


@router.get("/unmatched", response_model=list[FileRead])
async def list_unmatched_files(
    limit: int = 50,
    offset: int = 0,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DownloadedFile]:
    """List files that could not be automatically matched to a show.

    Returns files in ``unmatched`` status ordered by creation time descending.
    These files require manual review via ``POST /files/{id}/match``.

    Args:
        limit: Maximum results to return (default 50).
        offset: Number of results to skip for pagination.
        db_session: DB session (injected).

    Returns:
        List of unmatched :class:`DownloadedFile` records.
    """
    stmt = (
        select(DownloadedFile)
        .where(DownloadedFile.status == FileStatus.UNMATCHED)
        .order_by(DownloadedFile.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


@router.get("/{file_id}", response_model=FileRead)
async def get_file(
    file_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Get a single downloaded-file record.

    Args:
        file_id: Database primary key.
        db_session: DB session (injected).

    Returns:
        The matching :class:`DownloadedFile` record.

    Raises:
        HTTPException: 404 if the file is not found.
    """
    stmt = select(DownloadedFile).where(DownloadedFile.id == file_id)
    file = (await db_session.execute(stmt)).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return file


@router.patch("/{file_id}", response_model=FileRead)
async def patch_file(
    file_id: int,
    payload: FilePatch,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Manually override show_id, episode_id, status, or error_message on a file.

    Only fields explicitly provided in the request body are updated.
    Intended for operator correction of mismatched or stuck files.

    Args:
        file_id: Database primary key.
        payload: Fields to update.
        db_session: DB session (injected).

    Returns:
        The updated DownloadedFile record.

    Raises:
        HTTPException: 404 if the file is not found.
        HTTPException: 400 if the status value is not a valid FileStatus.
    """
    stmt = select(DownloadedFile).where(DownloadedFile.id == file_id)
    file = (await db_session.execute(stmt)).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")

    if "show_id" in payload.model_fields_set:
        show_changed = file.show_id != payload.show_id
        file.show_id = payload.show_id
        if show_changed:
            if "episode_id" not in payload.model_fields_set:
                file.episode_id = None
            file.matched_by = None
            if "error_message" not in payload.model_fields_set:
                file.error_message = None
    if "episode_id" in payload.model_fields_set:
        file.episode_id = payload.episode_id
    if "status" in payload.model_fields_set and payload.status is not None:
        file.status = FileStatus(payload.status)
    if "error_message" in payload.model_fields_set:
        file.error_message = payload.error_message

    try:
        await db_session.flush()
    except IntegrityError as exc:
        await db_session.rollback()
        orig = getattr(exc, "orig", None)
        pgcode = getattr(orig, "pgcode", None)
        if pgcode == "23505":
            raise HTTPException(
                status_code=409,
                detail="A file with that remote_path already exists",
            ) from None
        if pgcode == "23503":
            raise HTTPException(
                status_code=422,
                detail="Referenced show_id or episode_id does not exist",
            ) from None
        raise
    logger.info("Patched file id=%d fields=%s", file_id, payload.model_fields_set)
    return file


@router.post("/{file_id}/match", response_model=FileRead)
async def manual_match_file(
    file_id: int,
    payload: FileMatchRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Assign a show to an unmatched file, or reset it for automatic re-matching.

    When ``show_id`` is provided the show is assigned directly (manual match)
    and the file transitions to ``matched`` for the next route phase.
    When ``show_id`` is omitted the file is reset to ``downloaded`` so the
    parse pipeline will re-process it automatically on the next sync.

    Args:
        file_id: Database primary key.
        payload: Optional ``show_id``; omit to trigger automatic re-matching.
        db_session: DB session (injected).

    Returns:
        The updated :class:`DownloadedFile` record.

    Raises:
        HTTPException: 404 if the file or show is not found.
        HTTPException: 409 if the file is not in a re-matchable status.
        HTTPException: 422 if the show has no ``local_path`` configured.
    """
    stmt = select(DownloadedFile).where(DownloadedFile.id == file_id)
    file = (await db_session.execute(stmt)).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")

    matchable = {FileStatus.DOWNLOADED, FileStatus.UNMATCHED, FileStatus.ERROR}
    if file.status not in matchable:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot match a file with status '{file.status.value}'; "
            f"only {', '.join(s.value for s in matchable)} files can be matched",
        )

    if payload.show_id is None:
        # Auto re-match: reset to DOWNLOADED so the parse phase picks it up.
        file.status = FileStatus.DOWNLOADED
        file.show_id = None
        file.episode_id = None
        file.matched_by = None
        file.error_message = None
        await db_session.flush()
        await db_session.commit()
        logger.info("Reset file id=%d to downloaded for auto re-matching", file_id)
        return file

    show_stmt = select(Show).where(Show.id == payload.show_id)
    show = (await db_session.execute(show_stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    if show.local_path is None:
        raise HTTPException(
            status_code=422,
            detail="Show has no local_path configured; set it via PUT /shows/{id}/paths first",
        )

    file.show_id = show.id
    file.episode_id = None  # clear stale episode from any previous match
    file.matched_by = MatchedBy.MANUAL
    file.status = FileStatus.MATCHED
    file.error_message = None
    await db_session.flush()
    await db_session.commit()

    logger.info(
        "Manually matched file id=%d → show id=%d (%s)",
        file_id,
        show.id,
        show.title,
    )
    return file
