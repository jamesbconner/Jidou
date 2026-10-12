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
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock) as dismiss:
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


def test_reassign_show_without_episode_does_not_clear_old_tracking() -> None:
    """Pins current behavior (spec §5): show change alone never calls clear_if_unreferenced."""
    f = _file(show_id=1, episode_id=10)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock) as clear,
    ):
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=False, keep_error=False))
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
