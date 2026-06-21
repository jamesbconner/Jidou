"""API routes for downloaded file management."""

import asyncio
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators.parse_orchestrator import _heuristic_se
from jidou.schemas.file_schema import FileMatchRequest, FilePatch, FileRead
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_sys_name(title: str) -> str:
    """Derive a Windows-safe directory name from a show title."""
    return _INVALID_FS_CHARS.sub("_", title).strip()


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
        HTTPException: 409 if the file is not in a re-matchable status.
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

    matchable = {FileStatus.DOWNLOADED, FileStatus.UNMATCHED, FileStatus.ERROR}
    if file.status not in matchable:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot match a file with status '{file.status.value}'; "
            f"only {', '.join(s.value for s in matchable)} files can be matched",
        )

    # ── Reset path: no show_id or tmdb_id → queue for auto re-match ──────────
    if payload.show_id is None and payload.tmdb_id is None:
        file.status = FileStatus.DOWNLOADED
        file.show_id = None
        file.episode_id = None
        file.matched_by = None
        file.error_message = None
        await db_session.flush()
        await db_session.commit()
        logger.info("Reset file id=%d to downloaded for auto re-matching", file_id)
        return file

    # ── On-demand show creation via TMDB ID ───────────────────────────────────
    if payload.tmdb_id is not None:
        # Check DB first (idempotent)
        show_stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
        show = (await db_session.execute(show_stmt)).scalar_one_or_none()

        if show is None:
            if not payload.local_path:
                raise HTTPException(
                    status_code=422,
                    detail="local_path is required when creating a new show via tmdb_id",
                )
            tmdb = TMDBService()
            # Use the TMDB-reported media_type from the search result (tv/movie).
            # Fall back to inferring from content_type only when not provided.
            media_type = payload.tmdb_media_type or (
                "movie" if payload.content_type == "movie" else "tv"
            )
            ep_groups: dict[str, Any] = {}
            try:
                if media_type == "tv":
                    data, ext_ids, ep_groups = await asyncio.gather(
                        tmdb.get_details(payload.tmdb_id, media_type=media_type),
                        tmdb.get_external_ids(payload.tmdb_id, media_type=media_type),
                        tmdb.get_episode_groups(payload.tmdb_id),
                    )
                else:
                    data, ext_ids = await asyncio.gather(
                        tmdb.get_details(payload.tmdb_id, media_type=media_type),
                        tmdb.get_external_ids(payload.tmdb_id, media_type=media_type),
                    )
            except Exception as exc:
                raise HTTPException(status_code=404, detail=f"TMDB lookup failed: {exc}") from exc

            title = data.get("name") or data.get("title") or ""
            # TV: origin_country is a flat list ["JP"]. Movie: production_countries
            # is [{"iso_3166_1": "US", ...}]. Normalise both to a flat code list.
            raw_countries: list[object] = data.get("origin_country") or [
                c["iso_3166_1"]
                for c in (data.get("production_countries") or [])
                if isinstance(c, dict) and "iso_3166_1" in c
            ]
            # TV: episode_run_time is a list; take first value. Movie: runtime is an int.
            ep_runtimes: list[int] = data.get("episode_run_time") or []
            runtime: int | None = data.get("runtime") or (ep_runtimes[0] if ep_runtimes else None)
            show = Show(
                tmdb_id=payload.tmdb_id,
                title=title,
                overview=data.get("overview"),
                media_type=media_type,
                poster_path=data.get("poster_path"),
                backdrop_path=data.get("backdrop_path"),
                vote_average=data.get("vote_average"),
                vote_count=data.get("vote_count", 0),
                release_date=data.get("first_air_date") or data.get("release_date"),
                original_language=data.get("original_language"),
                genres=data.get("genres") or [],
                origin_country=raw_countries,
                last_air_date=data.get("last_air_date"),
                last_episode_to_air=data.get("last_episode_to_air"),
                next_episode_to_air=data.get("next_episode_to_air"),
                homepage=data.get("homepage"),
                external_ids=ext_ids or {},
                episode_groups=ep_groups.get("results") or [],
                status=data.get("status"),
                in_production=data.get("in_production"),
                number_of_seasons=data.get("number_of_seasons"),
                number_of_episodes=data.get("number_of_episodes"),
                networks=data.get("networks") or [],
                show_type=data.get("type"),
                runtime=runtime,
                tagline=data.get("tagline"),
                sys_name=_sanitize_sys_name(title),
                content_type=payload.content_type,
                local_path=payload.local_path,
                cached=False,
            )
            db_session.add(show)
            try:
                await db_session.flush()
            except IntegrityError:
                await db_session.rollback()
                show_stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
                show = (await db_session.execute(show_stmt)).scalar_one_or_none()
                if show is None:
                    raise
                # Apply caller's path/type to the concurrently-created row
                if payload.local_path:
                    show.local_path = payload.local_path
                if payload.content_type:
                    show.content_type = payload.content_type
                await db_session.flush()
            else:
                logger.info(
                    "Created show tmdb_id=%d title=%r (id=%d) via on-demand match",
                    show.tmdb_id,
                    show.title,
                    show.id,
                )
        else:
            # Show exists — update local_path / content_type if caller provided them
            if payload.local_path:
                show.local_path = payload.local_path
            if payload.content_type:
                show.content_type = payload.content_type
            await db_session.flush()

    else:
        # ── Existing show by show_id ───────────────────────────────────────────
        show_stmt = select(Show).where(Show.id == payload.show_id)
        show = (await db_session.execute(show_stmt)).scalar_one_or_none()
        if show is None:
            raise HTTPException(status_code=404, detail="Show not found")

    if show.local_path is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Show has no local_path configured; "
                "provide local_path or set it via PATCH /shows/{id}/paths"
            ),
        )

    file.show_id = show.id
    file.episode_id = None  # clear stale episode from any previous match
    file.matched_by = MatchedBy.MANUAL
    file.status = FileStatus.MATCHED
    file.error_message = None

    # Populate parsed_season / parsed_episode from filename heuristic so
    # RouteOrchestrator can place the file in Season NN/ instead of show root.
    if file.parsed_season is None and file.parsed_episode is None:
        se = _heuristic_se(file.original_filename)
        if se is not None:
            file.parsed_season, file.parsed_episode = se
            ep_stmt = select(Episode).where(
                (Episode.show_id == show.id)
                & (Episode.season_number == file.parsed_season)
                & (Episode.episode_number == file.parsed_episode)
            )
            ep = (await db_session.execute(ep_stmt)).scalar_one_or_none()
            if ep is not None:
                file.episode_id = ep.id

    await db_session.flush()
    await db_session.commit()

    logger.info(
        "Manually matched file id=%d → show id=%d (%s) S%sE%s",
        file_id,
        show.id,
        show.title,
        file.parsed_season,
        file.parsed_episode,
    )
    return file
