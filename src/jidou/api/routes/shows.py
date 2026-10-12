"""API routes for show management (CRUD, search, calendar, rematch, episode groups)."""

import logging
from datetime import date
from typing import Any, Literal

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, func, nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.api.dependencies import get_llm_service, get_tmdb
from jidou.api.lookups import get_show_or_404
from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.rss import RssSubscription
from jidou.models.show import Show
from jidou.orchestrators.show_creation_orchestrator import ShowSeed, get_or_create_show_from_tmdb
from jidou.schemas.calendar_schema import CalendarEpisode, CalendarSyncResult
from jidou.schemas.discover_schema import DiscoverResult
from jidou.schemas.episode_schema import EpisodeList
from jidou.schemas.rss_schema import RssSubscriptionRead
from jidou.schemas.show_schema import (
    EpisodeGroupApplyResponse,
    EpisodeGroupSummary,
    PosterOption,
    RematchRequest,
    ShowAliasesUpdate,
    ShowCreate,
    ShowIndexEntry,
    ShowList,
    ShowPatch,
    ShowPaths,
    ShowRead,
    ShowSearchResult,
)
from jidou.services.cache import cache
from jidou.services.discover_feed import to_discover_result
from jidou.services.llm_service import LLMService
from jidou.services.rss_stub import ensure_rss_stub
from jidou.services.settings_service import (
    get_similar_titles_count,
    get_similar_titles_enabled,
    get_similar_titles_include_external,
)
from jidou.services.show_search import MIN_QUERY_LENGTH, search_local_shows
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import fetch_episode_groups_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shows", tags=["shows"])


# Per-show "Similar Titles" carousel. Merges TMDB /recommendations and /similar
# for one show; the assembled list is cached for 24h keyed by
# (show_id, count, include_external). The underlying TMDB calls have their own
# 7-day cache in TMDBService.
_SIMILAR_CACHE_TTL = 86_400


# ---------------------------------------------------------------------------
# Database CRUD
# ---------------------------------------------------------------------------


_LATEST_EPISODE_ADDED_SQ = (
    select(func.max(Episode.file_tracked_at))
    .where(Episode.show_id == Show.id)
    .correlate(Show)
    .scalar_subquery()
)

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
    "episodes_added_desc": nullslast(_LATEST_EPISODE_ADDED_SQ.desc()),
}


