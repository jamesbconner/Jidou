"""Tests for episode watch-state helper functions."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from jidou.services.episode_watching import clear_episode_watched, mark_episode_watched


def _make_episode(**kwargs: object) -> MagicMock:
    """Return a mock Episode with watch field defaults."""
    ep = MagicMock()
    ep.watched = kwargs.get("watched", False)
    ep.watched_at = kwargs.get("watched_at")
    return ep


class TestMarkEpisodeWatched:
    def test_sets_both_fields(self) -> None:
        ep = _make_episode()
        before = datetime.now(UTC)
        mark_episode_watched(ep)
        after = datetime.now(UTC)

        assert ep.watched is True
        assert ep.watched_at is not None
        assert before <= ep.watched_at <= after

    def test_uses_explicit_watched_at(self) -> None:
        fixed = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        ep = _make_episode()
        mark_episode_watched(ep, watched_at=fixed)

        assert ep.watched_at == fixed

    def test_idempotent_on_already_watched_episode(self) -> None:
        old_time = datetime(2023, 1, 1, tzinfo=UTC)
        ep = _make_episode(watched=True, watched_at=old_time)
        mark_episode_watched(ep)

        assert ep.watched is True
        assert ep.watched_at != old_time


class TestClearEpisodeWatched:
    def test_clears_both_fields(self) -> None:
        ep = _make_episode(watched=True, watched_at=datetime.now(UTC))
        clear_episode_watched(ep)

        assert ep.watched is False
        assert ep.watched_at is None

    def test_idempotent_on_unwatched_episode(self) -> None:
        ep = _make_episode()
        clear_episode_watched(ep)

        assert ep.watched is False
        assert ep.watched_at is None
