"""API routes for show management and TMDB discovery."""

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any, Literal

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, func, nullslast, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.api.dependencies import get_llm_service
from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.rss import RssSubscription
from jidou.models.show import Show
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus
from jidou.schemas.calendar_schema import CalendarEpisode
from jidou.schemas.discover_schema import DiscoverResult
from jidou.schemas.episode_schema import BackingFile, EpisodeList
from jidou.schemas.file_schema import EpisodeBrief, FileRead
from jidou.schemas.rss_schema import RssSubscriptionRead
from jidou.schemas.show_schema import (
    AssignImportRequest,
    LinkFileRequest,
    RematchRequest,
    ScannedFileMatch,
    ShowAliasesUpdate,
    ShowCreate,
    ShowList,
    ShowPatch,
    ShowPaths,
    ShowRead,
)
from jidou.services.cache import cache
from jidou.services.episode_file_matching import match_entry_to_episode
from jidou.services.episode_tracking import clear_episode_tracking, mark_episode_tracked
from jidou.services.llm_service import LLMService
from jidou.services.path_parser import path_comparison_key, scan_show_directory
from jidou.services.path_resolution import resolve_show_local_path
from jidou.services.rss_stub import ensure_rss_stub
from jidou.services.synthetic_file import create_synthetic_import_file
from jidou.services.sys_name import sanitize_sys_name
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shows", tags=["shows"])


_tmdb = TMDBService()


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


def _auto_local_path(content_type: str, sys_name: str) -> str:
    """Compute the default local path for a new show from configured media roots.

    Args:
        content_type: One of ``"anime"``, ``"movie"``, or ``"tv"``.
        sys_name: Filesystem-safe show directory name.

    Returns:
        Absolute container-side path string.
    """
    from jidou.config import settings

    return resolve_show_local_path(
        content_type=content_type,
        media_type=None,
        sys_name=sys_name,
        local_tv_path=settings.local_tv_path,
        local_anime_path=settings.local_anime_path,
        local_movie_path=settings.local_movie_path,
    )


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


# Number of most-recently-updated watching/completed watchlist entries used to
# seed recommendations. Each seed show costs one rate-limited TMDB call
# (~2s, serialized — the shared RateLimiter holds a single lock across all
# callers, so concurrency doesn't help here), so this also bounds worst-case
# latency on a cache-cold request to roughly _DISCOVER_SEED_LIMIT * 2s.
_DISCOVER_SEED_LIMIT = 5
# Recommendations taken from each seed show, before dedup/exclusion.
_DISCOVER_PER_SHOW_LIMIT = 10
_DISCOVER_CACHE_TTL = 86_400  # 24h — the assembled/deduped feed, not the underlying TMDB calls


def _to_discover_result(
    raw: dict[str, Any], media_type: str, seeded_from: list[str]
) -> DiscoverResult:
    """Build a :class:`DiscoverResult` from a raw TMDB result dict.

    Args:
        raw: Raw TMDB result entry (from a recommendations or trending response).
        media_type: ``"tv"`` or ``"movie"`` — recommendations responses are
            already scoped to one type and don't include this field themselves.
        seeded_from: Watchlist show titles this result was recommended because
            of. Empty for trending-only fill items.

    Returns:
        A populated :class:`DiscoverResult`.
    """
    return DiscoverResult(
        id=raw["id"],
        media_type=media_type,
        name=raw.get("name"),
        title=raw.get("title"),
        overview=raw.get("overview"),
        poster_path=raw.get("poster_path"),
        backdrop_path=raw.get("backdrop_path"),
        vote_average=raw.get("vote_average"),
        vote_count=raw.get("vote_count"),
        release_date=raw.get("release_date"),
        first_air_date=raw.get("first_air_date"),
        original_language=raw.get("original_language"),
        genre_ids=raw.get("genre_ids"),
        origin_country=raw.get("origin_country"),
        adult=raw.get("adult"),
        seeded_from=seeded_from,
    )


