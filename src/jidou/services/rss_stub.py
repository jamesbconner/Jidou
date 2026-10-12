"""Shared logic for linking or creating an RSS subscription stub for a show."""

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.rss import RssSubscription
from jidou.services.fuzzy_match import unambiguous_title_match
from jidou.services.rss_config import fill_missing_yarss2_defaults

logger = logging.getLogger(__name__)


def pick_unlinked_subscription(
    subs: Sequence[RssSubscription], show_title: str
) -> RssSubscription | None:
    """Choose the unlinked subscription that best matches *show_title*.

    A single exact case-insensitive name match wins, even when it comes after a
    higher-scoring fuzzy match. Two or more exact matches are ambiguous. With no
    exact match the best token-set ratio at or above the threshold wins, unless
    two subscriptions tie at that best score. In every ambiguous case linking
    either would be a guess, so the caller creates a stub instead.

    Args:
        subs: Candidate subscriptions (those with no linked show).
        show_title: Title to match against each subscription's name.

    Returns:
        The matching subscription, or None when nothing qualifies or the best
        match (exact or fuzzy) is shared by more than one subscription.
    """
    index = unambiguous_title_match(show_title, [sub.name for sub in subs])
    return None if index is None else subs[index]


async def ensure_rss_stub(session: AsyncSession, show_id: int, show_title: str) -> RssSubscription:
    """Link an existing unlinked subscription or create a stub for show_id.

    Resolution order:
    1. An existing subscription already linked to this show_id — return it
       (most recently created, if more than one somehow exists).
    2. An unlinked subscription (show_id IS NULL) whose name matches show_title
       case-insensitively or with token-set ratio ≥ 85 — link and return it.
    3. No match — create and return a new inactive stub.

    The savepoint on stub insertion prevents a concurrent-insert IntegrityError
    from rolling back the enclosing transaction.

    Args:
        session: Active async SQLAlchemy session.
        show_id: ID of the show to link.
        show_title: Title used to find a matching unlinked subscription.

    Returns:
        The linked or newly created RssSubscription.
    """
    # Step 1: already linked
    stmt = (
        select(RssSubscription)
        .where(RssSubscription.show_id == show_id)
        .order_by(RssSubscription.created_at.desc())
        .limit(1)
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    # Step 2: find an unlinked subscription and link it
    unlinked_stmt = select(RssSubscription).where(RssSubscription.show_id.is_(None))
    unlinked_subs = list((await session.execute(unlinked_stmt)).scalars().all())
    best_match = pick_unlinked_subscription(unlinked_subs, show_title)
    if best_match is not None:
        best_match.show_id = show_id
        logger.debug(
            "Linked unlinked RSS subscription id=%d name=%r to show_id=%d title=%r",
            best_match.id,
            best_match.name,
            show_id,
            show_title,
        )
        return best_match

    # Step 3: create stub
    stub = RssSubscription(
        show_id=show_id,
        name=show_title,
        enabled_in_config=False,
        active=False,
        extra_config=fill_missing_yarss2_defaults(None),
    )
    session.add(stub)
    try:
        async with session.begin_nested():
            await session.flush()
        logger.debug("Created RSS subscription stub for show_id=%d name=%r", show_id, show_title)
        return stub
    except IntegrityError:
        # Expunge the stub so it is not in session.new when get_session commits.
        # Without this, SQLAlchemy would re-flush the pending object on commit,
        # hit the unique index again, and roll back the entire outer transaction.
        session.expunge(stub)
        logger.debug("RSS stub for show_id=%d already exists (concurrent insert ignored)", show_id)
        # A concurrent request created it first — fetch and return that one.
        concurrent = (await session.execute(stmt)).scalar_one()
        return concurrent
