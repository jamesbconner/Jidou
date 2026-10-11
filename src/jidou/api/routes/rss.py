"""API routes for RSS feed and subscription management."""

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.api.dependencies import get_feed_fetch_service, get_llm_service
from jidou.api.routes.shows import get_tmdb
from jidou.config import settings
from jidou.database import get_session
from jidou.models.rss import RssConfigSnapshot, RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.models.task import BackgroundTask
from jidou.orchestrators.feed_onboarding_orchestrator import (
    FeedOnboardingError,
    FeedOnboardingOrchestrator,
)
from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator
from jidou.schemas.rss_schema import (
    FeedAddShowRequest,
    FeedAddShowResult,
    FeedEntriesRead,
    FeedEntryGroupRead,
    FeedRegexSuggestion,
    FeedRegexSuggestRequest,
    FeedRegexTestRequest,
    RegexMatchReportRead,
    RssConfigDiff,
    RssFeedCreate,
    RssFeedRead,
    RssFeedUpdate,
    RssRegexSuggestion,
    RssRegexSuggestRequest,
    RssShowBrief,
    RssSubscriptionBulkPatchItem,
    RssSubscriptionCreate,
    RssSubscriptionRead,
    RssSubscriptionRecommendation,
    RssSubscriptionUpdate,
)
from jidou.schemas.task_schema import TaskRead
from jidou.services.feed_entry_grouping import FeedEntryGroup, group_entries
from jidou.services.feed_fetch import FeedFetchError, FeedFetchService
from jidou.services.feed_subscription_match import SubscriptionMatcher, SubscriptionRule
from jidou.services.llm_service import LLMService
from jidou.services.progress import TaskDispatchError, enqueue_task
from jidou.services.rss_config import (
    diff_rss_config,
    fill_missing_yarss2_defaults,
    parse_rss_config,
)
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
    stmt = select(RssFeed).where(RssFeed.id == feed_id)
    feed = (await db_session.execute(stmt)).scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="RSS feed not found")

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
    stmt = select(RssFeed).where(RssFeed.id == feed_id).with_for_update()
    feed = (await db_session.execute(stmt)).scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="RSS feed not found")

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
    feed = (
        await db_session.execute(select(RssFeed).where(RssFeed.id == feed_id))
    ).scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="RSS feed not found")

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


async def _get_feed_or_404(db_session: AsyncSession, feed_id: int) -> RssFeed:
    """Load a feed or raise 404."""
    feed = (
        await db_session.execute(select(RssFeed).where(RssFeed.id == feed_id))
    ).scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="RSS feed not found")
    return feed


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
    feed = await _get_feed_or_404(db_session, feed_id)
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
    feed = await _get_feed_or_404(db_session, feed_id)
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
    feed = await _get_feed_or_404(db_session, feed_id)
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
                _sub_stmt().where(RssSubscription.id == outcome.subscription_id)
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


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


def _sub_stmt() -> Select[tuple[RssSubscription]]:
    """Base select statement for subscriptions with eager-loaded relations."""
    return select(RssSubscription).options(
        selectinload(RssSubscription.feed),
        selectinload(RssSubscription.show),
    )


@router.get("/subscriptions", response_model=list[RssSubscriptionRead])
async def list_subscriptions(
    show_id: int | None = None,
    feed_id: int | None = None,
    enabled_only: bool = False,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RssSubscription]:
    """List RSS subscriptions with optional filters.

    Args:
        show_id: Filter to subscriptions linked to this show.
        feed_id: Filter to subscriptions linked to this feed.
        enabled_only: When true, only return subscriptions with enabled_in_config=True.
        db_session: DB session (injected).

    Returns:
        List of RssSubscription records.
    """
    stmt = _sub_stmt()
    if show_id is not None:
        stmt = stmt.where(RssSubscription.show_id == show_id)
    if feed_id is not None:
        stmt = stmt.where(RssSubscription.feed_id == feed_id)
    if enabled_only:
        stmt = stmt.where(RssSubscription.enabled_in_config.is_(True))
    stmt = stmt.order_by(RssSubscription.name.asc())
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


