"""Helpers shared by the RSS route modules."""

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.api.lookups import get_or_404
from jidou.models.rss import RssFeed, RssSubscription


async def get_feed_or_404(db_session: AsyncSession, feed_id: int) -> RssFeed:
    """Load a feed or raise 404."""
    return await get_or_404(db_session, RssFeed, RssFeed.id == feed_id, detail="RSS feed not found")


def sub_stmt() -> Select[tuple[RssSubscription]]:
    """Base select statement for subscriptions with eager-loaded relations."""
    return select(RssSubscription).options(
        selectinload(RssSubscription.feed),
        selectinload(RssSubscription.show),
    )
