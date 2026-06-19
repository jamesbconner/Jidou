"""Tests for MatchOrchestrator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.downloaded_file import FileStatus, MatchedBy
from jidou.orchestrators.match_orchestrator import MatchOrchestrator
from jidou.services.progress import TaskCancelledError


def _make_episode(ep_id=10, show_id=1, season=1, ep_num=2, name="Test Episode"):
    ep = MagicMock()
    ep.id = ep_id
    ep.show_id = show_id
    ep.season_number = season
    ep.episode_number = ep_num
    ep.name = name
    ep.file_tracked = False
    return ep


def _make_file_row(
    file_id=1,
    filename="Show.S01E02.mkv",
    show_id=1,
    show_title="Test Show",
):
    file = MagicMock()
    file.id = file_id
    file.original_filename = filename
    file.show_id = show_id
    file.status = FileStatus.DOWNLOADED
    file.episode_id = None
    file.matched_by = None
    file.error_message = None

    show = MagicMock()
    show.id = show_id
    show.title = show_title

    return file, show


def _make_session(rows=None, episodes=None):
    """Build a session that returns file rows then episode lists."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    file_result = MagicMock()
    file_result.all.return_value = rows or []

    ep_result = MagicMock()
    ep_result.scalars.return_value.all.return_value = episodes or []

    session.execute = AsyncMock(side_effect=[file_result, ep_result])
    return session


# --- Static method tests ---

def test_heuristic_match_s01e02():
    assert MatchOrchestrator._heuristic_match("Show.S01E02.mkv") == (1, 2)


def test_heuristic_match_lowercase():
    assert MatchOrchestrator._heuristic_match("show.s03e10.mkv") == (3, 10)


def test_heuristic_match_1x02():
    assert MatchOrchestrator._heuristic_match("Show.1x02.mkv") == (1, 2)


def test_heuristic_match_no_pattern():
    assert MatchOrchestrator._heuristic_match("ShowFile.mkv") is None


# --- run() tests ---

async def test_run_matches_by_heuristic():
    """File with S01E02 pattern is matched to the correct episode via heuristic."""
    ep = _make_episode(season=1, ep_num=2)
    file, show = _make_file_row(filename="Show.S01E02.mkv")

    session = _make_session(rows=[(file, show)], episodes=[ep])

    orch = MatchOrchestrator(session)
    result = await orch.run()

    assert result.files_matched == 1
    assert result.matched_by_heuristic == 1
    assert result.matched_by_llm == 0
    assert file.status == FileStatus.ROUTED
    assert file.episode_id == ep.id
    assert file.matched_by == MatchedBy.HEURISTIC
    assert ep.file_tracked is True


async def test_run_episode_not_in_list():
    """Heuristic matches S01E99, but no episode with that number exists → ERROR."""
    ep = _make_episode(season=1, ep_num=2)  # ep_num=2, not 99
    file, show = _make_file_row(filename="Show.S01E99.mkv")

    session = _make_session(rows=[(file, show)], episodes=[ep])

    orch = MatchOrchestrator(session)
    result = await orch.run()

    assert result.files_matched == 0
    assert result.files_unmatched == 1
    assert file.status == FileStatus.ERROR
    assert "not found" in file.error_message


async def test_run_llm_fallback():
    """When heuristic fails, LLM is queried and its result used for matching."""
    ep = _make_episode(season=1, ep_num=2)
    file, show = _make_file_row(filename="ShowFile.mkv")  # no S##E## pattern

    session = _make_session(rows=[(file, show)], episodes=[ep])

    llm = MagicMock()
    llm.is_available = MagicMock(return_value=True)
    llm_response = MagicMock()
    llm_response.content = "1 2"
    llm.complete = AsyncMock(return_value=llm_response)

    orch = MatchOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.matched_by_llm == 1
    assert result.files_matched == 1
    assert file.status == FileStatus.ROUTED
    assert file.matched_by == MatchedBy.LLM


async def test_run_llm_returns_unknown():
    """LLM returning UNKNOWN results in file marked as unmatched ERROR."""
    file, show = _make_file_row(filename="ShowFile.mkv")

    session = _make_session(rows=[(file, show)], episodes=[_make_episode()])

    llm = MagicMock()
    llm.is_available = MagicMock(return_value=True)
    llm_response = MagicMock()
    llm_response.content = "UNKNOWN"
    llm.complete = AsyncMock(return_value=llm_response)

    orch = MatchOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_unmatched == 1
    assert file.status == FileStatus.ERROR


async def test_run_dry_run():
    """In dry_run mode, files_matched is optimistically counted but no DB changes."""
    ep = _make_episode(season=1, ep_num=2)
    file, show = _make_file_row(filename="Show.S01E02.mkv")

    session = _make_session(rows=[(file, show)], episodes=[ep])

    orch = MatchOrchestrator(session)
    result = await orch.run(dry_run=True)

    assert result.files_matched == 1
    # Status must NOT be changed in dry_run
    assert file.status == FileStatus.DOWNLOADED
    assert file.episode_id is None


async def test_run_cancellation_propagates():
    """TaskCancelledError raised in on_progress propagates out of run()."""
    ep = _make_episode(season=1, ep_num=2)
    file, show = _make_file_row(filename="Show.S01E02.mkv")

    session = _make_session(rows=[(file, show)], episodes=[ep])

    async def cancel_callback(current: int, total: int, message: str) -> None:
        raise TaskCancelledError("cancelled")

    orch = MatchOrchestrator(session)
    with pytest.raises(TaskCancelledError):
        await orch.run(on_progress=cancel_callback)
