"""API routes for downloaded file management."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.api.dependencies import get_llm_service
from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.orchestrators.manual_match_orchestrator import ManualMatchOrchestrator
from jidou.schemas.file_schema import FileMatchRequest, FilePatch, FileRead
from jidou.services.episode_tracking import (
    clear_if_unreferenced,
    dismiss_orphans_for_file,
    mark_episode_tracked,
)
from jidou.services.llm_service import LLMService
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


@router.get("", response_model=list[FileRead])
async def list_files(
    response: Response,
    status: str | None = None,
    show_id: int | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DownloadedFile]:
    """List tracked downloaded files with optional filters.

    Args:
        status: Filter by file status (``discovered``, ``downloaded``, etc.).
        show_id: Filter by matched show ID.
        search: Case-insensitive substring match on ``original_filename``.
        limit: Maximum results to return (1-1000, default 50).
        offset: Number of results to skip for pagination.
        response: FastAPI response object used to set ``X-Total-Count`` header.
        db_session: DB session (injected).

    Returns:
        List of files ordered by creation time descending.

    Raises:
        HTTPException: 400 if *status* is not a valid :class:`FileStatus`.
    """
    filters = []

    if status is not None:
        try:
            file_status = FileStatus(status)
        except ValueError:
            valid = [s.value for s in FileStatus]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status {status!r}. Must be one of: {valid}",
            ) from None
        filters.append(DownloadedFile.status == file_status)

    if show_id is not None:
        filters.append(DownloadedFile.show_id == show_id)

    if search is not None:
        filters.append(DownloadedFile.original_filename.ilike(f"%{search}%"))

    total = await db_session.scalar(
        select(func.count()).select_from(DownloadedFile).where(*filters)
    )
    response.headers["X-Total-Count"] = str(total or 0)

    stmt = (
        select(DownloadedFile)
        .options(selectinload(DownloadedFile.show), selectinload(DownloadedFile.episode))
        .where(*filters)
        .order_by(DownloadedFile.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
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
    stmt = (
        select(DownloadedFile)
        .where(DownloadedFile.id == file_id)
        .options(selectinload(DownloadedFile.show), selectinload(DownloadedFile.episode))
    )
    file = (await db_session.execute(stmt)).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return file


@router.get("/{file_id}/tmdb-suggestions")
async def tmdb_suggestions(
    file_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Return TMDB search results for an unmatched file based on its parsed show name.

    Uses the file's ``parsed_show_name`` (set by the parse pipeline) as the
    search query.  Results are cached by the TMDB service layer.

    Args:
        file_id: Database primary key of the unmatched file.
        db_session: DB session (injected).

    Returns:
        ``{"query": str, "results": [...]}`` with up to 6 TMDB candidates.

    Raises:
        HTTPException: 404 if the file is not found.
        HTTPException: 422 if the file has no parsed show name to search with.
    """
    stmt = select(DownloadedFile).where(DownloadedFile.id == file_id)
    file = (await db_session.execute(stmt)).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")

    query = file.parsed_show_name or ""
    if not query:
        raise HTTPException(
            status_code=422,
            detail="File has no parsed_show_name; run the parse phase first",
        )

    tmdb = TMDBService()
    data = await tmdb.search(query, media_type="multi")
    tv_movie = [r for r in data.get("results", []) if r.get("media_type") in ("tv", "movie")]
    results = [
        {
            "tmdb_id": r.get("id"),
            "title": r.get("name") or r.get("title"),
            "media_type": r.get("media_type"),
            "overview": r.get("overview"),
            "poster_path": r.get("poster_path"),
            "first_air_date": r.get("first_air_date") or r.get("release_date"),
            "vote_average": r.get("vote_average"),
        }
        for r in tv_movie[:6]
    ]
    return {"query": query, "results": results}


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
            # Purge any orphan rows tied to this file — they reference the old
            # show and resolving them after reassignment would corrupt show_id.
            await dismiss_orphans_for_file(db_session, file.id)
    if "episode_id" in payload.model_fields_set:
        old_episode_id = file.episode_id
        file.episode_id = payload.episode_id
        if payload.episode_id is not None:
            # Auto-dismiss any orphan record that was waiting for this file to be re-linked.
            await dismiss_orphans_for_file(db_session, file.id)
            # Mark the target episode as tracked so the UI and stats reflect the link.
            ep = (
                await db_session.execute(select(Episode).where(Episode.id == payload.episode_id))
            ).scalar_one_or_none()
            if ep is not None:
                if file.show_id is not None and ep.show_id != file.show_id:
                    raise HTTPException(
                        status_code=422,
                        detail="Episode does not belong to the file's show",
                    )
                if ep.file_tracked and old_episode_id != payload.episode_id:
                    raise HTTPException(
                        status_code=409,
                        detail="Episode is already tracked by another file",
                    )
                mark_episode_tracked(ep, file.local_path or file.original_filename, "match")
                file.parsed_season = ep.season_number
                file.parsed_episode = ep.episode_number
        else:
            file.parsed_season = None
            file.parsed_episode = None
        # Clear stale tracking on the previous episode only when no other file
        # still points to it — mirrors the guard in manual_match_file.
        await clear_if_unreferenced(db_session, old_episode_id, payload.episode_id)
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
    refreshed = (
        await db_session.execute(
            select(DownloadedFile)
            .where(DownloadedFile.id == file_id)
            .options(selectinload(DownloadedFile.show), selectinload(DownloadedFile.episode))
        )
    ).scalar_one()
    logger.info("Patched file id=%d fields=%s", file_id, payload.model_fields_set)
    return refreshed


@router.post("/{file_id}/match", response_model=FileRead)
async def manual_match_file(
    file_id: int,
    payload: FileMatchRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
) -> DownloadedFile:
    """Assign a show to an unmatched file, or reset it for automatic re-matching.

    Three modes controlled by the request body:

    * ``show_id`` supplied: assign an existing tracked show directly.
    * ``tmdb_id`` supplied: look up or create the show on demand from TMDB,
      then assign.  ``local_path`` is required when creating a new show.
    * Neither supplied: reset the file to ``downloaded`` for automatic
      re-processing by the parse pipeline.

    Args:
        file_id: Database primary key.
        payload: Match request; see :class:`FileMatchRequest` for fields.
        db_session: DB session (injected).

    Returns:
        The updated :class:`DownloadedFile` record.

    Raises:
        HTTPException: 404 if the file, show, or TMDB resource is not found.
        HTTPException: 409 if the file is in a non-re-matchable status (e.g. DOWNLOADING).
        HTTPException: 422 if the show has no ``local_path`` or if both
            ``show_id`` and ``tmdb_id`` are supplied.
    """
    if payload.show_id is not None and payload.tmdb_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Provide either show_id or tmdb_id, not both",
        )

    stmt = select(DownloadedFile).where(DownloadedFile.id == file_id)
    file = (await db_session.execute(stmt)).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")

    matchable = {
        FileStatus.DOWNLOADED,
        FileStatus.UNMATCHED,
        FileStatus.MATCHED,
        FileStatus.ROUTING,
        FileStatus.ROUTED,
        FileStatus.ERROR,
    }
    if file.status not in matchable:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot match a file with status '{file.status.value}'; "
            f"only {', '.join(s.value for s in matchable)} files can be matched",
        )

    return await ManualMatchOrchestrator(db_session, llm).match(file, payload)
