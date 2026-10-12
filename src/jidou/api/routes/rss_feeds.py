"""API routes for RSS feeds: CRUD, entry browsing, regex tools and show onboarding."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.api.dependencies import get_feed_fetch_service, get_llm_service, get_tmdb
from jidou.api.lookups import get_or_404
from jidou.api.routes._rss_common import get_feed_or_404, sub_stmt
from jidou.database import get_session
from jidou.models.rss import RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.orchestrators.feed_onboarding_orchestrator import (
    FeedOnboardingError,
    FeedOnboardingOrchestrator,
)
from jidou.schemas.rss_schema import (
    FeedAddShowRequest,
    FeedAddShowResult,
    FeedEntriesRead,
    FeedEntryGroupRead,
    FeedRegexSuggestion,
    FeedRegexSuggestRequest,
    FeedRegexTestRequest,
    RegexMatchReportRead,
    RssFeedCreate,
    RssFeedRead,
    RssFeedUpdate,
    RssShowBrief,
    RssSubscriptionRead,
)
from jidou.services.feed_entry_grouping import FeedEntryGroup, group_entries
from jidou.services.feed_fetch import FeedFetchError, FeedFetchService
from jidou.services.feed_subscription_match import SubscriptionMatcher, SubscriptionRule
from jidou.services.llm_service import LLMService
from jidou.services.rss_regex_matching import evaluate_regex
from jidou.services.rss_regex_suggestor import (
    MAX_PROMPT_TITLES,
    RegexSuggestionError,
    RssRegexSuggestor,
)
from jidou.services.show_lookup import find_show_by_name
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rss", tags=["rss"])


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------


@router.get("/feeds", response_model=list[RssFeedRead])
async def list_feeds(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RssFeed]:
    """Return all RSS feeds ordered by name.

    Args:
        db_session: DB session (injected).

    Returns:
        List of RssFeed records.
    """
    stmt = select(RssFeed).order_by(RssFeed.name.asc())
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


@router.post("/feeds", response_model=RssFeedRead, status_code=201)
async def create_feed(
    payload: RssFeedCreate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RssFeed:
    """Create an RSS feed record.

    Args:
        payload: Feed fields.
        db_session: DB session (injected).

    Returns:
        The created RssFeed record.
    """
    feed = RssFeed(**payload.model_dump())
    db_session.add(feed)
    await db_session.flush()
    await db_session.refresh(feed)
    logger.info("Created RSS feed id=%d name=%r", feed.id, feed.name)
    return feed


@router.patch("/feeds/{feed_id}", response_model=RssFeedRead)
async def update_feed(
    feed_id: int,
    payload: RssFeedUpdate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RssFeed:
    """Update an RSS feed.

    Only fields explicitly present in the request body are changed.

    Args:
        feed_id: Database primary key.
        payload: Fields to update.
        db_session: DB session (injected).

    Returns:
        The updated RssFeed record.

    Raises:
        HTTPException: 404 if the feed is not found.
    """
    feed = await get_feed_or_404(db_session, feed_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(feed, field, value)

    await db_session.flush()
    await db_session.refresh(feed)
    logger.info("Updated RSS feed id=%d: %s", feed_id, payload.model_fields_set)
    return feed


@router.delete("/feeds/{feed_id}", status_code=204)
async def delete_feed(
    feed_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Delete an RSS feed.

    Refused if any subscription references this feed (subscription must be
    unlinked first to avoid accidental orphaning).

    Args:
        feed_id: Database primary key.
        db_session: DB session (injected).

    Raises:
        HTTPException: 404 if the feed is not found.
        HTTPException: 400 if subscriptions reference the feed.
    """
    # Lock the feed row first so no subscription can attach between the guard check and delete
    feed = await get_or_404(
        db_session,
        RssFeed,
        RssFeed.id == feed_id,
        detail="RSS feed not found",
        for_update=True,
    )

    sub_count_stmt = select(RssSubscription).where(RssSubscription.feed_id == feed_id).limit(1)
    has_subs = (await db_session.execute(sub_count_stmt)).scalar_one_or_none() is not None
    if has_subs:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete feed: subscriptions still reference it. Unlink them first.",
        )

    await db_session.delete(feed)
    logger.info("Deleted RSS feed id=%d name=%r", feed_id, feed.name)