@router.get("/discover", response_model=list[DiscoverResult])
async def discover_shows(
    limit: int = Query(default=40, ge=1, le=100),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> list[DiscoverResult]:
    """Return a personalized discovery feed of shows not yet in the library.

    Seeded from TMDB recommendations for the user's most recently engaged
    watchlist shows (``watching``/``completed``), deduplicated and merged with
    trending TV/movies to fill out the feed. Shows already in the library are
    excluded. The assembled feed is cached for 24h, keyed by the current seed
    show set so a watchlist change invalidates it without waiting out the TTL.

    Args:
        limit: Maximum results to return (1-100, default 40).
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        List of :class:`DiscoverResult`, seeded items first.
    """
    seed_stmt = (
        select(WatchlistEntry)
        .where(WatchlistEntry.status.in_([WatchlistStatus.WATCHING, WatchlistStatus.COMPLETED]))
        .options(selectinload(WatchlistEntry.show))
        .order_by(WatchlistEntry.updated_at.desc())
        .limit(_DISCOVER_SEED_LIMIT)
    )
    seed_entries = (await db_session.execute(seed_stmt)).scalars().all()

    cache_key_parts = sorted(f"{e.show.tmdb_id}:{e.show.media_type}" for e in seed_entries)
    cache_key = cache.make_key("discover:" + ",".join(cache_key_parts))
    cached = await cache.get(cache_key)
    if cached is not None:
        return [DiscoverResult(**item) for item in cached][:limit]

    existing_stmt = select(Show.tmdb_id, Show.media_type)
    existing = {(t, m) for t, m in (await db_session.execute(existing_stmt)).all()}

    seeded: dict[tuple[int, str], DiscoverResult] = {}
    for entry in seed_entries:
        show = entry.show
        if show.media_type not in {"movie", "tv"}:
            continue
        try:
            data = await tmdb.get_recommendations(show.tmdb_id, show.media_type)
        except (ValueError, httpx.HTTPStatusError):
            logger.warning("Discover: recommendations failed for show_id=%d", show.id)
            continue
        for raw in data.get("results", [])[:_DISCOVER_PER_SHOW_LIMIT]:
            key = (raw["id"], show.media_type)
            if key in existing:
                continue
            if key in seeded:
                seeded[key].seeded_from.append(show.title)
            else:
                seeded[key] = _to_discover_result(raw, show.media_type, [show.title])

    results = sorted(seeded.values(), key=lambda r: (-len(r.seeded_from), -(r.vote_average or 0)))

    if len(results) < limit:
        try:
            trending = await tmdb.get_trending(media_type="multi", time_window="week")
        except (ValueError, httpx.HTTPStatusError):
            logger.warning("Discover: trending fallback failed")
            trending = {"results": []}
        for raw in trending.get("results", []):
            media_type = raw.get("media_type")
            if media_type not in {"movie", "tv"}:
                continue
            key = (raw["id"], media_type)
            if key in existing or key in seeded:
                continue
            seeded[key] = _to_discover_result(raw, media_type, [])
            results.append(seeded[key])
            if len(results) >= limit:
                break

    results = results[:limit]
    await cache.set(
        cache_key, [r.model_dump() for r in results], label="discover", ttl=_DISCOVER_CACHE_TTL
    )
    return results


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
    active_rss_sq = (
        select(RssSubscription.id)
        .where(
            RssSubscription.show_id == Show.id,
            RssSubscription.active.is_(True),
            RssSubscription.enabled_in_config.is_(True),
        )
        .correlate(Show)
        .exists()
    )
    stmt = (
        select(
            Show,
            ep_count_sq.label("episode_count"),
            file_count_sq.label("matched_file_count"),
            active_rss_sq.label("has_active_rss_subscription"),
        )
        .order_by(_SORT_MAP[sort])
        .offset(offset)
        .limit(limit)
    )
    rows = (await db_session.execute(stmt)).all()
    shows: list[ShowList] = []
    for show, ep_count, file_count, has_active_rss in rows:
        data = ShowList.model_validate(show)
        data.episode_count = ep_count
        data.matched_file_count = file_count
        data.has_active_rss_subscription = has_active_rss
        shows.append(data)
    return shows


@router.get("/calendar", response_model=list[CalendarEpisode])
async def get_calendar(
    start: date,
    end: date,
    today: date | None = None,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[CalendarEpisode]:
    """Return episodes airing within a date range, across all shows.

    Every show with a matching episode appears — library and watchlist
    shows are the same ``Show`` table, so no separate scope filter is needed.

    Args:
        start: First date to include (inclusive).
        end: Last date to include (inclusive).
        today: The caller's notion of "today", used to decide "tracked"/
            "missing" vs "upcoming". The frontend always passes the
            browser's local date here — falling back to the API host's own
            clock (which may be in a different timezone, or just briefly
            disagree near a day boundary) would make the computed status
            disagree with whichever day the UI highlights as "today".
        db_session: DB session (injected).

    Returns:
        Episodes ordered by air date then show title, each with a computed
        ``status`` ("tracked", "missing", or "upcoming") so the frontend
        never has to reason about "today" itself.
    """
    stmt = (
        select(Episode, Show)
        .join(Show, Episode.show_id == Show.id)
        .where(Episode.air_date.between(start, end))
        .order_by(Episode.air_date, Show.title)
    )
    rows = (await db_session.execute(stmt)).all()

    today = today or date.today()
    results: list[CalendarEpisode] = []
    for episode, show in rows:
        # Excluded by the WHERE clause above; narrows the type for the
        # CalendarEpisode.air_date field (non-nullable).
        if episode.air_date is None:
            continue

        status: Literal["tracked", "missing", "upcoming"]
        if episode.air_date > today:
            status = "upcoming"
        elif episode.file_tracked:
            status = "tracked"
        else:
            status = "missing"

        results.append(
            CalendarEpisode(
                episode_id=episode.id,
                show_id=show.id,
                show_title=show.title,
                poster_path=show.poster_path,
                season_number=episode.season_number,
                episode_number=episode.episode_number,
                name=episode.name,
                air_date=episode.air_date,
                status=status,
            )
        )
    return results


@router.post("", response_model=ShowRead, status_code=201)
async def create_show(
    payload: ShowCreate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
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
        await TMDBOrchestrator(db_session, tmdb).ensure_episode_group_map(existing)
        return existing

    data = payload.model_dump()
    if not data.get("sys_name"):
        data["sys_name"] = sanitize_sys_name(payload.title)
    if not data.get("content_type"):
        data["content_type"] = _infer_content_type(payload)
    if not data.get("local_path"):
        data["local_path"] = _auto_local_path(data["content_type"], data["sys_name"])
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
            await TMDBOrchestrator(db_session, tmdb).ensure_episode_group_map(existing)
            return existing
        raise

    logger.info("Added show tmdb_id=%d title=%r (id=%d)", show.tmdb_id, show.title, show.id)

    if show.media_type != "movie":
        try:
            await TMDBOrchestrator(db_session, tmdb).sync_show_episodes(show)
            logger.info("Auto-synced episodes for show id=%d tmdb_id=%d", show.id, show.tmdb_id)
        except SQLAlchemyError:
            # DB failure during sync's internal flush leaves the session's
            # transaction in a broken state; propagate so the caller gets a
            # 500 rather than silently issuing more queries against a dead
            # transaction.
            raise
        except Exception:
            logger.warning(
                "Episode sync failed for new show id=%d tmdb_id=%d"
                " — user can retry via Sync Episodes",
                show.id,
                show.tmdb_id,
                exc_info=True,
            )

    # Commit the show (and any synced episodes) now, independent of alias
    # generation below. sync_show_episodes only flushes, so without this
    # commit a later DB-level failure in alias generation would roll back
    # an already-successful sync too -- both steps are meant to be
    # independently best-effort, not able to undo each other.
    await db_session.commit()

    try:
        from jidou.orchestrators.alias_orchestrator import generate_aliases

        await generate_aliases(show, tmdb, llm=llm)
        await db_session.flush()
    except Exception:
        logger.warning(
            "Alias generation failed for new show id=%d tmdb_id=%d"
            " — aliases can be regenerated via POST /shows/{id}/aliases/regenerate",
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

    from jidou.orchestrators.alias_orchestrator import _build_flat_aliases

    normalised = list(dict.fromkeys(a.strip().lower() for a in payload.aliases if a.strip()))
    existing_sources: dict[str, list[str]] = show.aliases_sources or {}
    if not show.aliases_sources and show.aliases:
        # Legacy shows pre-date the structured aliases_sources column.  Their
        # flat aliases were never split into tmdb/llm/user buckets.  Merge them
        # into the user list on first structured write so they aren't silently
        # dropped (generate_aliases can resplit them when the user regenerates).
        legacy = [a for a in show.aliases if a not in normalised]
        normalised = normalised + legacy
    new_sources = {
        "tmdb": existing_sources.get("tmdb") or [],
        "llm": existing_sources.get("llm") or [],
        "user": normalised,
    }
    show.aliases_sources = new_sources
    show.aliases = _build_flat_aliases(new_sources)
    await db_session.flush()
    await db_session.refresh(show)
    logger.info("Updated user aliases for show id=%d: %r", show_id, normalised)
    return show


@router.post("/{show_id}/aliases/regenerate", response_model=ShowRead)
async def regenerate_show_aliases(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
) -> Show:
    """Regenerate TMDB and LLM alias sources for a show.

    Fetches fresh alternative titles from TMDB, runs the LLM normalizer (if
    configured), and rebuilds both ``aliases_sources`` and the flat ``aliases``
    column.  User-defined aliases in ``aliases_sources.user`` are preserved.

    Args:
        show_id: Database primary key of the show.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).
        llm: LLM service (injected).

    Returns:
        The updated :class:`Show` record.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    from jidou.orchestrators.alias_orchestrator import generate_aliases

    stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    await generate_aliases(show, tmdb, llm=llm)
    await db_session.flush()
    await db_session.refresh(show)
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
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
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

    return await ShowRematchOrchestrator(db_session, tmdb, llm=llm).rematch(show, payload)


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


@router.post("/{show_id}/rss-stub", response_model=RssSubscriptionRead)
async def create_rss_stub(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RssSubscription:
    """Ensure an RSS subscription is linked to this show, creating one if needed.

    Reuses the same link-or-create logic as adding a show to the watchlist
    (:func:`jidou.services.rss_stub.ensure_rss_stub`): an existing linked
    subscription is returned as-is, an unlinked subscription with a matching
    name is linked, and only otherwise is a fresh inactive stub created.

    Args:
        show_id: Database primary key of the show.
        db_session: DB session (injected).

    Returns:
        The linked or newly created RssSubscription.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    show = (await db_session.execute(select(Show).where(Show.id == show_id))).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    sub = await ensure_rss_stub(db_session, show_id, show.title)
    await db_session.flush()
    await db_session.refresh(sub, ["feed", "show"])
    return sub


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
            await _resync_synthetic_file_episode(db_session, displaced, source_ep.id)
        else:
            clear_episode_tracking(source_ep)

    # Assign the filename to the target episode.
    mark_episode_tracked(target_ep, payload.filename, "import")
    await _resync_synthetic_file_episode(db_session, payload.filename, target_ep.id)

    await db_session.flush()
    await db_session.commit()
    return {"ok": True}


@router.post(
    "/{show_id}/episodes/{episode_id}/link-file",
    response_model=FileRead,
)
async def link_episode_file(
    show_id: int,
    episode_id: int,
    payload: LinkFileRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Manually link an on-disk file path to an untracked episode.

    For files that already sit at their final library location but were never
    downloaded or path-imported by Jidou, so no ``DownloadedFile`` row exists
    yet. Creates a display-only, already-ROUTED record using the same
    ``synthetic-import://`` convention as bulk path-import, and marks the
    episode tracked with ``tracked_source="import"`` — this keeps it in the
    ``assign-import`` reassignment pool and existing "Imported" UI treatment
    rather than introducing a third tracking source.

    To link a file Jidou already knows about (an ``unmatched`` DownloadedFile
    row), use ``PATCH /api/files/{file_id}`` instead.

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the episode.
        payload: Contains ``path`` — the absolute on-disk path of the file.
        db_session: DB session (injected).

    Returns:
        The created (or pre-existing) ``DownloadedFile`` record.

    Raises:
        HTTPException: 404 if the show or episode is not found.
        HTTPException: 422 if the episode is already tracked, or *path* does
            not point to an existing file.
    """
    show_stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(show_stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    # Locked so two concurrent link-file calls targeting the same episode
    # (e.g. a bulk "Confirm All Matched" batch) can't both read
    # file_tracked=False before either commits — the second request blocks
    # here until the first's transaction ends, then sees the now-tracked
    # state and 422s below instead of double-linking.
    ep_stmt = (
        select(Episode)
        .where(Episode.id == episode_id, Episode.show_id == show_id)
        .with_for_update()
    )
    ep = (await db_session.execute(ep_stmt)).scalar_one_or_none()
    if ep is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    if ep.file_tracked:
        raise HTTPException(
            status_code=422,
            detail=(
                "Episode is already tracked. Use begin-rematch or assign-import to reassign it."
            ),
        )

    if not Path(payload.path).is_file():
        raise HTTPException(
            status_code=422,
            detail=f"No file exists at path: {payload.path}",
        )

    mark_episode_tracked(ep, payload.path, "import")
    await create_synthetic_import_file(db_session, show_id, episode_id, payload.path)
    await db_session.commit()

    synthetic_remote_path = f"synthetic-import://{payload.path}"
    refreshed = (
        await db_session.execute(
            select(DownloadedFile)
            .where(DownloadedFile.remote_path == synthetic_remote_path)
            .options(selectinload(DownloadedFile.show), selectinload(DownloadedFile.episode))
        )
    ).scalar_one()
    logger.info(
        "Linked file path=%r to episode id=%d (show id=%d)", payload.path, episode_id, show_id
    )
    return refreshed


@router.post(
    "/{show_id}/scan-local-files",
    response_model=list[ScannedFileMatch],
)
async def scan_show_local_files(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
) -> list[ScannedFileMatch]:
    """List and auto-match media files found under a show's own local directory.

    An alternative to bulk text-file import for episodes whose files are
    already sitting at their final on-disk location — e.g. picking up
    stragglers a prior import missed, or files that predate Jidou entirely.
    Read-only: nothing is written. The same matching pipeline bulk path-import
    uses (regex heuristics, episode_group remap, LLM fallback — see
    :func:`~jidou.services.episode_file_matching.match_entry_to_episode`)
    resolves each file to a proposed episode.

    Files whose path matches an already-recorded ``DownloadedFile`` for this
    show (a prior import or download — compared via
    :func:`~jidou.services.path_parser.path_comparison_key`, since a prior
    bulk-import path string and this scan's live-filesystem path string can
    differ in format while referring to the same file) are skipped entirely.
    Everything else is returned with a status:

    - ``matched``: proposed episode is untracked and not claimed by an
      earlier row in this same scan; ready to confirm via
      ``POST /shows/{show_id}/episodes/{episode_id}/link-file``.
    - ``unmatched``: no episode could be resolved.
    - ``conflict``: the proposed episode is already tracked by a different
      file, or was already claimed by an earlier row in this scan (e.g. a
      duplicate file) — confirming would need ``link-file``'s existing 422
      guard overridden by picking a different episode first.

    Args:
        show_id: Database primary key of the show.
        db_session: DB session (injected).
        llm: LLM service (injected) — used as a fallback when regex parsing
            can't resolve a filename; matching still works without one.

    Returns:
        One :class:`ScannedFileMatch` per file found, sorted by path.

    Raises:
        HTTPException: 404 if the show is not found.
        HTTPException: 422 if the show has no local path configured.
    """
    show_stmt = select(Show).where(Show.id == show_id)
    show = (await db_session.execute(show_stmt)).scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    if not show.local_path:
        raise HTTPException(status_code=422, detail="Show has no local path configured")

    # Filesystem I/O is synchronous — run it off the event loop so a large or
    # slow-mounted show directory doesn't stall every other concurrent request.
    entries = await asyncio.to_thread(scan_show_directory, show.local_path)

    existing_paths_stmt = select(DownloadedFile.local_path).where(DownloadedFile.show_id == show_id)
    existing_keys = {
        path_comparison_key(p)
        for (p,) in (await db_session.execute(existing_paths_stmt)).all()
        if p
    }

    results: list[ScannedFileMatch] = []
    # Tracks episodes already claimed by an earlier row in this same scan, so
    # two files resolving to the same untracked episode (e.g. a duplicate)
    # are never both reported "matched" — only the first (by sort order).
    claimed_episode_ids: set[int] = set()
    for entry in entries:
        if path_comparison_key(entry.raw_path) in existing_keys:
            continue

        ep, season, episode_number = await match_entry_to_episode(
            db_session, llm, show_id, show.title, entry, show.episode_group_map
        )

        if ep is None:
            status: Literal["matched", "unmatched", "conflict"] = "unmatched"
        elif ep.file_tracked or ep.id in claimed_episode_ids:
            status = "conflict"
        else:
            status = "matched"
            claimed_episode_ids.add(ep.id)

        results.append(
            ScannedFileMatch(
                path=entry.raw_path,
                filename=Path(entry.raw_path).name,
                season=season,
                episode_number=episode_number,
                episode=EpisodeBrief.model_validate(ep) if ep is not None else None,
                status=status,
            )
        )

    return results


async def _resync_synthetic_file_episode(
    db_session: AsyncSession,
    filename: str,
    episode_id: int,
) -> None:
    """Repoint a path-imported file's synthetic DownloadedFile at its new episode.

    Path-import creates a display-only ``DownloadedFile(status=ROUTED)`` row
    for each tracked filename (see ``PathImportOrchestrator``), keyed by a
    ``synthetic-import://<filename>`` ``remote_path``. ``assign_import_episode``
    only moved ``Episode.tracked_filename``/``tracked_source`` between rows —
    without this, the synthetic file's ``episode_id`` would still point at
    whichever episode held the filename before the reassignment, so the Files
    page would list it under the wrong (or no longer tracked) episode.

    A no-op if no such row exists yet (e.g. data imported before this
    convention existed).

    Args:
        db_session: DB session (injected).
        filename: The raw path used as both ``Episode.tracked_filename`` and
            the synthetic file's ``remote_path`` suffix.
        episode_id: The episode the file should now be linked to.
    """
    stmt = select(DownloadedFile).where(
        DownloadedFile.remote_path == f"synthetic-import://{filename}"
    )
    synthetic_file = (await db_session.execute(stmt)).scalar_one_or_none()
    if synthetic_file is not None:
        synthetic_file.episode_id = episode_id
