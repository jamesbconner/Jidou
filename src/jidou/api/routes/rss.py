"""API routes for RSS feed and subscription management."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.database import get_session
from jidou.models.rss import RssConfigSnapshot, RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.schemas.rss_schema import (
    RssFeedCreate,
    RssFeedRead,
    RssFeedUpdate,
    RssSubscriptionCreate,
    RssSubscriptionRead,
    RssSubscriptionUpdate,
)

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

    for field in payload.model_fields_set:
        setattr(feed, field, getattr(payload, field))

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
    db_session.add(new_sub)
    await db_session.flush()
    fetch_stmt = _sub_stmt().where(RssSubscription.id == new_sub.id)
    created = (await db_session.execute(fetch_stmt)).scalar_one()
    logger.info("Created RSS subscription id=%d name=%r", created.id, created.name)
    return created


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
