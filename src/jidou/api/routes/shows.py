"""API routes for show management and TMDB discovery."""

import logging
import re
from datetime import datetime
from typing import Any, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, func, nullslast, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.show import Show
from jidou.schemas.episode_schema import BackingFile, EpisodeList
from jidou.schemas.file_schema import FileRead
from jidou.schemas.show_schema import (
    RematchRequest,
    ShowAliasesUpdate,
    ShowCreate,
    ShowList,
    ShowPatch,
    ShowPaths,
    ShowRead,
)
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shows", tags=["shows"])


class _TrackingSnapshot(TypedDict):
    """Tracking state captured from an Episode before the rematch bulk-delete."""

    tracked_filename: str | None
    tracked_source: str | None
    file_tracked_at: datetime | None


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
        HTTPException: 502 if TMDB details cannot be fetched.
    """
    from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator

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

    try:
        data = await tmdb.get_details(payload.tmdb_id, media_type=payload.media_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to fetch TMDB details") from exc

    # TV uses "name" + "first_air_date"; movies use "title" + "release_date".
    title: str = data.get("name") or data.get("title") or show.title
    release_date: str | None = data.get("first_air_date") or data.get("release_date")
    ep_runtimes: list[int] = data.get("episode_run_time") or []

    # Update all TMDB-sourced fields; preserve user-managed ones.
    show.tmdb_id = payload.tmdb_id
    show.media_type = payload.media_type
    show.title = title
    show.overview = data.get("overview")
    show.poster_path = data.get("poster_path")
    show.backdrop_path = data.get("backdrop_path")
    show.vote_average = data.get("vote_average")
    show.vote_count = data.get("vote_count", 0)
    show.release_date = release_date
    show.original_language = data.get("original_language")
    show.sys_name = _sanitize_sys_name(title)
    show.genres = data.get("genres") or []
    # TV uses origin_country (ISO list); movies use production_countries (objects).
    tv_countries: list[str] = data.get("origin_country") or []
    movie_countries: list[str] = [
        c["iso_3166_1"] for c in (data.get("production_countries") or []) if "iso_3166_1" in c
    ]
    show.origin_country = tv_countries or movie_countries
    show.last_air_date = data.get("last_air_date")
    show.last_episode_to_air = data.get("last_episode_to_air")
    show.next_episode_to_air = data.get("next_episode_to_air")
    show.homepage = data.get("homepage")
    show.status = data.get("status")
    show.in_production = data.get("in_production")
    show.number_of_seasons = data.get("number_of_seasons")
    show.number_of_episodes = data.get("number_of_episodes")
    show.networks = data.get("networks") or []
    show.show_type = data.get("type")
    show.runtime = data.get("runtime") or (ep_runtimes[0] if ep_runtimes else None)
    show.tagline = data.get("tagline")
    show.external_ids = data.get("external_ids")
    show.episode_groups = data.get("episode_groups") or []

    # Phase 1: Snapshot tracked episodes before the bulk delete so tracking state
    # can be restored after the new TMDB episodes are synced.
    old_tracking: dict[tuple[int, int], _TrackingSnapshot] = {}
    if payload.preserve_tracking and payload.media_type != "movie":
        tracked_stmt = select(Episode).where(
            Episode.show_id == show_id,
            Episode.file_tracked.is_(True),
        )
        tracked_eps = (await db_session.execute(tracked_stmt)).scalars().all()
        for ep in tracked_eps:
            old_tracking[(ep.season_number, ep.episode_number)] = _TrackingSnapshot(
                tracked_filename=ep.tracked_filename,
                tracked_source=ep.tracked_source,
                file_tracked_at=ep.file_tracked_at,
            )
        logger.debug(
            "Tracking snapshot: show id=%d captured %d tracked episode(s)",
            show_id,
            len(old_tracking),
        )

    # Purge episodes from the old match — they belong to a different show.
    await db_session.execute(
        Episode.__table__.delete().where(Episode.show_id == show_id)  # type: ignore[attr-defined]
    )

    await db_session.flush()
    logger.info("Re-matched show id=%d → tmdb_id=%d title=%r", show_id, payload.tmdb_id, title)

    # Movies have no episode structure; skip TV-specific season sync.
    if payload.media_type != "movie":
        try:
            await TMDBOrchestrator(db_session, tmdb).sync_show_episodes(show)
        except Exception as exc:
            logger.exception("Episode sync failed after rematch for show id=%d", show_id)
            raise HTTPException(
                status_code=502, detail="TMDB episode sync failed; rematch aborted"
            ) from exc

        # Phase 2: Restore tracking on new episodes matching by (season, episode) key.
        # Phase 3: Re-link DownloadedFile rows whose episode_id was SET NULL by cascade.
        if payload.preserve_tracking:
            new_eps_stmt = select(Episode).where(Episode.show_id == show_id)
            new_eps = (await db_session.execute(new_eps_stmt)).scalars().all()
            ep_by_se: dict[tuple[int, int], Episode] = {
                (e.season_number, e.episode_number): e for e in new_eps
            }

            migrated = 0
            for key, state in old_tracking.items():
                matched_ep = ep_by_se.get(key)
                if matched_ep is not None:
                    matched_ep.file_tracked = True
                    matched_ep.file_tracked_at = state["file_tracked_at"]
                    matched_ep.tracked_filename = state["tracked_filename"]
                    matched_ep.tracked_source = state["tracked_source"]
                    migrated += 1

            # Remove stale orphan records for this show before inserting fresh ones
            # so that repeated rematches don't stack duplicate DQ entries.
            await db_session.execute(
                OrphanedTrackingRecord.__table__.delete().where(  # type: ignore[attr-defined]
                    OrphanedTrackingRecord.show_id == show_id
                )
            )

            orphan_stmt = select(DownloadedFile).where(
                DownloadedFile.show_id == show_id,
                DownloadedFile.episode_id.is_(None),
                DownloadedFile.parsed_season.is_not(None),
                DownloadedFile.parsed_episode.is_not(None),
            )
            orphaned_files = (await db_session.execute(orphan_stmt)).scalars().all()
            relinked = 0
            orphan_records_created = 0
            # Track which (season, episode) keys Phase 3 already persisted as orphans
            # so the unrecoverable_keys loop below can skip them and avoid duplicates.
            phase3_orphan_keys: set[tuple[int, int]] = set()
            for file in orphaned_files:
                if file.parsed_season is not None and file.parsed_episode is not None:
                    new_ep = ep_by_se.get((file.parsed_season, file.parsed_episode))
                    if new_ep is not None:
                        file.episode_id = new_ep.id
                        relinked += 1
                    else:
                        # Downloaded file with no matching new episode — persist as orphan.
                        db_session.add(
                            OrphanedTrackingRecord(
                                show_id=show_id,
                                tracked_filename=file.original_filename,
                                tracked_source="match",
                                old_season_number=file.parsed_season,
                                old_episode_number=file.parsed_episode,
                                downloaded_file_id=file.id,
                            )
                        )
                        phase3_orphan_keys.add((file.parsed_season, file.parsed_episode))
                        orphan_records_created += 1

            # All unrecoverable tracking keys (both "import" and "match") need an orphan
            # record. For "match" keys already handled by Phase 3 (file found via parsed
            # S/E), skip to avoid duplicates. "match" keys whose files lack parsed S/E
            # numbers only appear here and would otherwise be silently dropped.
            unrecoverable_keys = set(old_tracking.keys()) - set(ep_by_se.keys())
            for key in unrecoverable_keys:
                if key in phase3_orphan_keys:
                    continue
                state = old_tracking[key]
                db_session.add(
                    OrphanedTrackingRecord(
                        show_id=show_id,
                        tracked_filename=state["tracked_filename"],
                        tracked_source=state["tracked_source"] or "match",
                        old_season_number=key[0],
                        old_episode_number=key[1],
                        downloaded_file_id=None,
                    )
                )
                orphan_records_created += 1

            if unrecoverable_keys:
                logger.warning(
                    "Unrecoverable tracking records after rematch of show id=%d: %d persisted",
                    show_id,
                    orphan_records_created,
                )

            logger.info(
                "Tracking migration: show id=%d migrated=%d relinked=%d orphans_created=%d",
                show_id,
                migrated,
                relinked,
                orphan_records_created,
            )

            await db_session.flush()

    await db_session.refresh(show)
    return show


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
    """Prepare a tracked episode's file for re-matching and return a FileRead.

    Episode tracking is **not** cleared here — it is only cleared once the
    route task successfully completes, so cancelling the re-match modal leaves
    the episode showing as tracked.

    - **Specific file** (``file_id`` supplied): resets that exact
      :class:`DownloadedFile` to ``DOWNLOADED`` without touching its
      ``episode_id``, so the auto-match task can transition it smoothly.
    - **Single backing file** (no ``file_id``): the only file linked to this
      episode is reset the same way.
    - **Imported / no backing file**: a synthetic :class:`DownloadedFile` row
      is created from the episode's stored path so the same re-match / re-route
      flow applies.

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
        HTTPException: 422 if the episode is not currently tracked.
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

    if backing is not None:
        # Leave status unchanged — resetting to DOWNLOADED would enroll the file
        # in the match orchestrator while the RematchModal is still open, creating
        # a race where auto-match re-links the episode before the user confirms.
        # The user's confirmation (POST /files/{id}/match) sets status=MATCHED,
        # which the route orchestrator picks up to move the file.
        file: DownloadedFile = backing
    else:
        # Imported (or legacy) path: create a synthetic DownloadedFile so the
        # RematchModal + route flow works identically to the downloaded case.
        # Set episode_id so a second Fix Match click finds this row instead of
        # inserting a duplicate (unique remote_path would otherwise conflict).
        tracked_path = ep.tracked_filename or ""
        basename = tracked_path.replace("\\", "/").rsplit("/", 1)[-1] or "unknown"
        synthetic_remote = f"synthetic-import://episode-{episode_id}/{basename}"
        file = DownloadedFile(
            show_id=show_id,
            episode_id=episode_id,
            original_filename=basename,
            remote_path=synthetic_remote,
            local_path=tracked_path or None,
            file_size=0,
            status=FileStatus.ROUTED,
            matched_by=MatchedBy.MANUAL,
            parsed_season=ep.season_number,
            parsed_episode=ep.episode_number,
        )
        db_session.add(file)
        await db_session.flush()
        await db_session.refresh(file)

    # Episode tracking stays untouched — it is cleared by the route task after
    # successfully routing the file to its new destination.

    await db_session.flush()
    await db_session.refresh(file)

    # Re-fetch with relationships for synthetic files (downloaded files had
    # selectinload in the query above).
    if backing is None:
        reload_stmt = (
            select(DownloadedFile)
            .where(DownloadedFile.id == file.id)
            .options(
                selectinload(DownloadedFile.show),
                selectinload(DownloadedFile.episode),
            )
        )
        file = (await db_session.execute(reload_stmt)).scalar_one()

    return file
