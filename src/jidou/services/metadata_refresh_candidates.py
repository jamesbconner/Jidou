"""Load the facts the metadata refresh policy ranks shows by.

This is the I/O half of the policy in ``metadata_refresh_policy``: one query
that returns narrow tuples instead of full ``Show`` rows. The lookback filter
and the "latest season fully aired" signal run in SQL; ranking stays in Python
so each rule is written once.
"""

import logging
from datetime import date

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode
from jidou.models.rss import RssSubscription
from jidou.models.show import Show
from jidou.services.metadata_refresh_policy import RefreshPolicy, ShowRefreshFacts

logger = logging.getLogger(__name__)


def _parse_iso_date(raw: str | None) -> date | None:
    """Parse the leading ``YYYY-MM-DD`` of a stored TMDB date string.

    Args:
        raw: A stored date string, possibly empty or malformed.

    Returns:
        The date, or ``None`` if *raw* is empty or unparseable.
    """
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        logger.debug("Ignoring unparseable stored date %r", raw)
        return None


async def load_refresh_facts(
    session: AsyncSession, policy: RefreshPolicy
) -> list[ShowRefreshFacts]:
    """Load refresh facts for every show inside the policy's lookback window.

    Dates are compared as ISO strings (never cast in SQL), so a malformed
    stored value can't raise a cast error and abort the whole query.

    Args:
        session: Active async session.
        policy: Active policy; supplies "today" and the lookback cutoff.

    Returns:
        One :class:`ShowRefreshFacts` per show whose last air date is unknown
        or on/after the lookback cutoff.
    """
    today = policy.today
    last_air = func.coalesce(
        func.nullif(Show.last_air_date, ""), func.nullif(Show.release_date, "")
    )

    # Highest non-special season per show, then whether all of its episodes
    # have a known air date on or before today. Uses ix_episodes_show_season_episode.
    latest = (
        select(Episode.show_id, func.max(Episode.season_number).label("season"))
        .where(Episode.season_number > 0)
        .group_by(Episode.show_id)
        .subquery()
    )
    aired = (
        select(
            Episode.show_id,
            func.bool_and(and_(Episode.air_date.is_not(None), Episode.air_date <= today)).label(
                "fully_aired"
            ),
            func.max(Episode.air_date).label("season_last_air"),
        )
        .join(
            latest,
            and_(latest.c.show_id == Episode.show_id, Episode.season_number == latest.c.season),
        )
        .group_by(Episode.show_id)
        .subquery()
    )

    stmt = (
        select(
            Show.id,
            Show.title,
            Show.media_type,
            Show.status,
            Show.metadata_refreshed_at,
            Show.vote_count,
            # ->> yields SQL NULL for a missing key *and* for a JSON null literal.
            Show.next_episode_to_air["air_date"].as_string().label("next_air"),
            last_air.label("last_air"),
            aired.c.fully_aired,
            aired.c.season_last_air,
            exists().where(RssSubscription.show_id == Show.id).label("has_rss"),
        )
        .outerjoin(aired, aired.c.show_id == Show.id)
        .where(
            (last_air.is_(None)) | (last_air >= policy.lookback_cutoff().isoformat()),
        )
    )

    rows = (await session.execute(stmt)).all()
    return [
        ShowRefreshFacts(
            show_id=row.id,
            title=row.title,
            media_type=row.media_type,
            status=row.status,
            metadata_refreshed_at=row.metadata_refreshed_at,
            vote_count=row.vote_count or 0,
            next_air_date=_parse_iso_date(row.next_air),
            last_air_date=_parse_iso_date(row.last_air),
            latest_season_fully_aired=row.fully_aired,
            latest_season_last_air=row.season_last_air,
            has_rss_subscription=bool(row.has_rss),
        )
        for row in rows
    ]
