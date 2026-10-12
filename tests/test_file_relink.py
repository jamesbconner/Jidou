"""Unit tests for jidou.services.file_relink."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.file_relink import (
    EpisodeAlreadyTrackedError,
    EpisodeShowMismatchError,
    reassign_show,
    relink_episode,
)

_MOD = "jidou.services.file_relink"


def _file(*, show_id: int | None = 1, episode_id: int | None = 10) -> MagicMock:
    f = MagicMock()
    f.id = 99
    f.show_id = show_id
    f.episode_id = episode_id
    f.matched_by = "llm"
    f.error_message = "old error"
    f.local_path = "/x/show.s01e02.mkv"
    f.original_filename = "show.s01e02.mkv"
    return f


def _episode(*, show_id: int = 1, tracked: bool = False) -> MagicMock:
    ep = MagicMock()
    ep.show_id = show_id
    ep.file_tracked = tracked
    ep.season_number = 1
    ep.episode_number = 2
    return ep


def _session_with_episode(ep: MagicMock | None) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = ep
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def test_reassign_show_same_value_is_a_noop() -> None:
    f = _file(show_id=1)
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock) as dismiss:
        asyncio.run(reassign_show(AsyncMock(), f, 1, keep_episode=False, keep_error=False))
    assert (f.episode_id, f.matched_by, f.error_message) == (10, "llm", "old error")
    dismiss.assert_not_awaited()


def test_reassign_show_change_clears_episode_matcher_and_error() -> None:
    f = _file(show_id=1)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock) as dismiss,
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock),
    ):
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=False, keep_error=False))
    assert f.show_id == 2
    assert f.episode_id is None
    assert f.matched_by is None
    assert f.error_message is None
    dismiss.assert_awaited_once()


def test_reassign_show_keeps_explicit_episode_and_error() -> None:
    f = _file(show_id=1)
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock):
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=True, keep_error=True))
    assert f.episode_id == 10
    assert f.error_message == "old error"
    assert f.matched_by is None


def test_reassign_show_without_episode_clears_old_tracking() -> None:
    """A show change that drops the episode link clears the old episode's tracking."""
    f = _file(show_id=1, episode_id=10)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock) as clear,
    ):
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=False, keep_error=False))
    clear.assert_awaited_once()
    assert clear.await_args.args[1:] == (10, None)


def test_reassign_show_nulls_link_before_clear_so_moved_file_is_not_counted() -> None:
    """The file's own link must be nulled before the reference count runs.

    The count query autoflushes pending changes; if the link were still set the
    moved file would count as a remaining reference and tracking would never clear.
    """
    f = _file(show_id=1, episode_id=10)
    seen: list[int | None] = []

    async def _spy(session: object, old: int | None, new: int | None) -> None:
        seen.append(f.episode_id)

    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", side_effect=_spy),
    ):
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=False, keep_error=False))
    assert seen == [None]


def test_reassign_show_clears_tracking_when_moved_file_was_only_reference() -> None:
    """End to end with the real helper: zero remaining references -> old episode cleared."""
    f = _file(show_id=1, episode_id=10)
    old_ep = _episode()
    old_ep.file_tracked = True
    old_ep.tracked_filename = "a.mkv"
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = old_ep
    counted_with: list[int | None] = []

    async def _execute(stmt: object) -> MagicMock:
        if not counted_with:
            counted_with.append(f.episode_id)  # state the count query would flush
            return count_result
        return ep_result

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=_execute)
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock):
        asyncio.run(reassign_show(session, f, 2, keep_episode=False, keep_error=False))
    assert counted_with == [None]
    assert old_ep.file_tracked is False
    assert old_ep.tracked_filename is None


def test_reassign_show_keeps_old_tracking_while_another_file_references_it() -> None:
    f = _file(show_id=1, episode_id=10)
    old_ep = _episode()
    old_ep.file_tracked = True
    count_result = MagicMock()
    count_result.scalar.return_value = 1  # another file still points at the episode
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result])
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock):
        asyncio.run(reassign_show(session, f, 2, keep_episode=False, keep_error=False))
    assert old_ep.file_tracked is True
    assert session.execute.await_count == 1  # count only; episode lookup skipped


def test_reassign_show_without_old_episode_is_a_noop_for_tracking() -> None:
    f = _file(show_id=1, episode_id=None)
    session = AsyncMock()
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock):
        asyncio.run(reassign_show(session, f, 2, keep_episode=False, keep_error=False))
    assert f.show_id == 2
    session.execute.assert_not_awaited()


def test_reassign_show_with_explicit_episode_leaves_clearing_to_relink() -> None:
    f = _file(show_id=1, episode_id=10)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock) as clear,
    ):
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=True, keep_error=False))
    clear.assert_not_awaited()


def test_relink_episode_to_none_clears_parsed_fields_and_old_tracking() -> None:
    f = _file(episode_id=10)
    with patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock) as clear:
        asyncio.run(relink_episode(AsyncMock(), f, None))
    assert f.episode_id is None
    assert f.parsed_season is None
    assert f.parsed_episode is None
    clear.assert_awaited_once()
    assert clear.await_args.args[1:] == (10, None)


def test_relink_episode_marks_target_tracked_and_copies_numbers() -> None:
    f = _file(episode_id=10)
    ep = _episode()
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock),
        patch(f"{_MOD}.mark_episode_tracked") as mark,
    ):
        asyncio.run(relink_episode(_session_with_episode(ep), f, 11))
    mark.assert_called_once_with(ep, "/x/show.s01e02.mkv", "match")
    assert (f.episode_id, f.parsed_season, f.parsed_episode) == (11, 1, 2)


def test_relink_episode_wrong_show_raises() -> None:
    f = _file(show_id=1)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        pytest.raises(EpisodeShowMismatchError, match="Episode does not belong to the file's show"),
    ):
        asyncio.run(relink_episode(_session_with_episode(_episode(show_id=2)), f, 11))


def test_relink_episode_already_tracked_by_other_file_raises() -> None:
    f = _file(episode_id=10)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        pytest.raises(EpisodeAlreadyTrackedError, match="already tracked by another file"),
    ):
        asyncio.run(relink_episode(_session_with_episode(_episode(tracked=True)), f, 11))


def test_relink_same_tracked_episode_is_allowed() -> None:
    f = _file(episode_id=11)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock),
        patch(f"{_MOD}.mark_episode_tracked"),
    ):
        asyncio.run(relink_episode(_session_with_episode(_episode(tracked=True)), f, 11))
    assert f.episode_id == 11


def test_relink_unknown_episode_skips_validation_but_clears_old_tracking() -> None:
    f = _file(episode_id=10)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock) as clear,
        patch(f"{_MOD}.mark_episode_tracked") as mark,
    ):
        asyncio.run(relink_episode(_session_with_episode(None), f, 777))
    assert f.episode_id == 777
    mark.assert_not_called()
    assert clear.await_args.args[1:] == (10, 777)
