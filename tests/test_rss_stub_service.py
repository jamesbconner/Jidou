"""Tests for jidou.services.rss_stub.ensure_rss_stub.

The link-to-existing-subscription and fuzzy-match-unlinked-subscription
paths are already covered indirectly via tests/test_watchlist_routes.py
(the original call sites, before this logic was extracted into a shared
service). This file focuses on the stub-creation path's newer behavior:
backfilling YaRSS2's default torrent-option keys into extra_config.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.rss import RssSubscription
from jidou.services.rss_config import YARSS2_SUBSCRIPTION_DEFAULTS
from jidou.services.rss_stub import ensure_rss_stub, pick_unlinked_subscription


def _make_begin_nested() -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=None)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


@pytest.mark.asyncio
async def test_create_stub_backfills_yarss2_defaults() -> None:
    """A newly created stub (no existing/unlinked subscription to reuse) gets
    every YaRSS2 default torrent-option key set on extra_config immediately,
    not just at publish time.
    """
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    no_unlinked = MagicMock()
    no_unlinked.scalars.return_value.all.return_value = []

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[no_existing, no_unlinked])
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.begin_nested = _make_begin_nested()

    stub = await ensure_rss_stub(session, show_id=1, show_title="Some Show")

    assert stub.extra_config is not None
    for field, default in YARSS2_SUBSCRIPTION_DEFAULTS.items():
        assert stub.extra_config[field] == default
    session.add.assert_called_once_with(stub)


def _subs(*names: str) -> list[RssSubscription]:
    return [RssSubscription(name=n) for n in names]


def test_pick_exact_name_wins_even_after_a_higher_scoring_fuzzy_match() -> None:
    subs = _subs("Example Show Extra", "example show")  # fuzzy 100 (subset) first, exact second

    assert pick_unlinked_subscription(subs, "Example Show") is subs[1]


def test_pick_tie_at_best_fuzzy_score_is_ambiguous() -> None:
    subs = _subs("Example Show A", "Example Show B")

    assert pick_unlinked_subscription(subs, "Example Show") is None


def test_pick_best_score_below_threshold_is_none() -> None:
    assert pick_unlinked_subscription(_subs("Completely Different"), "Example Show") is None


def test_pick_unique_best_fuzzy_match_is_returned() -> None:
    subs = _subs("Unrelated", "Example Show 2026")

    assert pick_unlinked_subscription(subs, "Example Show") is subs[1]


def test_pick_empty_candidates_is_none() -> None:
    assert pick_unlinked_subscription([], "Example Show") is None
