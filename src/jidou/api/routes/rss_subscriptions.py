"""API routes for RSS subscriptions: CRUD, recommendations, bulk patch and regex tools."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.api.dependencies import get_llm_service
from jidou.api.lookups import get_or_404, get_show_or_404, one_or_404
from jidou.api.routes._rss_common import get_feed_or_404, sub_stmt
from jidou.database import get_session
from jidou.models.rss import RssSubscription
from jidou.models.show import Show
from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator
from jidou.schemas.rss_schema import (
    RssRegexSuggestion,
    RssRegexSuggestRequest,
    RssSubscriptionBulkPatchItem,
    RssSubscriptionCreate,
    RssSubscriptionRead,
    RssSubscriptionRecommendation,
    RssSubscriptionUpdate,
)
from jidou.services.llm_service import LLMService
from jidou.services.rss_config import (
    fill_missing_yarss2_defaults,
)
from jidou.services.rss_regex_suggestor import (
    RegexSuggestionError,
    RssRegexSuggestor,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rss", tags=["rss"])


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


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
    stmt = sub_stmt()
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
        await get_feed_or_404(db_session, payload.feed_id)

    if payload.show_id is not None:
        await get_show_or_404(db_session, payload.show_id)

    new_sub = RssSubscription(**payload.model_dump())
    new_sub.extra_config = fill_missing_yarss2_defaults(new_sub.extra_config)
    db_session.add(new_sub)
    await db_session.flush()
    fetch_stmt = sub_stmt().where(RssSubscription.id == new_sub.id)
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
        sub_stmt()
        .join(Show, RssSubscription.show_id == Show.id)
        .where(RssSubscription.active.is_(True))
        .where(Show.status.in_(_DEACTIVATE_STATUSES))
    )
    activate_stmt = (
        sub_stmt()
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

    stmt = sub_stmt().where(RssSubscription.id.in_(ids))
    subs = list((await db_session.execute(stmt)).scalars().all())

    for sub in subs:
        sub.active = active_by_id[sub.id]

    await db_session.flush()

    fetch_stmt = sub_stmt().where(RssSubscription.id.in_([s.id for s in subs]))
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
    sub = await one_or_404(
        db_session,
        sub_stmt().where(RssSubscription.id == sub_id),
        detail="RSS subscription not found",
    )
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
    sub = await one_or_404(
        db_session,
        sub_stmt().where(RssSubscription.id == sub_id),
        detail="RSS subscription not found",
    )

    if "feed_id" in payload.model_fields_set and payload.feed_id is not None:
        await get_feed_or_404(db_session, payload.feed_id)

    if "show_id" in payload.model_fields_set and payload.show_id is not None:
        await get_show_or_404(db_session, payload.show_id)

    for field in payload.model_fields_set:
        setattr(sub, field, getattr(payload, field))
    sub.extra_config = fill_missing_yarss2_defaults(sub.extra_config)

    await db_session.flush()
    fetch_stmt2 = sub_stmt().where(RssSubscription.id == sub_id)
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
    sub = await get_or_404(
        db_session,
        RssSubscription,
        RssSubscription.id == sub_id,
        detail="RSS subscription not found",
        for_update=True,
    )

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
    sub = await one_or_404(
        db_session,
        sub_stmt().where(RssSubscription.id == sub_id),
        detail="RSS subscription not found",
    )

    feed = sub.feed
    if body is not None and "feed_id" in body.model_fields_set:
        feed = None
        if body.feed_id is not None:
            feed = await get_feed_or_404(db_session, body.feed_id)

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
    sub = await one_or_404(db_session, stmt, detail="RSS subscription not found")

    return RssPublishOrchestrator.build_sub_dict(sub, sub.remote_key or "unassigned")
