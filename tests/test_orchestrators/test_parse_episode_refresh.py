"""Tests for ParseOrchestrator's missing-episode handling.

A matched show whose parsed episode is absent from the episode table triggers a
TMDB episode refresh (once per show per run) and a retry. A file that still has
no episode afterwards is left UNMATCHED for manual resolution instead of being
routed to the show root as MATCHED.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator
from tests.test_orchestrators.test_match_orchestrator import (
    _make_file,
    _make_show,
    _parsed,
    _recording_parse_session,
)

_MOD = "jidou.orchestrators.parse_orchestrator"


def _episode(ep_id: int = 99, season: int = 3, number: int = 1) -> MagicMock:
    return MagicMock(id=ep_id, season_number=season, episode_number=number)


def _refresher(*, added: bool = True) -> MagicMock:
    refresher = MagicMock()
    refresher.refresh_episodes = AsyncMock(return_value=added)
    return refresher


async def _run(
    files: list,
    show: MagicMock,
    parsed_by_file: list,
    *,
    resolve_results: list,
    refresher: MagicMock | None,
    on_event: AsyncMock | None = None,
):
    """Run one parse pass with the show lookup and episode resolution scripted."""
    session, _ = _recording_parse_session(files)
    resolve = AsyncMock(side_effect=resolve_results)
    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(side_effect=parsed_by_file)),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
        patch(f"{_MOD}.resolve_episode", resolve),
        patch(f"{_MOD}.llm_match_episode", AsyncMock(return_value=(None, None, None))),
        patch(f"{_MOD}.find_duplicate_original", AsyncMock(return_value=None)),
        patch(f"{_MOD}.dismiss_orphans_for_file", AsyncMock()),
    ):
        orch = ParseOrchestrator(session, llm=None, episode_refresher=refresher)
        result = await orch.run(on_event=on_event)
    return result, resolve


async def test_episode_miss_triggers_refresh_then_matches_when_episode_appears():
    """A new-season file matches once the refresh brings its episode in."""
    file1 = _make_file(filename="Show.S03E01.mkv")
    show = _make_show()
    show.media_type = "tv"
    refresher = _refresher(added=True)
    ep = _episode()

    result, resolve = await _run(
        [file1],
        show,
        [_parsed(season=3, episode=1)],
        resolve_results=[None, ep],
        refresher=refresher,
    )

    refresher.refresh_episodes.assert_awaited_once_with(show)
    assert resolve.await_count == 2
    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED
    assert file1.episode_id == 99


async def test_episode_still_missing_after_refresh_leaves_file_unmatched():
    """No episode even after the refresh: UNMATCHED, show kept, reason recorded."""
    file1 = _make_file(filename="Show.S03E01.mkv")
    show = _make_show()
    show.media_type = "tv"
    refresher = _refresher(added=True)

    result, _ = await _run(
        [file1],
        show,
        [_parsed(season=3, episode=1)],
        resolve_results=[None, None],
        refresher=refresher,
    )

    assert result.files_unmatched == 1
    assert result.files_matched == 0
    assert file1.status == FileStatus.UNMATCHED
    assert file1.show_id == show.id
    assert file1.episode_id is None
    assert "S03E01" in file1.error_message


async def test_refresh_adding_nothing_skips_the_retry():
    """A refresh that brought no new episodes cannot change the answer."""
    file1 = _make_file(filename="Show.S03E01.mkv")
    show = _make_show()
    show.media_type = "tv"
    refresher = _refresher(added=False)

    result, resolve = await _run(
        [file1],
        show,
        [_parsed(season=3, episode=1)],
        resolve_results=[None],
        refresher=refresher,
    )

    refresher.refresh_episodes.assert_awaited_once()
    assert resolve.await_count == 1
    assert file1.status == FileStatus.UNMATCHED
    assert result.files_unmatched == 1


async def test_refresh_runs_once_per_show_per_run():
    """Several files of the same show share one refresh."""
    files = [_make_file(file_id=i, filename=f"Show.S03E0{i}.mkv") for i in (1, 2, 3)]
    show = _make_show()
    show.media_type = "tv"
    refresher = _refresher(added=True)
    ep = _episode()

    # file 1: miss -> refresh -> hit; files 2 and 3 resolve straight away.
    result, _ = await _run(
        files,
        show,
        [_parsed(season=3, episode=i) for i in (1, 2, 3)],
        resolve_results=[None, ep, ep, ep],
        refresher=refresher,
    )

    refresher.refresh_episodes.assert_awaited_once()
    assert result.files_matched == 3


async def test_second_miss_for_same_show_does_not_refresh_again():
    """A later miss for an already-refreshed show goes straight to UNMATCHED."""
    files = [_make_file(file_id=i, filename=f"Show.S03E0{i}.mkv") for i in (1, 2)]
    show = _make_show()
    show.media_type = "tv"
    refresher = _refresher(added=True)

    result, _ = await _run(
        files,
        show,
        [_parsed(season=3, episode=i) for i in (1, 2)],
        resolve_results=[None, None, None],
        refresher=refresher,
    )

    refresher.refresh_episodes.assert_awaited_once()
    assert result.files_unmatched == 2
    assert all(f.status == FileStatus.UNMATCHED for f in files)


async def test_no_season_and_absolute_and_season_one_fallbacks_miss_is_unmatched():
    """No season detected and both fallbacks miss: UNMATCHED with a season-specific reason."""
    file1 = _make_file(filename="Show - 25.mkv")
    show = _make_show()
    show.media_type = "tv"

    result, _ = await _run(
        [file1],
        show,
        [_parsed(season=None, episode=25)],
        resolve_results=[None],
        refresher=_refresher(added=False),
    )

    assert result.files_unmatched == 1
    assert file1.status == FileStatus.UNMATCHED
    assert "season" in file1.error_message.lower()


async def test_movie_without_episode_still_matches_and_never_refreshes():
    """Movies have no episode rows: no refresh, still MATCHED."""
    file1 = _make_file(filename="Some.Movie.2024.mkv")
    show = _make_show()
    show.media_type = "movie"
    refresher = _refresher()

    result, _ = await _run(
        [file1],
        show,
        [_parsed(season=None, episode=None, content_type="movie")],
        resolve_results=[None],
        refresher=refresher,
    )

    refresher.refresh_episodes.assert_not_awaited()
    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED


async def test_without_refresher_a_miss_is_still_unmatched():
    """No refresher configured: skip the refresh, but never route an episode-less TV file."""
    file1 = _make_file(filename="Show.S03E01.mkv")
    show = _make_show()
    show.media_type = "tv"

    result, resolve = await _run(
        [file1],
        show,
        [_parsed(season=3, episode=1)],
        resolve_results=[None],
        refresher=None,
    )

    assert resolve.await_count == 1
    assert result.files_unmatched == 1
    assert file1.status == FileStatus.UNMATCHED


async def test_unmatched_for_missing_episode_emits_warn_event():
    """The UNMATCHED decision is visible in the event log."""
    file1 = _make_file(filename="Show.S03E01.mkv")
    show = _make_show()
    show.media_type = "tv"
    on_event = AsyncMock()

    await _run(
        [file1],
        show,
        [_parsed(season=3, episode=1)],
        resolve_results=[None],
        refresher=_refresher(added=False),
        on_event=on_event,
    )

    levels = [call.args[0] for call in on_event.await_args_list]
    assert "warn" in levels


@pytest.mark.parametrize("added", [True, False])
async def test_dry_run_never_refreshes(added):
    """Dry run performs no side effects, so no TMDB refresh."""
    file1 = _make_file(filename="Show.S03E01.mkv")
    show = _make_show()
    show.media_type = "tv"
    refresher = _refresher(added=added)
    session, _ = _recording_parse_session([file1])

    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(return_value=_parsed(season=3, episode=1))),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
    ):
        await ParseOrchestrator(session, llm=None, episode_refresher=refresher).run(dry_run=True)

    refresher.refresh_episodes.assert_not_awaited()


async def _dry_run(show, parsed, *, resolve_result, on_event=None):
    file1 = _make_file(filename="Show.S03E01.mkv")
    session, _ = _recording_parse_session([file1])
    resolve = AsyncMock(return_value=resolve_result)
    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(return_value=parsed)),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
        patch(f"{_MOD}.resolve_episode", resolve),
    ):
        result = await ParseOrchestrator(session, llm=None).run(dry_run=True, on_event=on_event)
    return result, file1, resolve


async def test_dry_run_reports_unmatched_when_the_episode_is_missing():
    """Bugbot: the preview must show the new UNMATCHED outcome, not count a match."""
    show = _make_show()
    show.media_type = "tv"
    on_event = AsyncMock()

    result, file1, _ = await _dry_run(
        show, _parsed(season=3, episode=1), resolve_result=None, on_event=on_event
    )

    assert (result.files_matched, result.files_unmatched) == (0, 1)
    assert file1.status == FileStatus.DOWNLOADED  # a dry run never modifies the file
    assert any("Would leave unmatched" in call.args[1] for call in on_event.await_args_list)


async def test_dry_run_reports_match_when_the_episode_exists():
    show = _make_show()
    show.media_type = "tv"

    result, _, _ = await _dry_run(show, _parsed(season=3, episode=1), resolve_result=_episode())

    assert (result.files_matched, result.files_unmatched) == (1, 0)


async def test_dry_run_movie_skips_the_episode_lookup():
    show = _make_show()
    show.media_type = "movie"

    result, _, resolve = await _dry_run(
        show, _parsed(season=None, episode=None, content_type="movie"), resolve_result=None
    )

    resolve.assert_not_awaited()
    assert result.files_matched == 1