@router.get("/feeds/{feed_id}/entries", response_model=FeedEntriesRead)
async def browse_feed_entries(
    feed_id: int,
    refresh: bool = False,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    fetcher: FeedFetchService = Depends(get_feed_fetch_service),  # noqa: B008
) -> FeedEntriesRead:
    """Fetch a feed's current entries, grouped by parsed show name.

    Read-only: nothing is persisted. Each group is annotated with the library
    show whose alias/title exactly matches the parsed name, and with any active
    subscription on this feed that already covers it: one whose include/exclude
    regexes match the group's titles, or failing that one linked to that show.

    Args:
        feed_id: Database primary key of the feed.
        refresh: Bypass the short-lived entry cache and refetch.
        db_session: DB session (injected).
        fetcher: Feed fetch service (injected).

    Returns:
        Entries grouped by show name.

    Raises:
        HTTPException: 404 if the feed is not found; 502 if the feed cannot be
            fetched or is not a feed; 504 if the fetch timed out.
    """
    feed = await get_feed_or_404(db_session, feed_id)

    try:
        result = await fetcher.fetch_entries(feed.url, bypass_cache=refresh)
    except FeedFetchError as exc:
        status = 504 if exc.timed_out else 502
        raise HTTPException(status_code=status, detail=str(exc)) from None

    groups = group_entries(result.entries)

    shows: dict[int, Show] = {}
    show_by_group: dict[int, int] = {}
    for idx, group in enumerate(groups):
        if not group.parsed_name:
            continue
        show = await find_show_by_name(db_session, group.parsed_name)
        if show is not None:
            shows[show.id] = show
            show_by_group[idx] = show.id

    # Only subscriptions that are actually published and active count: stubs and
    # disabled rules will not download anything.
    sub_rows = await db_session.execute(
        select(
            RssSubscription.id,
            RssSubscription.show_id,
            RssSubscription.regex_include,
            RssSubscription.regex_exclude,
            RssSubscription.regex_include_ignorecase,
            RssSubscription.regex_exclude_ignorecase,
        ).where(
            RssSubscription.feed_id == feed_id,
            RssSubscription.active.is_(True),
            RssSubscription.enabled_in_config.is_(True),
        )
    )
    matcher = SubscriptionMatcher([SubscriptionRule(*row) for row in sub_rows.all()])
    sub_by_group = {
        idx: matcher.find(g.titles, show_id=show_by_group.get(idx)) for idx, g in enumerate(groups)
    }

    return FeedEntriesRead(
        feed_id=feed_id,
        total_entries=len(result.entries),
        truncated=result.truncated,
        malformed=result.malformed,
        cached=result.cached,
        groups=[
            FeedEntryGroupRead(
                parsed_name=g.parsed_name,
                entry_count=g.entry_count,
                season_min=g.season_min,
                season_max=g.season_max,
                episode_min=g.episode_min,
                episode_max=g.episode_max,
                sample_titles=g.sample_titles,
                library_show=(
                    RssShowBrief.model_validate(shows[show_by_group[idx]])
                    if idx in show_by_group
                    else None
                ),
                existing_subscription_id=sub_by_group[idx],
            )
            for idx, g in enumerate(groups)
        ],
    )


async def _feed_group_or_http_error(
    fetcher: FeedFetchService, feed: RssFeed, parsed_name: str
) -> FeedEntryGroup:
    """Re-read a feed (cache-first) and return the group named *parsed_name*.

    Raises:
        HTTPException: 502/504 if the feed cannot be fetched; 404 if the feed
            no longer contains a group of that name (entries roll off).
    """
    try:
        result = await fetcher.fetch_entries(feed.url)
    except FeedFetchError as exc:
        raise HTTPException(status_code=504 if exc.timed_out else 502, detail=str(exc)) from None
    wanted = " ".join(parsed_name.split()).casefold()
    for group in group_entries(result.entries):
        if group.parsed_name and group.parsed_name.casefold() == wanted:
            return group
    raise HTTPException(
        status_code=404,
        detail="That show is no longer in the feed's current entries. Refresh and try again.",
    )


def _match_report_read(
    report_matched: list[str], report_unmatched: list[str]
) -> RegexMatchReportRead:
    return RegexMatchReportRead(
        matched_titles=report_matched,
        unmatched_titles=report_unmatched,
        total=len(report_matched) + len(report_unmatched),
    )


