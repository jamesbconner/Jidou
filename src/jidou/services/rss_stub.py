"""Shared logic for linking or creating an RSS subscription stub for a show."""

import logging

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.rss import RssSubscription

logger = logging.getLogger(__name__)

_FUZZY_THRESHOLD = 85


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
    title_lower = show_title.lower()
    best_match: RssSubscription | None = None
    best_score: float = 0
    ambiguous = False
    for sub in unlinked_subs:
        if sub.name.lower() == title_lower:
            best_match = sub
            ambiguous = False
            break
        score = fuzz.token_set_ratio(title_lower, sub.name.lower())
        if score >= _FUZZY_THRESHOLD:
            if score > best_score:
                best_score = score
                best_match = sub
                ambiguous = False
            elif score == best_score:
                ambiguous = True
    if best_match is not None and not ambiguous:
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
