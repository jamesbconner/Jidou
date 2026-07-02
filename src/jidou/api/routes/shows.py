"""API routes for show management and TMDB discovery."""

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, func, nullslast, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.schemas.episode_schema import BackingFile, EpisodeList
from jidou.schemas.file_schema import FileRead
from jidou.schemas.show_schema import (
    AssignImportRequest,
    RematchRequest,
    ShowAliasesUpdate,
    ShowCreate,
    ShowList,
    ShowPatch,
    ShowPaths,
    ShowRead,
)
from jidou.services.episode_tracking import clear_episode_tracking, mark_episode_tracked
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shows", tags=["shows"])


_tmdb = TMDBService()

_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_sys_name(title: str) -> str:
    """Derive a Windows-safe directory name from a show title."""
    return _INVALID_FS_CHARS.sub("_", title).strip()


# TMDB genre ID 16 = Animation
_ANIMATION_GENRE_ID = 16


def _infer_content_type(payload: ShowCreate) -> str:
    """Infer routing content type from TMDB metadata.

    Rules (applied in order):
    - ``movie`` media type → ``"movie"``
    - Animation genre AND (Japanese language OR JP origin) → ``"anime"``
    - Everything else → ``"tv"``

    Accepts both TMDB response shapes:
    - Search/trending cards supply ``genre_ids: [16, 18]`` (flat int list).
    - Detail endpoints supply ``genres: [{"id": 16, "name": "Animation"}]``.

    Args:
        payload: Show creation payload containing TMDB metadata.

    Returns:
        One of ``"movie"``, ``"anime"``, or ``"tv"``.
    """
    if payload.media_type == "movie":
        return "movie"
    # Collect genre IDs from whichever field the caller populated.
    ids_from_objects = {g.get("id") for g in (payload.genres or [])}
    ids_from_list = set(payload.genre_ids or [])
    all_genre_ids = ids_from_objects | ids_from_list
    is_animated = _ANIMATION_GENRE_ID in all_genre_ids
    is_japanese = payload.original_language == "ja" or "JP" in (payload.origin_country or [])
    if is_animated and is_japanese:
        return "anime"
    return "tv"


# ---------------------------------------------------------------------------
# TMDB discovery endpoints (literal paths — must come before /{show_id})
# ---------------------------------------------------------------------------


async def get_tmdb() -> TMDBService:
    """Return the shared TMDB service instance."""
    return _tmdb