@router.get("/search", response_model=list[ShowSearchResult])
async def search_shows(
    query: str = Query(min_length=MIN_QUERY_LENGTH, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ShowSearchResult]:
    """Search the local library by title, alias, ``sys_name`` or folder name.

    Case-insensitive substring match; results are ranked exact > prefix >
    substring. Folder matching uses only the final component of ``local_path``.
    For TMDB search use ``GET /shows/tmdb/search``.

    Args:
        query: Search text (at least two characters).
        limit: Maximum number of results.
        db_session: Async database session (injected).

    Returns:
        Ranked matching shows, each tagged with the field that matched.
    """
    hits = await search_local_shows(db_session, query, limit=limit)
    return [ShowSearchResult.model_validate(hit) for hit in hits]


# Columns of the library index, in ShowIndexEntry field order. Selecting bare
# columns (not the Show entity) keeps the query to one round trip with no ORM
# identity-map work and no relationship loading, however large the library is.
_INDEX_COLUMNS = (
    Show.id,
    Show.tmdb_id,
    Show.title,
    Show.sys_name,
    Show.aliases,
    Show.media_type,
    Show.content_type,
    Show.local_path,
)


@router.get("/index", response_model=list[ShowIndexEntry])
async def list_show_index(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ShowIndexEntry]:
    """Return the lightweight index of every show in the library.

    Meant for pickers and ``tmdb_id:media_type`` lookups that need the whole
    library but none of the per-show counts ``GET /shows`` computes. It is a
    single column-only query with no pagination, sized for libraries of
    several thousand shows. Registered before ``/{show_id}`` so the literal
    path is not captured by the integer route.

    Ordering is deterministic: ``title`` ascending (database collation), then
    ``id`` ascending as the tie-breaker for shows sharing a title.

    Args:
        db_session: DB session (injected).

    Returns:
        One entry per show, ordered by title then id.
    """
    stmt = select(*_INDEX_COLUMNS).order_by(Show.title.asc(), Show.id.asc())
    rows = (await db_session.execute(stmt)).mappings().all()
    return [ShowIndexEntry.model_validate(dict(row)) for row in rows]


@router.get("", response_model=list[ShowList])
async def list_shows(
    limit: int = 500,
    offset: int = 0,
    sort: str = Query(
        default="title_asc",
        pattern=(
            "^(title_asc|title_desc|added_desc|added_asc"
            "|release_desc|release_asc|last_aired_desc|rating_desc|episodes_desc"
            "|episodes_added_desc)$"
        ),
    ),
    today: date | None = None,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ShowList]:
    """List all shows stored in the database.

    Args:
        limit: Maximum results to return (default 500).
        offset: Number of results to skip for pagination.
        sort: Sort order key. One of: ``title_asc``, ``title_desc``,
            ``added_desc``, ``added_asc``, ``release_desc``, ``release_asc``,
            ``last_aired_desc``, ``rating_desc``, ``episodes_desc``,
            ``episodes_added_desc`` (most recently added episode file first).
        today: The caller's notion of "today", used to decide whether an
            episode has aired for ``missing_episode_count`` and the other
            aired-only counts below. Defaults to the server's current date;
            overridable so a client on a different timezone doesn't disagree
            with the server about "today".
            ``missing_episode_count`` and ``missing_full_season_count`` are
            reported as 0 for shows with ``track_missing_episodes=False``,
            regardless of actual gaps. ``missing_full_season_count`` counts
            seasons (excluding season 0/specials) where every aired episode
            is untracked.
            ``aired_episode_count`` and ``matched_episode_count`` are the
            total aired episodes and the subset of those that are tracked,
            respectively (``matched_episode_count + missing_episode_count
            == aired_episode_count``, ignoring the ``track_missing_episodes``
            zeroing above). ``aired_season_count`` and
            ``matched_full_season_count`` are the season-level equivalents:
            seasons with at least one aired episode, and the subset of those
            fully tracked. Unlike the ``missing_*`` fields, these four are
            always computed regardless of ``track_missing_episodes``.
        db_session: DB session (injected).

    Returns:
        List of shows in the requested order with local episode counts.
    """
    today = today or date.today()
    ep_count_sq = (
        select(func.count(Episode.id))
        .where(Episode.show_id == Show.id)
        .correlate(Show)
        .scalar_subquery()
    )
    watched_ep_count_sq = (
        select(func.count(Episode.id))
        .where(Episode.show_id == Show.id, Episode.watched.is_(True))
        .correlate(Show)
        .scalar_subquery()
    )
    file_count_sq = (
        select(func.count(DownloadedFile.id))
        .where(DownloadedFile.show_id == Show.id)
        .correlate(Show)
        .scalar_subquery()
    )
    missing_ep_count_sq = (
        select(func.count(Episode.id))
        .where(
            Episode.show_id == Show.id,
            Episode.air_date < today,
            Episode.file_tracked.is_(False),
        )
        .correlate(Show)
        .scalar_subquery()
    )
    aired_ep_count_sq = (
        select(func.count(Episode.id))
        .where(Episode.show_id == Show.id, Episode.air_date < today)
        .correlate(Show)
        .scalar_subquery()
    )
    matched_ep_count_sq = (
        select(func.count(Episode.id))
        .where(
            Episode.show_id == Show.id,
            Episode.air_date < today,
            Episode.file_tracked.is_(True),
        )
        .correlate(Show)
        .scalar_subquery()
    )
    # Per-season aired/missing counts, correlated to the outer Show and
    # excluding season 0 (specials). A season with aired_count == missing_count
    # (and aired_count > 0) is fully aired but has no local files at all.
    season_stats_sq = (
        select(
            Episode.season_number,
            func.count(Episode.id).filter(Episode.air_date < today).label("aired_count"),
            func.count(Episode.id)
            .filter(Episode.air_date < today, Episode.file_tracked.is_(False))
            .label("missing_count"),
        )
        .where(Episode.show_id == Show.id, Episode.season_number != 0)
        .correlate(Show)
        .group_by(Episode.season_number)
        .subquery()
    )
    missing_full_season_sq = (
        select(func.count())
        .select_from(season_stats_sq)
        .where(
            season_stats_sq.c.aired_count == season_stats_sq.c.missing_count,
            season_stats_sq.c.aired_count > 0,
        )
        .correlate(Show)
        .scalar_subquery()
    )
    aired_season_count_sq = (
        select(func.count())
        .select_from(season_stats_sq)
        .where(season_stats_sq.c.aired_count > 0)
        .correlate(Show)
        .scalar_subquery()
    )
    matched_full_season_sq = (
        select(func.count())
        .select_from(season_stats_sq)
        .where(
            season_stats_sq.c.aired_count > 0,
            season_stats_sq.c.missing_count == 0,
        )
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
            watched_ep_count_sq.label("watched_episode_count"),
            file_count_sq.label("matched_file_count"),
            missing_ep_count_sq.label("missing_episode_count"),
            missing_full_season_sq.label("missing_full_season_count"),
            aired_ep_count_sq.label("aired_episode_count"),
            matched_ep_count_sq.label("matched_episode_count"),
            aired_season_count_sq.label("aired_season_count"),
            matched_full_season_sq.label("matched_full_season_count"),
            active_rss_sq.label("has_active_rss_subscription"),
            _LATEST_EPISODE_ADDED_SQ.label("latest_episode_added_at"),
        )
        .order_by(_SORT_MAP[sort])
        .offset(offset)
        .limit(limit)
    )
    rows = (await db_session.execute(stmt)).all()
    shows: list[ShowList] = []
    for (
        show,
        ep_count,
        watched_ep_count,
        file_count,
        missing_ep_count,
        missing_full_season_count,
        aired_ep_count,
        matched_ep_count,
        aired_season_count,
        matched_full_season_count,
        has_active_rss,
        latest_episode_added_at,
    ) in rows:
        data = ShowList.model_validate(show)
        data.episode_count = ep_count
        data.watched_episode_count = watched_ep_count
        data.matched_file_count = file_count
        data.missing_episode_count = missing_ep_count if show.track_missing_episodes else 0
        data.missing_full_season_count = (
            missing_full_season_count if show.track_missing_episodes else 0
        )
        data.aired_episode_count = aired_ep_count
        data.matched_episode_count = matched_ep_count
        data.aired_season_count = aired_season_count
        data.latest_episode_added_at = latest_episode_added_at
        data.matched_full_season_count = matched_full_season_count
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
        select(Episode, Show, active_rss_sq.label("has_active_rss_subscription"))
        .join(Show, Episode.show_id == Show.id)
        .where(Episode.air_date.between(start, end))
        .order_by(Episode.air_date, Show.title)
    )
    rows = (await db_session.execute(stmt)).all()

    today = today or date.today()
    results: list[CalendarEpisode] = []
    for episode, show, has_active_rss in rows:
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
                track_missing_episodes=show.track_missing_episodes,
                has_active_rss_subscription=has_active_rss,
                content_type=show.content_type,
                genres=show.genres,
            )
        )
    return results