@router.post("/feeds/{feed_id}/suggest-regex", response_model=FeedRegexSuggestion)
async def suggest_feed_group_regex(
    feed_id: int,
    body: FeedRegexSuggestRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
    fetcher: FeedFetchService = Depends(get_feed_fetch_service),  # noqa: B008
) -> FeedRegexSuggestion:
    """Suggest a filter for a feed group that has no subscription yet.

    The model is shown the group's real release titles (re-read from the feed,
    cache-first) so the pattern follows how the feed actually spells the show,
    and the response reports which of those titles the suggestion selects.

    Args:
        feed_id: Feed the group belongs to.
        body: Group key, optional picked show title, and prior suggestions.
        db_session: DB session (injected).
        llm: LLM service (injected).
        fetcher: Feed fetch service (injected).

    Returns:
        The suggestion plus a match report over the group's current titles.

    Raises:
        HTTPException: 404 unknown feed or group no longer in the feed; 422 LLM
            not configured; 502/504 feed fetch failed; 503 LLM call failed.
    """
    feed = await get_feed_or_404(db_session, feed_id)
    if not llm.is_available():
        # Checked before the network fetch so an unconfigured LLM fails fast.
        raise HTTPException(
            status_code=422,
            detail="LLM provider is not configured (set LLM_PROVIDER and LLM_MODEL).",
        )
    group = await _feed_group_or_http_error(fetcher, feed, body.parsed_name)

    try:
        suggestion = await RssRegexSuggestor(llm).suggest(
            label=body.show_title or group.parsed_name or body.parsed_name,
            label_is_show=True,
            feed=feed,
            previous=body.previous,
            titles=group.titles[:MAX_PROMPT_TITLES],
            log_ref=f"feed_id={feed_id}",
        )
    except RegexSuggestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # The model's pattern is compile-checked by the suggestor; the exclude hint
    # may be an arbitrary stored string, so guard the evaluation too.
    try:
        report = evaluate_regex(
            group.titles, include=suggestion.regex_include, exclude=suggestion.regex_exclude
        )
    except re.error:
        raise HTTPException(
            status_code=503, detail="Suggested filter contains an invalid regex."
        ) from None
    return FeedRegexSuggestion(
        regex_include=suggestion.regex_include,
        regex_exclude=suggestion.regex_exclude,
        model=suggestion.model,
        cached=suggestion.cached,
        match=_match_report_read(report.matched, report.unmatched),
    )


@router.post("/feeds/{feed_id}/test-regex", response_model=RegexMatchReportRead)
async def test_feed_group_regex(
    feed_id: int,
    body: FeedRegexTestRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    fetcher: FeedFetchService = Depends(get_feed_fetch_service),  # noqa: B008
) -> RegexMatchReportRead:
    """Preview which of a feed group's current titles a filter would select.

    Read-only and LLM-free; used while a user edits a suggested filter.

    Args:
        feed_id: Feed the group belongs to.
        body: Group key and the include/exclude patterns with their flags.
        db_session: DB session (injected).
        fetcher: Feed fetch service (injected).

    Returns:
        Matched and unmatched titles.

    Raises:
        HTTPException: 404 unknown feed or group no longer in the feed; 422
            invalid regex; 502/504 feed fetch failed.
    """
    feed = await get_feed_or_404(db_session, feed_id)
    group = await _feed_group_or_http_error(fetcher, feed, body.parsed_name)
    report = evaluate_regex(
        group.titles,
        include=body.regex_include,
        exclude=body.regex_exclude,
        include_ignorecase=body.regex_include_ignorecase,
        exclude_ignorecase=body.regex_exclude_ignorecase,
    )
    return _match_report_read(report.matched, report.unmatched)


@router.post("/feeds/{feed_id}/add-show", response_model=FeedAddShowResult)
async def add_show_from_feed(
    feed_id: int,
    body: FeedAddShowRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    tmdb: TMDBService = Depends(get_tmdb),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
) -> FeedAddShowResult:
    """Add a show to the library and subscribe it to this feed in one step.

    Resolves or creates the show, teaches the group's parsed name as an alias,
    and creates the feed subscription (or links an unlinked stub left by an
    import). Idempotent: a subscription already linking the show to this feed
    is returned unchanged. Nothing is published to YaRSS2.

    Args:
        feed_id: Feed the group came from.
        body: The group key, the show to use or add, and the filter.
        db_session: DB session (injected).
        tmdb: TMDB service (injected).
        llm: LLM service (injected).

    Returns:
        What was done, or with ``dry_run`` what would be done.

    Raises:
        HTTPException: 404 if the feed or ``show_id`` does not exist.
    """
    feed = await get_feed_or_404(db_session, feed_id)
    try:
        outcome = await FeedOnboardingOrchestrator(db_session, tmdb, llm).add_show_from_feed(
            feed, body
        )
    except FeedOnboardingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    subscription: RssSubscription | None = None
    if outcome.subscription_id is not None:
        subscription = (
            await db_session.execute(
                sub_stmt().where(RssSubscription.id == outcome.subscription_id)
            )
        ).scalar_one()
    return FeedAddShowResult(
        show=RssShowBrief.model_validate(outcome.show) if outcome.show is not None else None,
        show_created=outcome.show_created,
        subscription=RssSubscriptionRead.model_validate(subscription) if subscription else None,
        subscription_created=outcome.subscription_created,
        adopted_stub=outcome.adopted_stub,
        alias_added=outcome.alias_added,
        dry_run=outcome.dry_run,
    )
