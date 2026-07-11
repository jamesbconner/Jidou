"""Tests for jidou.services.rss_stub.ensure_rss_stub.

The link-to-existing-subscription and fuzzy-match-unlinked-subscription
paths are already covered indirectly via tests/test_watchlist_routes.py
(the original call sites, before this logic was extracted into a shared
service). This file focuses on the stub-creation path's newer behavior:
backfilling YaRSS2's default torrent-option keys into extra_config.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.services.rss_config import YARSS2_SUBSCRIPTION_DEFAULTS
from jidou.services.rss_stub import ensure_rss_stub


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