@router.post("/calendar/sync-missing", response_model=CalendarSyncResult)
async def sync_missing_calendar_shows(
    start: date,
    end: date,
    today: date | None = None,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> CalendarSyncResult:
    """Re-sync TMDB metadata for every show with a "missing" episode in a calendar range.

    Scoped, manually-triggered alternative to clicking "Sync Episodes" on each
    show individually from its detail page. A show is included if it has an
    episode in [start, end] that the calendar would currently mark "missing"
    -- aired on/before *today* per the currently-stored ``air_date``, but no
    file tracked. That's deliberately the same condition :func:`get_calendar`
    uses: a TMDB schedule slip is exactly what produces a false "missing"
    flag, since the stored ``air_date`` says the episode already aired while
    the real schedule moved it later. A genuinely missing episode (aired, no
    file, and TMDB still agrees) is harmlessly re-synced too -- the refresh
    is just a no-op upsert for it. Shows with ``track_missing_episodes=False``
    or with no active, published RSS subscription are skipped -- neither one
    is ever going to auto-download the "missing" episode, so re-syncing TMDB
    metadata for it here would be pointless work. Bypasses TMDB's response cache (see
    ``TMDBService._request``) so a schedule change made within the cache's
    TTL is actually picked up, rather than silently re-serving the same
    stale response this endpoint exists to correct.

    Args:
        start: First date to include (inclusive), matching the calendar view.
        end: Last date to include (inclusive).
        today: Caller's local "today" -- must match what the calendar view
            itself is using (see :func:`get_calendar` for why).
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        Aggregated counts across every show that was re-synced.
    """
    from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator

    today = today or date.today()
    show_ids_stmt = (
        select(Episode.show_id)
        .distinct()
        .where(
            Episode.air_date.between(start, end),
            Episode.air_date <= today,
            Episode.file_tracked == False,  # noqa: E712
        )
    )
    show_ids = list((await db_session.execute(show_ids_stmt)).scalars().all())

    orchestrator = TMDBOrchestrator(db_session, tmdb)
    shows_synced = 0
    shows_failed = 0
    episodes_upserted = 0
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
    for show_id in show_ids:
        show_stmt = select(Show, active_rss_sq.label("has_active_rss_subscription")).where(
            Show.id == show_id, Show.media_type != "movie"
        )
        row = (await db_session.execute(show_stmt)).first()
        if row is None:
            continue
        show, has_active_rss = row
        if not show.track_missing_episodes:
            continue
        if not has_active_rss:
            continue
        try:
            # Own SAVEPOINT per show, same rationale as sync_all_shows: a
            # failure here should only roll back this show's partial work,
            # not expire every already-loaded row for the rest of the loop.
            async with db_session.begin_nested():
                # bypass_cache=True: the whole point of this endpoint is to
                # pick up a TMDB change since the last sync -- serving back
                # the same cached response (up to a 7-day TTL for season/
                # episode endpoints) would rewrite the same stale air_date
                # and leave the episode looking "missing" forever.
                result = await orchestrator.sync_show_episodes(show, bypass_cache=True)
            await db_session.commit()
        except Exception:
            logger.exception("Calendar sync-missing: TMDB re-sync failed for show id=%d", show_id)
            await db_session.rollback()
            shows_failed += 1
            continue
        shows_synced += 1
        episodes_upserted += result.episodes_upserted

    return CalendarSyncResult(
        shows_synced=shows_synced,
        shows_failed=shows_failed,
        episodes_upserted=episodes_upserted,
    )


@router.post("", response_model=ShowRead, status_code=201)
async def create_show(
    payload: ShowCreate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
) -> Show:
    """Add a show to the database (upsert by TMDB ID).

    If the show already exists it is returned unchanged. Otherwise the show is
    created with full TMDB metadata, its episodes are synced and aliases are
    generated; see
    :func:`jidou.orchestrators.show_creation_orchestrator.get_or_create_show_from_tmdb`
    for the best-effort semantics of those steps.

    Args:
        payload: Show data from a TMDB search/trending result.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).
        llm: LLM service (injected).

    Returns:
        The created or existing :class:`Show` record.
    """
    result = await get_or_create_show_from_tmdb(
        db_session, tmdb, ShowSeed.from_create(payload), llm=llm
    )
    return result.show


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
    show = await get_show_or_404(db_session, show_id)
    return show


@router.get("/{show_id}/similar", response_model=list[DiscoverResult])
async def get_similar_shows(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> list[DiscoverResult]:
    """Return titles similar to a show, for the detail page's carousel.

    Merges TMDB ``/recommendations`` (editorial + collaborative) and ``/similar``
    (keyword/genre driven) for the show, deduplicates, drops the show itself,
    and annotates nothing extra -- the frontend cross-references the library by
    ``(tmdb_id, media_type)`` to decide whether a card links to an existing show
    or offers an Add action, exactly as the Discover page does.

    Behaviour is governed by three runtime settings: the feature can be disabled
    (returns ``[]``), the result count is capped, and titles not already in the
    library can be excluded. The assembled list is cached for 24h, keyed by
    ``(show_id, count, include_external)``.

    Args:
        show_id: Database primary key of the show to find matches for.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        List of :class:`DiscoverResult`, recommendation matches before
        similar-only matches, capped to the configured count.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    show = await get_show_or_404(db_session, show_id)

    if not await get_similar_titles_enabled(db_session):
        return []

    count = await get_similar_titles_count(db_session)
    include_external = await get_similar_titles_include_external(db_session)
    media_type = show.media_type
    if media_type not in {"movie", "tv"}:
        return []

    # tmdb_id is part of the key so a rematch (which changes the show's TMDB
    # identity without changing show_id) doesn't keep serving the old show's
    # similar titles until the TTL expires.
    cache_key = cache.make_key(f"similar:{show_id}:{show.tmdb_id}:{count}:{int(include_external)}")
    cached = await cache.get(cache_key)
    if cached is not None:
        return [DiscoverResult(**item) for item in cached]

    library_stmt = select(Show.tmdb_id, Show.media_type)
    library = {(t, m) for t, m in (await db_session.execute(library_stmt)).all()}

    merged: dict[int, DiscoverResult] = {}
    any_failed = False
    for fetch in (tmdb.get_recommendations, tmdb.get_similar):
        try:
            data = await fetch(show.tmdb_id, media_type)
        except (ValueError, httpx.HTTPStatusError):
            any_failed = True
            logger.warning("Similar: %s failed for show_id=%d", fetch.__name__, show.id)
            continue
        for raw in data.get("results", []):
            tmdb_id = raw.get("id")
            if tmdb_id is None or tmdb_id == show.tmdb_id or tmdb_id in merged:
                continue
            if not include_external and (tmdb_id, media_type) not in library:
                continue
            merged[tmdb_id] = to_discover_result(raw, media_type, [])

    results = list(merged.values())[:count]
    # Don't persist an empty list that only exists because TMDB was unreachable
    # -- that would serve "no similar titles" for 24h. A genuine empty result
    # (both calls succeeded, nothing matched) is still cached.
    if results or not any_failed:
        await cache.set(
            cache_key,
            [r.model_dump() for r in results],
            label="similar",
            ttl=_SIMILAR_CACHE_TTL,
        )
    return results


def _filter_and_rank_images(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter a TMDB images-endpoint list to English/textless, most-voted first.

    Shared by the poster and backdrop picker routes -- both apply the same
    "English UI, textless-or-en only" rule to TMDB's ``iso_639_1`` field.

    Args:
        items: Raw ``posters`` or ``backdrops`` entries from ``TMDBService.get_images()``.

    Returns:
        Filtered list sorted by ``vote_average`` descending.
    """
    filtered = [i for i in items if i.get("iso_639_1") in (None, "en")]
    filtered.sort(key=lambda i: i.get("vote_average") or 0, reverse=True)
    return filtered


@router.get("/{show_id}/images/posters", response_model=list[PosterOption])
async def list_show_posters(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> list[dict[str, Any]]:
    """List candidate posters for a show, for the poster-picker modal.

    Filtered to English-language and textless (``iso_639_1: null``) posters
    -- TMDB's poster gallery is dominated by other-language variants that
    aren't useful choices for this app's English UI.

    Args:
        show_id: Database primary key.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        Available posters, most-voted first.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    show = await get_show_or_404(db_session, show_id)

    images = await tmdb.get_images(show.tmdb_id, media_type=show.media_type)
    return _filter_and_rank_images(images.get("posters", []))


@router.get("/{show_id}/images/backdrops", response_model=list[PosterOption])
async def list_show_backdrops(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> list[dict[str, Any]]:
    """List candidate backdrops for a show, for the banner-picker tab.

    Filtered to English-language and textless (``iso_639_1: null``)
    backdrops, same as ``list_show_posters`` -- TMDB does tag some localized
    backdrop variants, which aren't useful choices for this app's English UI.
    Response shape reuses ``PosterOption`` since TMDB's ``posters`` and
    ``backdrops`` entries share an identical shape.

    Args:
        show_id: Database primary key.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        Available backdrops, most-voted first.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    show = await get_show_or_404(db_session, show_id)

    images = await tmdb.get_images(show.tmdb_id, media_type=show.media_type)
    return _filter_and_rank_images(images.get("backdrops", []))


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
    show = await get_show_or_404(db_session, show_id)

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
    show = await get_show_or_404(db_session, show_id)

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

    show = await get_show_or_404(db_session, show_id)

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
    show = await get_show_or_404(db_session, show_id)

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
    show = await get_show_or_404(db_session, show_id)

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

    show = await get_show_or_404(db_session, show_id)

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

    show = await get_show_or_404(db_session, show_id)

    orchestrator = TMDBOrchestrator(db_session, tmdb)
    # User-triggered "sync now": bypass the TMDB response cache so a season
    # TMDB has since populated isn't masked by a stale cached response.
    await orchestrator.sync_show_episodes(show, bypass_cache=True)

    ep_stmt = (
        select(Episode)
        .where(Episode.show_id == show_id)
        .order_by(Episode.season_number, Episode.episode_number)
    )
    result = await db_session.execute(ep_stmt)
    return list(result.scalars().all())


@router.get("/{show_id}/episode-groups", response_model=list[EpisodeGroupSummary])
async def list_episode_groups(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> list[EpisodeGroupSummary]:
    """List TMDB alternate episode groupings available for a show.

    Always fetches fresh from TMDB (via the shared cache/rate-limiter in
    ``TMDBService``) rather than trusting ``show.episode_groups``, since this
    is a user-initiated "pick a group" action and that column may be stale
    or never populated.

    Args:
        show_id: Database primary key of the show.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        Available episode groups, each flagged with whether it's the show's
        current ``active_episode_group_id``.

    Raises:
        HTTPException: 404 if the show is not found. 422 if the show is a
            movie -- movies have no TMDB episode_groups.
    """
    show = await get_show_or_404(db_session, show_id)
    if show.media_type == "movie":
        raise HTTPException(status_code=422, detail="Movies have no TMDB episode_groups")

    groups = await fetch_episode_groups_list(tmdb, show.tmdb_id)
    return [
        EpisodeGroupSummary(
            id=g["id"],
            name=g.get("name", ""),
            type=g.get("type", 0),
            episode_count=g.get("episode_count", 0),
            group_count=g.get("group_count", 0),
            is_active=g["id"] == show.active_episode_group_id,
        )
        for g in groups
        if g.get("id")
    ]


@router.post("/{show_id}/episode-groups/{group_id}/apply", response_model=EpisodeGroupApplyResponse)
async def apply_episode_group(
    show_id: int,
    group_id: str,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
) -> EpisodeGroupApplyResponse:
    """Switch a show's episode catalog to a specific TMDB episode grouping.

    Destructive: replaces every Episode row for the show with the group's
    own episodes. See ``TMDBOrchestrator.apply_episode_group`` for the full
    contract, including how previously tracked episodes are preserved as
    ``OrphanedTrackingRecord`` entries for manual resolution.

    Args:
        show_id: Database primary key of the show.
        group_id: TMDB episode_group ID, from ``GET .../episode-groups``.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).

    Returns:
        The updated episode list plus counts of what changed.

    Raises:
        HTTPException: 404 if the show is not found. 422 if the show is a
            movie.
    """
    from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator

    show = await get_show_or_404(db_session, show_id)
    if show.media_type == "movie":
        raise HTTPException(status_code=422, detail="Movies have no TMDB episode_groups")

    orchestrator = TMDBOrchestrator(db_session, tmdb)
    try:
        apply_result = await orchestrator.apply_episode_group(show, group_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ep_stmt = (
        select(Episode)
        .where(Episode.show_id == show_id)
        .order_by(Episode.season_number, Episode.episode_number)
    )
    episodes = (await db_session.execute(ep_stmt)).scalars().all()
    return EpisodeGroupApplyResponse(
        episodes=[EpisodeList.model_validate(ep) for ep in episodes],
        episodes_added=apply_result.episodes_added,
        episodes_removed=apply_result.episodes_removed,
        orphaned_file_count=apply_result.orphaned_file_count,
        orphaned_watched_count=apply_result.orphaned_watched_count,
    )


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
    show = await get_show_or_404(db_session, show_id)

    sub = await ensure_rss_stub(db_session, show_id, show.title)
    await db_session.flush()
    await db_session.refresh(sub, ["feed", "show"])
    return sub