@router.post("/subscriptions", response_model=RssSubscriptionRead, status_code=201)
async def create_subscription(
    payload: RssSubscriptionCreate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RssSubscription:
    """Create an RSS subscription.

    Args:
        payload: Subscription fields.
        db_session: DB session (injected).

    Returns:
        The created RssSubscription record.

    Raises:
        HTTPException: 404 if the referenced feed or show does not exist.
    """
    if payload.feed_id is not None:
        feed_exists = (
            await db_session.execute(select(RssFeed).where(RssFeed.id == payload.feed_id))
        ).scalar_one_or_none()
        if feed_exists is None:
            raise HTTPException(status_code=404, detail="RSS feed not found")

    if payload.show_id is not None:
        show_exists = (
            await db_session.execute(select(Show).where(Show.id == payload.show_id))
        ).scalar_one_or_none()
        if show_exists is None:
            raise HTTPException(status_code=404, detail="Show not found")

    new_sub = RssSubscription(**payload.model_dump())
    new_sub.extra_config = fill_missing_yarss2_defaults(new_sub.extra_config)
    db_session.add(new_sub)
    await db_session.flush()
    fetch_stmt = _sub_stmt().where(RssSubscription.id == new_sub.id)
    created = (await db_session.execute(fetch_stmt)).scalar_one()
    logger.info("Created RSS subscription id=%d name=%r", created.id, created.name)
    return created


_DEACTIVATE_STATUSES = frozenset({"Ended", "Cancelled"})
_ACTIVATE_STATUSES = frozenset({"Returning Series", "In Production"})


@router.get("/subscriptions/recommendations", response_model=list[RssSubscriptionRecommendation])
async def get_subscription_recommendations(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RssSubscriptionRecommendation]:
    """Return subscriptions with health-check recommendations.

    **Deactivate**: linked show's TMDB status is ``Ended`` or ``Cancelled``
    and the subscription is currently active.

    **Activate**: linked show's TMDB status is ``Returning Series`` or
    ``In Production`` and the subscription is currently inactive.

    Only subscriptions linked to a show are included; unlinked subscriptions
    have no TMDB signal and are excluded.

    Args:
        db_session: DB session (injected).

    Returns:
        List of subscriptions with a ``recommendation`` field.
    """
    deactivate_stmt = (
        _sub_stmt()
        .join(Show, RssSubscription.show_id == Show.id)
        .where(RssSubscription.active.is_(True))
        .where(Show.status.in_(_DEACTIVATE_STATUSES))
    )
    activate_stmt = (
        _sub_stmt()
        .join(Show, RssSubscription.show_id == Show.id)
        .where(RssSubscription.active.is_(False))
        .where(Show.status.in_(_ACTIVATE_STATUSES))
    )

    deactivate_subs = list((await db_session.execute(deactivate_stmt)).scalars().all())
    activate_subs = list((await db_session.execute(activate_stmt)).scalars().all())

    results: list[RssSubscriptionRecommendation] = []
    for sub in deactivate_subs:
        base = RssSubscriptionRead.model_validate(sub)
        results.append(
            RssSubscriptionRecommendation.model_validate(
                {**base.model_dump(), "recommendation": "deactivate"}
            )
        )
    for sub in activate_subs:
        base = RssSubscriptionRead.model_validate(sub)
        results.append(
            RssSubscriptionRecommendation.model_validate(
                {**base.model_dump(), "recommendation": "activate"}
            )
        )

    results.sort(key=lambda r: r.name.lower())
    logger.debug(
        "Subscription recommendations: %d deactivate, %d activate",
        len(deactivate_subs),
        len(activate_subs),
    )
    return results


@router.patch("/subscriptions/bulk", response_model=list[RssSubscriptionRead])
async def bulk_patch_subscriptions(
    payload: list[RssSubscriptionBulkPatchItem],
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RssSubscription]:
    """Apply active-flag changes to multiple subscriptions in one transaction.

    Used by the Recommendations tab to accept all suggested changes at once.
    Unknown IDs are silently skipped — the caller should treat the returned
    list as the source of truth for what was actually updated.

    Args:
        payload: List of ``{id, active}`` pairs.
        db_session: DB session (injected).

    Returns:
        List of updated RssSubscription records.
    """
    if not payload:
        return []

    ids = [item.id for item in payload]
    active_by_id = {item.id: item.active for item in payload}

    stmt = _sub_stmt().where(RssSubscription.id.in_(ids))
    subs = list((await db_session.execute(stmt)).scalars().all())

    for sub in subs:
        sub.active = active_by_id[sub.id]

    await db_session.flush()

    fetch_stmt = _sub_stmt().where(RssSubscription.id.in_([s.id for s in subs]))
    updated = list((await db_session.execute(fetch_stmt)).scalars().all())
    logger.info("Bulk-patched %d/%d subscriptions (active flags)", len(updated), len(ids))
    return updated


@router.get("/subscriptions/{sub_id}", response_model=RssSubscriptionRead)
async def get_subscription(
    sub_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RssSubscription:
    """Get a single RSS subscription by ID.

    Args:
        sub_id: Database primary key.
        db_session: DB session (injected).

    Returns:
        The matching RssSubscription record.

    Raises:
        HTTPException: 404 if the subscription is not found.
    """
    stmt = _sub_stmt().where(RssSubscription.id == sub_id)
    sub = (await db_session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="RSS subscription not found")
    return sub


@router.patch("/subscriptions/{sub_id}", response_model=RssSubscriptionRead)
async def update_subscription(
    sub_id: int,
    payload: RssSubscriptionUpdate,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RssSubscription:
    """Update an RSS subscription.

    Only fields explicitly present in the request body are changed.

    Args:
        sub_id: Database primary key.
        payload: Fields to update.
        db_session: DB session (injected).

    Returns:
        The updated RssSubscription record.

    Raises:
        HTTPException: 404 if the subscription is not found.
        HTTPException: 404 if the referenced feed does not exist.
    """
    stmt = _sub_stmt().where(RssSubscription.id == sub_id)
    sub = (await db_session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="RSS subscription not found")

    if "feed_id" in payload.model_fields_set and payload.feed_id is not None:
        feed_exists = (
            await db_session.execute(select(RssFeed).where(RssFeed.id == payload.feed_id))
        ).scalar_one_or_none()
        if feed_exists is None:
            raise HTTPException(status_code=404, detail="RSS feed not found")

    if "show_id" in payload.model_fields_set and payload.show_id is not None:
        show_exists = (
            await db_session.execute(select(Show).where(Show.id == payload.show_id))
        ).scalar_one_or_none()
        if show_exists is None:
            raise HTTPException(status_code=404, detail="Show not found")

    for field in payload.model_fields_set:
        setattr(sub, field, getattr(payload, field))
    sub.extra_config = fill_missing_yarss2_defaults(sub.extra_config)

    await db_session.flush()
    fetch_stmt2 = _sub_stmt().where(RssSubscription.id == sub_id)
    updated = (await db_session.execute(fetch_stmt2)).scalar_one()
    logger.info("Updated RSS subscription id=%d: %s", sub_id, payload.model_fields_set)
    return updated


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(
    sub_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Delete an RSS subscription.

    Refused if the subscription is currently enabled in the remote config
    (``enabled_in_config=True``) to prevent silent config divergence.
    Disable the subscription first before deleting.

    Args:
        sub_id: Database primary key.
        db_session: DB session (injected).

    Raises:
        HTTPException: 404 if the subscription is not found.
        HTTPException: 400 if the subscription is enabled in the remote config.
    """
    # Lock the row so a concurrent PATCH can't flip enabled_in_config after this check
    stmt = select(RssSubscription).where(RssSubscription.id == sub_id).with_for_update()
    sub = (await db_session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="RSS subscription not found")

    if sub.enabled_in_config:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot delete subscription while it is enabled in the remote config. "
                "Set enabled_in_config=false first."
            ),
        )

    await db_session.delete(sub)
    logger.info("Deleted RSS subscription id=%d name=%r", sub_id, sub.name)


@router.post("/subscriptions/{sub_id}/suggest-regex", response_model=RssRegexSuggestion)
async def suggest_regex(
    sub_id: int,
    body: RssRegexSuggestRequest | None = None,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
) -> RssRegexSuggestion:
    """Generate an LLM regex suggestion for an RSS subscription filter.

    Uses the subscription name (and linked show title if available) as the
    prompt context.  The LLM returns a compact JSON object with
    ``regex_include`` and ``regex_exclude`` patterns suitable for a
    BitTorrent RSS downloader.

    Args:
        sub_id: Database primary key of the subscription.
        body: Optional unsaved form state. A ``feed_id`` here selects the feed
            whose regex hints steer the prompt instead of the persisted one, so
            suggestions follow a feed changed in the edit modal but not yet saved.
            ``previous`` lists earlier suggestions; when present the LLM cache is
            bypassed and the model is told to differ.
        db_session: DB session (injected).
        llm: LLM service (injected).

    Returns:
        :class:`RssRegexSuggestion` with the suggested regex patterns.

    Raises:
        HTTPException: 404 if the subscription or the requested feed is not found.
        HTTPException: 422 if the LLM provider is not configured.
        HTTPException: 503 if the LLM call fails.
    """
    stmt = _sub_stmt().where(RssSubscription.id == sub_id)
    sub = (await db_session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="RSS subscription not found")

    feed = sub.feed
    if body is not None and "feed_id" in body.model_fields_set:
        feed = None
        if body.feed_id is not None:
            feed = (
                await db_session.execute(select(RssFeed).where(RssFeed.id == body.feed_id))
            ).scalar_one_or_none()
            if feed is None:
                raise HTTPException(status_code=404, detail="RSS feed not found")

    show_title = sub.show.title if sub.show else None
    try:
        suggestion = await RssRegexSuggestor(llm).suggest(
            label=show_title or sub.name,
            label_is_show=bool(show_title),
            feed=feed,
            previous=body.previous if body is not None else [],
            log_ref=f"sub_id={sub_id}",
        )
    except RegexSuggestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return RssRegexSuggestion(
        regex_include=suggestion.regex_include,
        regex_exclude=suggestion.regex_exclude,
        model=suggestion.model,
        cached=suggestion.cached,
    )


# ---------------------------------------------------------------------------
# Download (compose current DB state as a YaRSS2 config file)
# ---------------------------------------------------------------------------


@router.get("/download")
async def download_config(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Response:
    """Compose and download the current DB state as a YaRSS2 config file.

    Uses the latest stored snapshot for the header and non-managed sections,
    then overlays the current DB feeds and enabled subscriptions via
    :meth:`RssPublishOrchestrator.compose_config` — the same composition
    logic ``run()`` uses to build what it actually uploads, so this
    preview can't drift from real publish behavior. Does not upload to the
    remote server; ``upload=False`` computes subscription keys without
    persisting them.

    Args:
        db_session: DB session (injected).

    Returns:
        ``application/octet-stream`` response with ``yarss2.conf`` filename.

    Raises:
        HTTPException: 404 if no snapshot exists (run an import first).
        HTTPException: 500 if the latest snapshot cannot be parsed.
    """
    snapshot_stmt = select(RssConfigSnapshot).order_by(RssConfigSnapshot.created_at.desc()).limit(1)
    snapshot = (await db_session.execute(snapshot_stmt)).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(
            status_code=404, detail="No config snapshot found — run an import first"
        )

    try:
        header, old_body = parse_rss_config(snapshot.raw_content)
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to parse latest snapshot: {exc}"
        ) from exc

    orchestrator = RssPublishOrchestrator(db_session, None, "", dry_run=True)
    composed, _result = await orchestrator.compose_config(header, old_body, upload=False)

    return Response(
        content=composed.encode("utf-8"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="yarss2.conf"'},
    )


@router.get("/diff", response_model=RssConfigDiff)
async def diff_config(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RssConfigDiff:
    """Diff the current DB-composed config against the last stored snapshot.

    Answers "what would change if I published right now?" without touching
    the remote server. Composes the current DB state the same way
    :meth:`RssPublishOrchestrator.compose_config` (and therefore a real
    publish) would, then diffs it against the most recent snapshot — the
    last config Jidou actually saw on the remote server, whether from an
    explicit import, the pre-publish reconciliation step of a prior publish,
    or (most commonly) the ``post_publish`` snapshot :meth:`RssPublishOrchestrator.run`
    stores of exactly what it just uploaded.

    Args:
        db_session: DB session (injected).

    Returns:
        :class:`RssConfigDiff` with unified diff lines and a reference to
        the snapshot the diff was taken against.

    Raises:
        HTTPException: 404 if no snapshot exists (run an import first).
        HTTPException: 500 if the latest snapshot cannot be parsed.
    """
    snapshot_stmt = select(RssConfigSnapshot).order_by(RssConfigSnapshot.created_at.desc()).limit(1)
    snapshot = (await db_session.execute(snapshot_stmt)).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(
            status_code=404, detail="No config snapshot found — run an import first"
        )

    try:
        header, old_body = parse_rss_config(snapshot.raw_content)
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to parse latest snapshot: {exc}"
        ) from exc

    orchestrator = RssPublishOrchestrator(db_session, None, "", dry_run=True)
    composed, _result = await orchestrator.compose_config(header, old_body, upload=False)
    new_header, new_body = parse_rss_config(composed)

    diff_lines = diff_rss_config(header, old_body, new_header, new_body)

    return RssConfigDiff(
        snapshot_id=snapshot.id,
        snapshot_type=snapshot.snapshot_type,
        snapshot_created_at=snapshot.created_at,
        has_changes=bool(diff_lines),
        diff=diff_lines,
    )


@router.get("/subscriptions/{sub_id}/preview")
async def preview_subscription(
    sub_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    """Preview the YaRSS2 subscription dict Jidou would publish for one subscription.

    Uses the same :meth:`RssPublishOrchestrator.build_sub_dict` publish
    itself calls, so the preview always reflects real publish output —
    including YaRSS2 torrent-option defaults for a subscription that has
    never round-tripped through a real config.

    Args:
        sub_id: Database primary key of the subscription to preview.
        db_session: DB session (injected).

    Returns:
        The composed YaRSS2 subscription dict.

    Raises:
        HTTPException: 404 if the subscription is not found.
    """
    stmt = (
        select(RssSubscription)
        .where(RssSubscription.id == sub_id)
        .options(selectinload(RssSubscription.feed))
    )
    sub = (await db_session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="RSS subscription not found")

    return RssPublishOrchestrator.build_sub_dict(sub, sub.remote_key or "unassigned")


# ---------------------------------------------------------------------------
# Snapshots (read-only)
# ---------------------------------------------------------------------------


@router.get("/snapshots", response_model=list[dict[str, object]])
async def list_snapshots(
    limit: int = 20,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    """Return recent RSS config snapshots (most recent first).

    Args:
        limit: Maximum records to return (default 20).
        db_session: DB session (injected).

    Returns:
        List of snapshot summaries (id, snapshot_type, created_at, content length).
    """
    stmt = (
        select(
            RssConfigSnapshot.id,
            RssConfigSnapshot.snapshot_type,
            RssConfigSnapshot.created_at,
            func.length(RssConfigSnapshot.raw_content).label("content_length"),
        )
        .order_by(RssConfigSnapshot.created_at.desc())
        .limit(limit)
    )
    rows = (await db_session.execute(stmt)).all()
    return [
        {
            "id": row.id,
            "snapshot_type": row.snapshot_type,
            "created_at": row.created_at,
            "content_length": row.content_length,
        }
        for row in rows
    ]


@router.get("/snapshots/{snapshot_id}", response_model=dict[str, object])
async def get_snapshot(
    snapshot_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    """Return a single RSS config snapshot including its full raw content.

    The listing endpoint omits raw_content; use this to retrieve the actual
    config text for a specific import or pre-publish snapshot.

    Args:
        snapshot_id: Database primary key.
        db_session: DB session (injected).

    Returns:
        Snapshot record including raw_content.

    Raises:
        HTTPException: 404 if the snapshot is not found.
    """
    stmt = select(RssConfigSnapshot).where(RssConfigSnapshot.id == snapshot_id)
    snapshot = (await db_session.execute(stmt)).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {
        "id": snapshot.id,
        "snapshot_type": snapshot.snapshot_type,
        "created_at": snapshot.created_at,
        "raw_content": snapshot.raw_content,
    }


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


@router.post("/import", response_model=TaskRead, status_code=202)
async def trigger_rss_import(
    dry_run: bool = False,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Download the remote YaRSS2 config and sync it into the database.

    Requires ``RSS_CONFIG_REMOTE_PATH`` to be configured.  Progress is
    streamed over WebSocket (``/ws``) using the returned task ID.

    Args:
        dry_run: Parse and reconcile without writing to the database.
        db_session: DB session (injected).

    Returns:
        Background task record for polling or WebSocket tracking.

    Raises:
        HTTPException: 422 if ``RSS_CONFIG_REMOTE_PATH`` is not configured.
        HTTPException: 503 if the Celery broker is unreachable.
    """
    if not settings.rss_config_remote_path:
        raise HTTPException(
            status_code=422,
            detail="RSS_CONFIG_REMOTE_PATH is not configured.",
        )

    task_id = str(uuid.uuid4())

    def _dispatch() -> None:
        # Delayed import avoids circular references with the Celery app, and
        # keeps a failure here (e.g. a broken worker module) inside
        # enqueue_task's failure handling rather than surfacing unhandled.
        from jidou.workers.rss_tasks import rss_import_task

        rss_import_task.apply_async(args=[dry_run], task_id=task_id)

    try:
        new_task = await enqueue_task(db_session, task_id, "rss_import", _dispatch, dry_run=dry_run)
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc

    logger.info("Enqueued RSS import task %s (dry_run=%s)", task_id, dry_run)
    return new_task


@router.post("/publish", response_model=TaskRead, status_code=202)
async def trigger_rss_publish(
    dry_run: bool = False,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Compose and upload the Jidou DB state back to the remote YaRSS2 config.

    Requires ``RSS_CONFIG_REMOTE_PATH`` to be configured.  Backs up the current
    remote file, reconciles out-of-band changes, then uploads the composed config.
    Progress is streamed over WebSocket (``/ws``) using the returned task ID.

    Args:
        dry_run: Plan the publish without uploading to the remote server.
        db_session: DB session (injected).

    Returns:
        Background task record for polling or WebSocket tracking.

    Raises:
        HTTPException: 422 if ``RSS_CONFIG_REMOTE_PATH`` is not configured.
        HTTPException: 503 if the Celery broker is unreachable.
    """
    if not settings.rss_config_remote_path:
        raise HTTPException(
            status_code=422,
            detail="RSS_CONFIG_REMOTE_PATH is not configured.",
        )

    task_id = str(uuid.uuid4())

    def _dispatch() -> None:
        # Delayed import avoids circular references with the Celery app, and
        # keeps a failure here (e.g. a broken worker module) inside
        # enqueue_task's failure handling rather than surfacing unhandled.
        from jidou.workers.rss_tasks import rss_publish_task

        rss_publish_task.apply_async(args=[dry_run], task_id=task_id)

    try:
        new_task = await enqueue_task(
            db_session, task_id, "rss_publish", _dispatch, dry_run=dry_run
        )
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc

    logger.info("Enqueued RSS publish task %s (dry_run=%s)", task_id, dry_run)
    return new_task
