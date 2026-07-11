"""Tests for episode tracking helper functions."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.services.episode_tracking import (
    clear_episode_tracking,
    clear_if_unreferenced,
    dismiss_orphans_for_file,
    mark_episode_tracked,
)


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

    def test_preserves_none_tracked_at_from_snapshot(self) -> None:
        """Explicitly passing tracked_at=None must store NULL, not datetime.now()."""
        ep = _make_episode()
        mark_episode_tracked(ep, "file.mkv", "match", tracked_at=None)

        assert ep.file_tracked is True
        assert ep.file_tracked_at is None

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


class TestClearIfUnreferenced:
    async def test_noop_when_old_episode_id_is_none(self) -> None:
        session = AsyncMock()
        await clear_if_unreferenced(session, None, 42)
        session.execute.assert_not_awaited()

    async def test_noop_when_old_equals_new(self) -> None:
        session = AsyncMock()
        await clear_if_unreferenced(session, 10, 10)
        session.execute.assert_not_awaited()

    async def test_clears_when_no_other_file_references_old_episode(self) -> None:
        old_ep = _make_episode(file_tracked=True, tracked_filename="a.mkv", tracked_source="match")
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        old_ep_result = MagicMock()
        old_ep_result.scalar_one_or_none.return_value = old_ep
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[count_result, old_ep_result])

        await clear_if_unreferenced(session, 10, 42)

        assert old_ep.file_tracked is False
        assert old_ep.tracked_filename is None
        assert session.execute.await_count == 2

    async def test_skips_clear_when_other_file_still_references_old_episode(self) -> None:
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[count_result])

        await clear_if_unreferenced(session, 10, 42)

        # Only the count query runs — the episode lookup is skipped entirely.
        assert session.execute.await_count == 1

    async def test_noop_when_old_episode_row_not_found(self) -> None:
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        missing_result = MagicMock()
        missing_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[count_result, missing_result])

        await clear_if_unreferenced(session, 10, 42)  # must not raise

    async def test_treats_new_episode_id_none_as_a_change(self) -> None:
        """Clearing episode_id back to null must still trigger the unreferenced check."""
        old_ep = _make_episode(file_tracked=True)
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        old_ep_result = MagicMock()
        old_ep_result.scalar_one_or_none.return_value = old_ep
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[count_result, old_ep_result])

        await clear_if_unreferenced(session, 10, None)

        assert old_ep.file_tracked is False


class TestDismissOrphansForFile:
    async def test_issues_a_delete_scoped_to_the_file(self) -> None:
        session = AsyncMock()

        await dismiss_orphans_for_file(session, 7)

        session.execute.assert_awaited_once()
        stmt = session.execute.await_args.args[0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        sql = str(compiled)
        assert "orphaned_tracking_records" in sql
        assert "7" in sql
