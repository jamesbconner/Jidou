"""API routes for downloaded file management and episode matching."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.schemas.file_schema import FileList, FileMatchRequest, FilePatch, FileRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


@router.get("", response_model=list[FileList])
async def list_files(
    status: str | None = None,
    show_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DownloadedFile]:
    """List tracked downloaded files with optional filters.

    Args:
        status: Filter by file status (``pending``, ``downloaded``, etc.).
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
            # Invalidate match data that belonged to the previous show
            if "episode_id" not in payload.model_fields_set:
                file.episode_id = None
            file.matched_by = None  # not patchable — always clear on reassignment
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
        if pgcode == "23503":
            raise HTTPException(
                status_code=422,
                detail="Referenced show_id or episode_id does not exist",
            ) from None
        if pgcode is None or pgcode == "23505":
            raise HTTPException(
                status_code=409,
                detail="A file with that show_id and remote_path combination already exists",
            ) from None
        raise
    logger.info("Patched file id=%d fields=%s", file_id, payload.model_fields_set)
    return file


@router.post("/{file_id}/match", response_model=FileRead)
async def rematch_file(
    file_id: int,
    payload: FileMatchRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Re-trigger episode matching for a downloaded file.

    Resets the file status to ``pending`` and dispatches a Celery match task
    for the file's associated show.  The match worker will update status and
    populate ``episode_id`` and ``matched_by`` when it completes.

    Args:
        file_id: Database primary key.
        payload: Matching strategy hint (``"auto"``, ``"llm"``, or
            ``"heuristic"``).  Stored for observability; the current worker
            uses show-level matching.
        db_session: DB session (injected).

    Returns:
        The updated :class:`DownloadedFile` record with status reset to
        ``pending``.

    Raises:
        HTTPException: 404 if the file is not found.
        HTTPException: 422 if the file has no associated show (cannot match
            without a show assignment).
        HTTPException: 503 if the Celery broker is unavailable.
    """
    stmt = select(DownloadedFile).where(DownloadedFile.id == file_id)
    file = (await db_session.execute(stmt)).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")

    if file.show_id is None:
        raise HTTPException(
            status_code=422,
            detail="File has no associated show; assign a show before re-matching",
        )

    # Reset to pending, then commit so the worker reads the updated state from
    # its own DB connection before it begins processing.
    # Clear episode_id so the worker assigns a fresh match rather than
    # returning a stale result that contradicts pending status.
    file.status = FileStatus.PENDING
    file.episode_id = None
    file.matched_by = None
    file.error_message = None
    await db_session.flush()
    await db_session.commit()

    try:
        from jidou.workers.match_tasks import match_files_task

        match_files_task.apply_async(args=[file.show_id, False])
    except Exception as exc:
        logger.exception("Failed to dispatch match task for file %d", file_id)
        # Roll the file back to ERROR so it is not left as PENDING with no
        # queued job — the caller can retry once the broker is available.
        file.status = FileStatus.ERROR
        file.error_message = "Failed to dispatch matching task to broker"
        await db_session.flush()
        await db_session.commit()
        raise HTTPException(
            status_code=503,
            detail="Failed to dispatch matching task to broker",
        ) from exc

    logger.info(
        "Re-queued matching for file id=%d show_id=%d method=%s",
        file_id,
        file.show_id,
        payload.method,
    )
    return file
