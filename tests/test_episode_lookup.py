"""Tests for jidou.services.episode_lookup."""

from unittest.mock import AsyncMock, MagicMock

from jidou.services.episode_lookup import resolve_episode


def _mock_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


async def test_resolve_episode_episode_none_returns_none_without_query() -> None:
    """No episode number at all short-circuits with no DB query."""
    session = AsyncMock()
    ep = await resolve_episode(session, show_id=1, season=1, episode=None)
    assert ep is None
    session.execute.assert_not_called()


async def test_resolve_episode_season_given_exact_match() -> None:
    """Season and episode both known: exact (season_number, episode_number) match."""
    episode = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_result(episode))

    ep = await resolve_episode(session, show_id=1, season=2, episode=5)

    assert ep is episode
    session.execute.assert_awaited_once()


async def test_resolve_episode_season_given_miss_returns_none_no_fallback() -> None:
    """Season given but no exact match: returns None, no further fallback attempted.

    A known season number means confident data -- guessing further risks a
    wrong match (e.g. a Season 3 file must never silently resolve to a
    Season 1 episode).
    """
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_result(None))

    ep = await resolve_episode(session, show_id=1, season=3, episode=99)

    assert ep is None
    session.execute.assert_awaited_once()


async def test_resolve_episode_season_none_absolute_hit() -> None:
    """Season unknown: absolute_episode_number column match resolves in one query."""
    episode = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_result(episode))

    ep = await resolve_episode(session, show_id=1, season=None, episode=146)

    assert ep is episode
    session.execute.assert_awaited_once()


async def test_resolve_episode_season_none_falls_back_to_season_1_by_default() -> None:
    """Season unknown, absolute miss, positional_fallback=False (default): tries Season 1.

    This is the canonical anime-without-season-markers chain used by the
    SFTP pipeline (ParseOrchestrator, RouteOrchestrator, SyncOrchestrator's
    retry, and manual file matching).
    """
    episode = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_mock_result(None), _mock_result(episode)])

    ep = await resolve_episode(session, show_id=1, season=None, episode=13)

    assert ep is episode
    assert session.execute.await_count == 2


async def test_resolve_episode_season_none_both_miss_returns_none() -> None:
    """Season unknown, absolute and Season-1 both miss: returns None."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_result(None))

    ep = await resolve_episode(session, show_id=1, season=None, episode=13)

    assert ep is None
    assert session.execute.await_count == 2


async def test_resolve_episode_positional_fallback_used_instead_of_season_1() -> None:
    """positional_fallback=True tries the ROW_NUMBER lookup, not Season 1.

    Path-list import's strategy: the two fallbacks are mutually exclusive,
    not stacked -- positional_fallback replaces the Season-1 guess rather
    than adding a third attempt on top of it.
    """
    episode = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_mock_result(None), _mock_result(episode)])

    ep = await resolve_episode(
        session, show_id=1, season=None, episode=146, positional_fallback=True
    )

    assert ep is episode
    assert session.execute.await_count == 2


async def test_resolve_episode_positional_fallback_miss_does_not_try_season_1() -> None:
    """positional_fallback=True: when both absolute and positional miss, no Season-1 attempt.

    Regression guard for the mutual-exclusivity design: exactly 2 queries,
    not 3 -- adding an unconditional Season-1 fallback on top of positional
    would change path-list import's season>1-retry query count and risk a
    false-positive match in a context where the season is already known.
    """
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_result(None))

    ep = await resolve_episode(
        session, show_id=1, season=None, episode=999, positional_fallback=True
    )

    assert ep is None
    assert session.execute.await_count == 2