@router.get("/trending")
async def get_trending(
    media_type: str = "tv",
    time_window: str = "day",
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> dict[str, Any]:
    """Return trending shows from TMDB.

    Args:
        media_type: ``"tv"``, ``"movie"``, or ``"multi"``.
        time_window: ``"day"`` or ``"week"``.
        tmdb: TMDB service (injected).

    Returns:
        Raw TMDB trending response dictionary.
    """
    return await tmdb.get_trending(media_type=media_type, time_window=time_window)


@router.get("/search")
async def search_shows(
    query: str,
    media_type: str = "multi",
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> dict[str, Any]:
    """Search TMDB for shows matching a query.

    Args:
        query: Search term.
        media_type: ``"tv"``, ``"movie"``, or ``"multi"``.
        tmdb: TMDB service (injected).

    Returns:
        Raw TMDB search response dictionary.
    """
    return await tmdb.search(query=query, media_type=media_type)


@router.get("/tmdb/{tmdb_id}")
async def get_tmdb_details(
    tmdb_id: int,
    media_type: str = "tv",
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> dict[str, Any]:
    """Return full TMDB metadata for a show by its TMDB ID.

    Args:
        tmdb_id: The TMDB identifier for the show or movie.
        media_type: ``"tv"`` or ``"movie"``.
        tmdb: TMDB service (injected).

    Returns:
        Raw TMDB detail response dictionary.
    """
    return await tmdb.get_details(tmdb_id=tmdb_id, media_type=media_type)


# ---------------------------------------------------------------------------
# Database CRUD
# ---------------------------------------------------------------------------


_SORT_MAP: dict[str, ColumnElement[Any]] = {
    "title_asc": Show.title.asc(),
    "title_desc": Show.title.desc(),
    "added_desc": Show.created_at.desc(),
    "added_asc": Show.created_at.asc(),
    "release_desc": nullslast(Show.release_date.desc()),
    "release_asc": nullslast(Show.release_date.asc()),
    "last_aired_desc": nullslast(Show.last_air_date.desc()),
    "rating_desc": nullslast(Show.vote_average.desc()),
    "episodes_desc": nullslast(Show.number_of_episodes.desc()),
}


@router.get("", response_model=list[ShowList])
async def list_shows(
    limit: int = 500,
    offset: int = 0,
    sort: str = Query(
        default="title_asc",
        pattern=(
            "^(title_asc|title_desc|added_desc|added_asc"
            "|release_desc|release_asc|last_aired_desc|rating_desc|episodes_desc)$"
        ),
    ),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ShowList]:
    """List all shows stored in the database.

    Args:
        limit: Maximum results to return (default 500).
        offset: Number of results to skip for pagination.
        sort: Sort order key. One of: ``title_asc``, ``title_desc``,
            ``added_desc``, ``added_asc``, ``release_desc``, ``release_asc``,
            ``last_aired_desc``, ``rating_desc``, ``episodes_desc``.
        db_session: DB session (injected).

    Returns:
        List of shows in the requested order with local episode counts.
    """
    ep_count_sq = (
        select(func.count(Episode.id))
        .where(Episode.show_id == Show.id)
        .correlate(Show)
        .scalar_subquery()
    )
    file_count_sq = (
        select(func.count(DownloadedFile.id))
        .where(DownloadedFile.show_id == Show.id)
        .correlate(Show)
        .scalar_subquery()
    )
    stmt = (
        select(Show, ep_count_sq.label("episode_count"), file_count_sq.label("matched_file_count"))
        .order_by(_SORT_MAP[sort])
        .offset(offset)
        .limit(limit)
    )
    rows = (await db_session.execute(stmt)).all()
    shows: list[ShowList] = []
    for show, ep_count, file_count in rows:
        data = ShowList.model_validate(show)
        data.episode_count = ep_count
        data.matched_file_count = file_count
        shows.append(data)
    return shows


@router.post("", response_model=ShowRead, status_code=201)
async def create_show(
    payload: ShowCreate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> Show:
    """Add a show to the database (upsert by TMDB ID).

    If the show already exists it is returned unchanged.  ``sys_name`` is
    auto-derived from the title if not provided.  For newly created shows a
    TMDB episode sync is attempted inline so the show detail page shows
    episodes immediately.  TMDB failures are logged but do not abort the
    response — the show is still returned.

    Args:
        payload: Show data from a TMDB search/trending result.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        The created or existing :class:`Show` record.
    """
    from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator

    stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
    existing = (await db_session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        logger.debug("Show tmdb_id=%d already exists (id=%d)", payload.tmdb_id, existing.id)
        return existing

    data = payload.model_dump()
    if not data.get("sys_name"):
        data["sys_name"] = _sanitize_sys_name(payload.title)
    if not data.get("content_type"):
        data["content_type"] = _infer_content_type(payload)
    # genre_ids is a ShowCreate-only field (search card shape); Show has no such column.
    data.pop("genre_ids", None)

    show = Show(**data, cached=False)
    db_session.add(show)
    try:
        await db_session.flush()
    except IntegrityError:
        await db_session.rollback()
        stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
        existing = (await db_session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            logger.debug(
                "Show tmdb_id=%d inserted concurrently, returning existing (id=%d)",
                payload.tmdb_id,
                existing.id,
            )
            return existing
        raise

    logger.info("Added show tmdb_id=%d title=%r (id=%d)", show.tmdb_id, show.title, show.id)

    if show.media_type != "movie":
        try:
            await TMDBOrchestrator(db_session, tmdb).sync_show_episodes(show)
            logger.info("Auto-synced episodes for show id=%d tmdb_id=%d", show.id, show.tmdb_id)
        except SQLAlchemyError:
            # DB failure during sync's internal commit — the show row was rolled
            # back along with the episodes; propagate so the caller gets a 500.
            raise
        except Exception:
            logger.warning(
                "Episode sync failed for new show id=%d tmdb_id=%d"
                " — user can retry via Sync Episodes",
                show.id,
                show.tmdb_id,
                exc_info=True,
            )

    await db_session.refresh(show)
    return show


@router.get("/{show_id}", response_model=ShowRead)
async def get_show(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Show:
    """Get a show by its database ID.

    Args:
        show_id: Database primary key.
        db_session: DB session (injected).

    Returns:
        The matching :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    return show


@router.put("/{show_id}/paths", response_model=ShowRead)
async def update_show_paths(
    show_id: int,
    payload: ShowPaths,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Show:
    """Update a show's local filesystem path.

    Passing ``null`` for the field clears the stored path.

    Args:
        show_id: Database primary key.
        payload: New path value.
        db_session: DB session (injected).

    Returns:
        The updated :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    if "local_path" in payload.model_fields_set:
        show.local_path = payload.local_path
    await db_session.flush()
    await db_session.refresh(show)
    logger.info("Updated local_path for show id=%d: %r", show_id, show.local_path)
    return show


@router.put("/{show_id}/aliases", response_model=ShowRead)
async def update_show_aliases(
    show_id: int,
    payload: ShowAliasesUpdate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Show:
    """Replace the full aliases list for a show.

    Aliases are normalised to lowercase before storage.  Duplicate values
    are silently deduplicated.

    Args:
        show_id: Database primary key.
        payload: New list of alias strings.
        db_session: DB session (injected).

    Returns:
        The updated :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    normalised = list(dict.fromkeys(a.strip().lower() for a in payload.aliases if a.strip()))
    show.aliases = normalised or None
    await db_session.flush()
    await db_session.refresh(show)
    logger.info("Updated aliases for show id=%d: %r", show_id, show.aliases)
    return show


@router.delete("/{show_id}", status_code=204)
async def delete_show(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Remove a show and all its cascaded data from the database.

    Args:
        show_id: Database primary key.
        db_session: DB session (injected).

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    await db_session.delete(show)
    logger.info("Deleted show id=%d title=%r", show_id, show.title)


@router.patch("/{show_id}", response_model=ShowRead)
async def patch_show(
    show_id: int,
    payload: ShowPatch,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Show:
    """Partially update user-managed fields on a show.

    Only fields explicitly included in the request body are applied.
    Pass ``null`` for a field to clear it.

    Args:
        show_id: Database primary key.
        payload: Partial update with the fields to change.
        db_session: DB session (injected).

    Returns:
        The updated :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    for field in payload.model_fields_set:
        setattr(show, field, getattr(payload, field))

    await db_session.flush()
    await db_session.refresh(show)
    logger.info("Patched show id=%d fields=%r", show_id, list(payload.model_fields_set))
    return show


@router.post("/{show_id}/rematch", response_model=ShowRead)
async def rematch_show(
    show_id: int,
    payload: RematchRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> Show:
    """Re-match a show to a different TMDB entry.

    Replaces all TMDB-sourced metadata on the show row, purges every episode
    that was synced from the old entry, and syncs fresh episodes from the new
    TMDB ID.  User-managed fields (``local_path``, ``content_type``, ``aliases``)
    are preserved.

    Args:
        show_id: Database primary key of the show to re-match.
        payload: ``{ "tmdb_id": <new_tmdb_id> }``
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        The updated :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
        HTTPException: 409 if the target TMDB ID is already tracked as a
            different show.
        HTTPException: 502 if TMDB details or episode sync fails.
    """
    from jidou.orchestrators.show_rematch_orchestrator import ShowRematchOrchestrator

    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    if payload.tmdb_id != show.tmdb_id:
        conflict = (
            await db_session.execute(select(Show).where(Show.tmdb_id == payload.tmdb_id))
        ).scalar_one_or_none()
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"TMDB ID {payload.tmdb_id} is already tracked as"
                    f" '{conflict.title}' (id={conflict.id})"
                ),
            )

    return await ShowRematchOrchestrator(db_session, tmdb).rematch(show, payload)


@router.post("/{show_id}/sync-episodes", response_model=list[EpisodeList])
async def sync_episodes(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> list[Episode]:
    """Sync episodes from TMDB for a specific show and return the updated list.

    Args:
        show_id: Database primary key of the show to sync.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        Updated list of episodes ordered by season and episode number.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator

    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    orchestrator = TMDBOrchestrator(db_session, tmdb)
    await orchestrator.sync_show_episodes(show)

    ep_stmt = (
        select(Episode)
        .where(Episode.show_id == show_id)
        .order_by(Episode.season_number, Episode.episode_number)
    )
    result = await db_session.execute(ep_stmt)
    return list(result.scalars().all())


@router.get("/{show_id}/episodes", response_model=list[EpisodeList])
async def list_episodes(
    show_id: int,
    season: int | None = None,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[EpisodeList]:
    """List episodes for a show, optionally filtered by season number.

    Args:
        show_id: Database primary key of the show.
        season: If provided, return only episodes from this season.
        db_session: DB session (injected).

    Returns:
        List of episodes ordered by season and episode number, each including
        ``backing_file_id`` if a DownloadedFile is linked to that episode.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    show_stmt = select(Show).where(Show.id == show_id)
    if (await db_session.execute(show_stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Show not found")

    ep_stmt = select(Episode).where(Episode.show_id == show_id)
    if season is not None:
        ep_stmt = ep_stmt.where(Episode.season_number == season)
    ep_stmt = ep_stmt.order_by(Episode.season_number, Episode.episode_number)
    episodes = list((await db_session.execute(ep_stmt)).scalars().all())

    # Fetch all DownloadedFiles linked to these episodes in one query.
    episode_ids = [ep.id for ep in episodes]
    files_by_episode: dict[int, list[BackingFile]] = {}
    if episode_ids:
        files_stmt = (
            select(
                DownloadedFile.episode_id,
                DownloadedFile.id,
                DownloadedFile.original_filename,
            )
            .where(
                DownloadedFile.episode_id.in_(episode_ids),
                # Exclude pending synthetic rows so a cancelled Fix Match on an
                # imported episode doesn't flip the chip from Imported → Matched.
                ~DownloadedFile.remote_path.like("synthetic-import://%"),
            )
            .order_by(DownloadedFile.id)
        )
        for ep_id, file_id, filename in (await db_session.execute(files_stmt)).all():
            files_by_episode.setdefault(ep_id, []).append(
                BackingFile(id=file_id, filename=filename or "")
            )

    result: list[EpisodeList] = []
    for ep in episodes:
        el = EpisodeList.model_validate(ep, from_attributes=True)
        el.backing_files = files_by_episode.get(ep.id, [])
        result.append(el)
    return result


@router.post(
    "/{show_id}/episodes/{episode_id}/begin-rematch",
    response_model=FileRead,
)
async def begin_episode_rematch(
    show_id: int,
    episode_id: int,
    file_id: int | None = Query(default=None),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Prepare a downloaded episode's backing file for re-matching.

    Episode tracking is **not** cleared here — it is only cleared once the
    route task successfully completes, so cancelling the re-match modal leaves
    the episode showing as tracked.

    Only valid for episodes backed by a :class:`DownloadedFile`.  Imported
    episodes (tracked via path-import with no backing file) must use
    ``POST /shows/{show_id}/episodes/{episode_id}/assign-import`` instead.

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the episode.
        file_id: Optional ID of a specific backing file to re-match when the
            episode has multiple tracked files.
        db_session: DB session (injected).

    Returns:
        A ``FileRead`` ready to be passed to the re-match modal.

    Raises:
        HTTPException: 404 if the show, episode, or specified file is not found.
        HTTPException: 422 if the episode is not tracked or has no backing file.
    """
    show_stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(show_stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    ep_stmt = select(Episode).where(Episode.id == episode_id, Episode.show_id == show_id)
    ep = (await db_session.execute(ep_stmt)).scalar_one_or_none()
    if ep is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    if not ep.file_tracked:
        raise HTTPException(status_code=422, detail="Episode is not tracked")

    backing: DownloadedFile | None = None

    if file_id is not None:
        # Caller specified which file to re-match (multiple-file episode).
        specific_stmt = (
            select(DownloadedFile)
            .where(
                DownloadedFile.id == file_id,
                DownloadedFile.episode_id == episode_id,
            )
            .options(
                selectinload(DownloadedFile.show),
                selectinload(DownloadedFile.episode),
            )
        )
        backing = (await db_session.execute(specific_stmt)).scalar_one_or_none()
        if backing is None:
            raise HTTPException(status_code=404, detail="File not found for this episode")
    else:
        # Look for any backing DownloadedFile — handles downloaded and legacy
        # pre-migration episodes where tracked_source is null.
        any_stmt = (
            select(DownloadedFile)
            .where(DownloadedFile.episode_id == episode_id)
            .options(
                selectinload(DownloadedFile.show),
                selectinload(DownloadedFile.episode),
            )
            .limit(1)
        )
        backing = (await db_session.execute(any_stmt)).scalar_one_or_none()

    if backing is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Episode has no backing file. "
                "Use POST /shows/{show_id}/episodes/{episode_id}/assign-import "
                "to reassign imported episode tracking."
            ),
        )

    # Leave status unchanged — resetting to DOWNLOADED would enroll the file
    # in the match orchestrator while the RematchModal is still open, creating
    # a race where auto-match re-links the episode before the user confirms.
    # The user's confirmation (POST /files/{id}/match) sets status=MATCHED,
    # which the route orchestrator picks up to move the file.
    return backing


@router.post(
    "/{show_id}/episodes/{episode_id}/assign-import",
    status_code=200,
)
async def assign_import_episode(
    show_id: int,
    episode_id: int,
    payload: AssignImportRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, bool]:
    """Reassign an imported episode's tracked filename to a different episode.

    Atomically moves ``payload.filename`` from whichever episode currently
    holds it to ``episode_id``.  Both sides of the transfer are updated in
    the same transaction — no :class:`DownloadedFile` is created and no route
    task is triggered, because the file is already at its final location on
    disk.

    This endpoint handles arbitrary permutations of imported filenames across
    episodes in the same show, including cases where the target episode already
    tracks a different file (the displaced file is simply cleared).

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the target episode.
        payload: Contains ``filename`` — one of the show's existing tracked
            filenames (taken from any episode's ``tracked_filename`` field).
        db_session: DB session (injected).

    Returns:
        ``{"ok": true}`` on success.

    Raises:
        HTTPException: 404 if the show or target episode is not found.
        HTTPException: 422 if ``payload.filename`` is not currently tracked
            by any episode in this show.
    """
    show_stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(show_stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    target_stmt = select(Episode).where(Episode.id == episode_id, Episode.show_id == show_id)
    target_ep = (await db_session.execute(target_stmt)).scalar_one_or_none()
    if target_ep is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Find the import-tracked episode that currently holds this filename.
    # Filenames tracked via 'match' (download-backed) are not in the import pool —
    # moving them would desync the Episode from its DownloadedFile row.
    source_stmt = select(Episode).where(
        Episode.show_id == show_id,
        Episode.tracked_filename == payload.filename,
        Episode.tracked_source == "import",
    )
    source_ep = (await db_session.execute(source_stmt)).scalar_one_or_none()
    if source_ep is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Filename {payload.filename!r} is not in this show's import pool. "
                "Only filenames tracked via path-import can be reassigned here."
            ),
        )

    # Refuse to overwrite a download-backed episode's tracking — that episode's
    # DownloadedFile row would be left inconsistently linked.
    if target_ep.file_tracked and target_ep.tracked_source != "import":
        raise HTTPException(
            status_code=422,
            detail=(
                "Target episode is backed by a downloaded file. "
                "Use POST /shows/{show_id}/episodes/{episode_id}/begin-rematch to reassign it."
            ),
        )

    if source_ep.id != target_ep.id:
        # Capture the filename target currently holds before overwriting it.
        # If target held a different import filename, swap it back to source so it
        # stays in the pool.  If target was untracked (None), source is cleared.
        displaced = target_ep.tracked_filename

        if displaced and displaced != payload.filename:
            mark_episode_tracked(source_ep, displaced, "import")
        else:
            clear_episode_tracking(source_ep)

    # Assign the filename to the target episode.
    mark_episode_tracked(target_ep, payload.filename, "import")

    await db_session.flush()
    await db_session.commit()
    return {"ok": True}
