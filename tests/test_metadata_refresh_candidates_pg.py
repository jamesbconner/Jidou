"""Refresh-candidate facts query against a real PostgreSQL.

Skipped unless ``JIDOU_TEST_PG_URL`` names an asyncpg URL of a throwaway
database already migrated to ``alembic upgrade head`` (the query relies on
JSONB ``->>`` and ``bool_and``). Every test runs in one outer transaction that
is rolled back afterwards.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from jidou.models.episode import Episode
from jidou.models.rss import RssSubscription
from jidou.models.show import Show
from jidou.services.metadata_refresh_candidates import load_refresh_facts
from jidou.services.metadata_refresh_policy import RefreshPolicy

_PG_URL = os.environ.get("JIDOU_TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not _PG_URL,
    reason="JIDOU_TEST_PG_URL is not set (needs a throwaway PostgreSQL migrated to head)",
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a session whose work is rolled back when the test ends."""
    assert _PG_URL is not None
    engine = create_async_engine(_PG_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        db = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield db
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


def _policy() -> RefreshPolicy:
    return RefreshPolicy.from_settings(NOW)


async def _show(db: AsyncSession, tmdb_id: int, **fields: object) -> Show:
    fields.setdefault("media_type", "tv")
    show = Show(tmdb_id=tmdb_id, title=f"Show {tmdb_id}", **fields)
    db.add(show)
    await db.flush()
    return show


async def _episode(db: AsyncSession, show: Show, n: int, season: int, air: date | None) -> None:
    db.add(
        Episode(
            show_id=show.id,
            tmdb_id=show.tmdb_id * 1000 + season * 100 + n,
            season_number=season,
            episode_number=n,
            name=f"E{n}",
            air_date=air,
        )
    )
    await db.flush()


async def test_fully_aired_signal_uses_only_the_latest_season(session: AsyncSession) -> None:
    show = await _show(session, 990201)
    await _episode(session, show, 1, 1, TODAY - timedelta(days=90))
    await _episode(session, show, 1, 2, TODAY - timedelta(days=10))
    await _episode(session, show, 2, 2, TODAY + timedelta(days=7))

    facts = {f.show_id: f for f in await load_refresh_facts(session, _policy())}

    assert facts[show.id].latest_season_fully_aired is False
    assert facts[show.id].latest_season_last_air == TODAY + timedelta(days=7)


async def test_fully_aired_true_and_none_without_episodes(session: AsyncSession) -> None:
    done = await _show(session, 990202)
    await _episode(session, done, 1, 1, TODAY - timedelta(days=5))
    bare = await _show(session, 990203)

    facts = {f.show_id: f for f in await load_refresh_facts(session, _policy())}

    assert facts[done.id].latest_season_fully_aired is True
    assert facts[done.id].latest_season_last_air == TODAY - timedelta(days=5)
    assert facts[bare.id].latest_season_fully_aired is None
    assert facts[bare.id].latest_season_last_air is None


async def test_json_null_and_missing_next_episode_are_none(session: AsyncSession) -> None:
    missing = await _show(session, 990204)
    with_next = await _show(
        session, 990205, next_episode_to_air={"air_date": "2026-09-01", "episode_number": 4}
    )

    facts = {f.show_id: f for f in await load_refresh_facts(session, _policy())}

    assert facts[missing.id].next_air_date is None
    assert facts[with_next.id].next_air_date == date(2026, 9, 1)


async def test_lookback_filters_old_shows_and_falls_back_to_release_date(
    session: AsyncSession,
) -> None:
    old = await _show(session, 990206, last_air_date="2015-01-01")
    recent_movie = await _show(
        session, 990207, media_type="movie", last_air_date=None, release_date="2026-01-01"
    )
    old_movie = await _show(
        session, 990208, media_type="movie", last_air_date="", release_date="2010-01-01"
    )
    unknown = await _show(session, 990209)

    ids = {f.show_id for f in await load_refresh_facts(session, _policy())}

    assert old.id not in ids
    assert old_movie.id not in ids
    assert recent_movie.id in ids
    assert unknown.id in ids


async def test_malformed_stored_date_does_not_break_the_query(session: AsyncSession) -> None:
    bad = await _show(session, 990210, last_air_date="2026-13-45")

    facts = {f.show_id: f for f in await load_refresh_facts(session, _policy())}

    assert facts[bad.id].last_air_date is None


async def test_has_rss_subscription_flag(session: AsyncSession) -> None:
    subscribed = await _show(session, 990211)
    plain = await _show(session, 990212)
    session.add(RssSubscription(name="sub", show_id=subscribed.id))
    await session.flush()

    facts = {f.show_id: f for f in await load_refresh_facts(session, _policy())}

    assert facts[subscribed.id].has_rss_subscription is True
    assert facts[plain.id].has_rss_subscription is False
