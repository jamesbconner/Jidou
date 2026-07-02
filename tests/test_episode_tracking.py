"""Tests for episode tracking helper functions."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from jidou.services.episode_tracking import clear_episode_tracking, mark_episode_tracked


def _make_episode(**kwargs: object) -> MagicMock:
    """Return a mock Episode with tracking field defaults."""
    ep = MagicMock()
    ep.file_tracked = kwargs.get("file_tracked", False)
    ep.file_tracked_at = kwargs.get("file_tracked_at")
    ep.tracked_filename = kwargs.get("tracked_filename")
    ep.tracked_source = kwargs.get("tracked_source")
    return ep


class TestMarkEpisodeTracked:
    def test_sets_all_four_fields(self) -> None:
        ep = _make_episode()
        before = datetime.now(UTC)
        mark_episode_tracked(ep, "/media/show.mkv", "match")
        after = datetime.now(UTC)

        assert ep.file_tracked is True
        assert ep.tracked_filename == "/media/show.mkv"
        assert ep.tracked_source == "match"
        assert ep.file_tracked_at is not None
        assert before <= ep.file_tracked_at <= after

    def test_uses_explicit_tracked_at(self) -> None:
        fixed = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        ep = _make_episode()
        mark_episode_tracked(ep, "file.mkv", "import", tracked_at=fixed)

        assert ep.file_tracked_at == fixed

    def test_accepts_none_filename(self) -> None:
        ep = _make_episode()
        mark_episode_tracked(ep, None, "match")

        assert ep.file_tracked is True
        assert ep.tracked_filename is None

    def test_accepts_none_source(self) -> None:
        ep = _make_episode()
        mark_episode_tracked(ep, "file.mkv", None)

        assert ep.file_tracked is True
        assert ep.tracked_source is None

    def test_overwrites_existing_tracking(self) -> None:
        old_time = datetime(2023, 1, 1, tzinfo=UTC)
        ep = _make_episode(
            file_tracked=True,
            file_tracked_at=old_time,
            tracked_filename="old.mkv",
            tracked_source="import",
        )
        mark_episode_tracked(ep, "new.mkv", "match")

        assert ep.tracked_filename == "new.mkv"
        assert ep.tracked_source == "match"
        assert ep.file_tracked_at != old_time

    @pytest.mark.parametrize("source", ["match", "import"])
    def test_standard_sources(self, source: str) -> None:
        ep = _make_episode()
        mark_episode_tracked(ep, "file.mkv", source)
        assert ep.tracked_source == source


class TestClearEpisodeTracking:
    def test_clears_all_four_fields(self) -> None:
        ep = _make_episode(
            file_tracked=True,
            file_tracked_at=datetime.now(UTC),
            tracked_filename="file.mkv",
            tracked_source="match",
        )
        clear_episode_tracking(ep)

        assert ep.file_tracked is False
        assert ep.file_tracked_at is None
        assert ep.tracked_filename is None
        assert ep.tracked_source is None

    def test_idempotent_on_untracked_episode(self) -> None:
        ep = _make_episode()
        clear_episode_tracking(ep)

        assert ep.file_tracked is False
        assert ep.file_tracked_at is None
