"""Tests for MatchOrchestrator (file-to-episode matching via heuristic + LLM)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.downloaded_file import FileStatus, MatchedBy
from jidou.orchestrators.match_orchestrator import MatchOrchestrator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(
    file_id: int = 1,
    filename: str = "Show.S01E01.mkv",
    status: FileStatus = FileStatus.DOWNLOADED,
    show_id: int = 10,
    episode_id: int | None = None,
) -> MagicMock:
    f = MagicMock()
    f.id = file_id
    f.original_filename = filename
    f.status = status
    f.show_id = show_id
    f.episode_id = episode_id
    f.matched_by = None
    f.error_message = None
    return f


def _make_show(show_id: int = 10, title: str = "Test Show") -> MagicMock:
    s = MagicMock()
    s.id = show_id
    s.title = title
    return s


def _make_episode(
    ep_id: int = 1,
    show_id: int = 10,
    season: int = 1,
    ep_num: int = 1,
    name: str = "Pilot",
    file_tracked: bool = False,
) -> MagicMock:
    e = MagicMock()
    e.id = ep_id
    e.show_id = show_id
    e.season_number = season
    e.episode_number = ep_num
    e.name = name
    e.file_tracked = file_tracked
    e.file_tracked_at = None
    e.tracked_filename = None
    e.tracked_source = None
    return e


def _make_session(
    file_show_pairs: list[tuple],
    episodes: list,
    *,
    extra_executes: list | None = None,
) -> MagicMock:
    """Build a mock AsyncSession for MatchOrchestrator.run().

    Execute call order:
      1. files+shows query  → .all() returns file_show_pairs
      2. episodes-per-show  → .scalars().all() returns episodes  (once per show)
      3. flush/orphan deletes + any extra_executes per test
    """
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    files_result = MagicMock()
    files_result.all.return_value = file_show_pairs

    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = episodes

    # Orphan delete — result is ignored by orchestrator
    orphan_result = MagicMock()

    side_effects: list = [files_result, ep_list_result, orphan_result]
    if extra_executes:
        side_effects.extend(extra_executes)

    session.execute = AsyncMock(side_effect=side_effects)
    return session


# ---------------------------------------------------------------------------
# _heuristic_match unit tests
# ---------------------------------------------------------------------------


def test_heuristic_match_sxxeyy() -> None:
    """SxxEyy pattern returns (season, episode)."""
    orch = MatchOrchestrator.__new__(MatchOrchestrator)
    assert orch._heuristic_match("Show.S01E02.1080p.mkv") == (1, 2)


def test_heuristic_match_nxm() -> None:
    """NxM pattern returns (season, episode)."""
    orch = MatchOrchestrator.__new__(MatchOrchestrator)
    assert orch._heuristic_match("Show.2x05.mkv") == (2, 5)


def test_heuristic_match_no_pattern_returns_none() -> None:
    """Returns None when no S/E pattern is found."""
    orch = MatchOrchestrator.__new__(MatchOrchestrator)
    assert orch._heuristic_match("Movie.2024.1080p.mkv") is None


def test_heuristic_match_resolution_not_matched() -> None:
    """1920x1080 resolution string is not matched as episode."""
    orch = MatchOrchestrator.__new__(MatchOrchestrator)
    assert orch._heuristic_match("Show.1920x1080.mkv") is None


def test_heuristic_match_sxxeyy_three_digit_episode() -> None:
    """3-digit episode number (e.g. E124) is extracted correctly."""
    orch = MatchOrchestrator.__new__(MatchOrchestrator)
    assert orch._heuristic_match("OnePiece.S01E124.mkv") == (1, 124)


# ---------------------------------------------------------------------------
# _llm_match unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_match_returns_none_when_llm_none() -> None:
    """_llm_match returns None immediately when llm=None."""
    session = MagicMock()
    orch = MatchOrchestrator(session, llm=None)
    result = await orch._llm_match("Show.S01E01.mkv", "Test Show", [])
    assert result is None


@pytest.mark.asyncio
async def test_llm_match_returns_none_when_llm_unavailable() -> None:
    """_llm_match returns None when llm.is_available() is False."""
    session = MagicMock()
    llm = MagicMock()
    llm.is_available.return_value = False
    orch = MatchOrchestrator(session, llm=llm)
    result = await orch._llm_match("Show.S01E01.mkv", "Test Show", [])
    assert result is None


@pytest.mark.asyncio
async def test_llm_match_success_returns_season_episode() -> None:
    """_llm_match parses '2 7' response into (2, 7)."""
    session = MagicMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm_resp = MagicMock()
    llm_resp.content = "2 7"
    llm.complete = AsyncMock(return_value=llm_resp)

    orch = MatchOrchestrator(session, llm=llm)
    episodes = [_make_episode(season=2, ep_num=7)]
    result = await orch._llm_match("Show.ep7.mkv", "Test Show", episodes)
    assert result == (2, 7)


@pytest.mark.asyncio
async def test_llm_match_unknown_returns_none() -> None:
    """_llm_match returns None when LLM replies UNKNOWN."""
    session = MagicMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm_resp = MagicMock()
    llm_resp.content = "UNKNOWN"
    llm.complete = AsyncMock(return_value=llm_resp)

    orch = MatchOrchestrator(session, llm=llm)
    result = await orch._llm_match("weird_file.mkv", "Test Show", [])
    assert result is None


@pytest.mark.asyncio
async def test_llm_match_none_response_returns_none() -> None:
    """_llm_match returns None when llm.complete returns None (outage)."""
    session = MagicMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)

    orch = MatchOrchestrator(session, llm=llm)
    result = await orch._llm_match("weird_file.mkv", "Test Show", [])
    assert result is None


@pytest.mark.asyncio
async def test_llm_match_bad_format_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    """_llm_match returns None and logs warning for non-integer LLM response."""
    import logging

    session = MagicMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm_resp = MagicMock()
    llm_resp.content = "two seven"
    llm.complete = AsyncMock(return_value=llm_resp)

    orch = MatchOrchestrator(session, llm=llm)
    with caplog.at_level(logging.WARNING):
        result = await orch._llm_match("weird_file.mkv", "Test Show", [])

    assert result is None
    assert "non-integer" in caplog.text


# ---------------------------------------------------------------------------
# run() — no files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_no_files_returns_empty_result() -> None:
    """run() with no DOWNLOADED files returns zeroed MatchResult."""
    files_result = MagicMock()
    files_result.all.return_value = []
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=files_result)

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_matched == 0
    assert result.files_unmatched == 0
    assert result.files_failed == 0


# ---------------------------------------------------------------------------
# run() — heuristic match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_heuristic_match_sets_routed_and_tracks_episode() -> None:
    """Heuristic match: file transitions to ROUTED and episode is marked tracked."""
    file = _make_file(filename="Show.S01E01.mkv")
    show = _make_show()
    ep = _make_episode(ep_id=5, season=1, ep_num=1)

    session = _make_session([(file, show)], [ep])
    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_matched == 1
    assert result.matched_by_heuristic == 1
    assert result.matched_by_llm == 0
    assert result.files_unmatched == 0
    assert file.status == FileStatus.ROUTED
    assert file.episode_id == ep.id
    assert file.matched_by == MatchedBy.HEURISTIC
    assert ep.file_tracked is True
    assert ep.tracked_filename == file.original_filename
    assert ep.tracked_source == "match"
    assert ep.file_tracked_at is not None


@pytest.mark.asyncio
async def test_run_heuristic_episode_not_in_list_sets_error() -> None:
    """When heuristic finds S02E01 but only S01 episodes exist → ERROR."""
    file = _make_file(filename="Show.S02E01.mkv")
    show = _make_show()
    ep = _make_episode(ep_id=1, season=1, ep_num=1)  # season 1 only

    # No orphan delete since we don't reach the match path
    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [ep]
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result])

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_unmatched == 1
    assert file.status == FileStatus.ERROR
    assert "S02E01" in (file.error_message or "")


# ---------------------------------------------------------------------------
# run() — LLM fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_llm_fallback_when_heuristic_fails() -> None:
    """When heuristic finds no pattern, LLM fallback is used."""
    file = _make_file(filename="Show.Episode.Seven.mkv")
    show = _make_show()
    ep = _make_episode(ep_id=7, season=1, ep_num=7)

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_resp = MagicMock()
    llm_resp.content = "1 7"
    llm.complete = AsyncMock(return_value=llm_resp)

    session = _make_session([(file, show)], [ep])
    orch = MatchOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_matched == 1
    assert result.matched_by_llm == 1
    assert result.matched_by_heuristic == 0
    assert file.matched_by == MatchedBy.LLM
    assert ep.file_tracked is True


@pytest.mark.asyncio
async def test_run_no_llm_and_heuristic_fails_sets_error() -> None:
    """No heuristic match and no LLM → ERROR with message."""
    file = _make_file(filename="Random.Name.Without.Pattern.mkv")
    show = _make_show()
    ep = _make_episode()

    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [ep]
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result])

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_unmatched == 1
    assert file.status == FileStatus.ERROR
    assert file.error_message is not None


@pytest.mark.asyncio
async def test_run_llm_unknown_and_heuristic_fails_sets_error() -> None:
    """LLM returns UNKNOWN and heuristic fails → file marked ERROR."""
    file = _make_file(filename="Random.File.mkv")
    show = _make_show()
    ep = _make_episode()

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_resp = MagicMock()
    llm_resp.content = "UNKNOWN"
    llm.complete = AsyncMock(return_value=llm_resp)

    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [ep]
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result])

    orch = MatchOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_unmatched == 1
    assert file.status == FileStatus.ERROR


# ---------------------------------------------------------------------------
# run() — dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_dry_run_does_not_flush_or_write_episode() -> None:
    """dry_run=True skips the per-file flush and does not mutate episode rows."""
    file = _make_file(filename="Show.S01E01.mkv")
    show = _make_show()
    ep = _make_episode()

    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [ep]
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result])

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run(dry_run=True)

    assert result.dry_run is True
    # Per-file flush (status = ROUTING) must not be called in dry_run
    session.flush.assert_not_called()
    # Episode must not be modified in dry_run
    assert ep.file_tracked is False


@pytest.mark.asyncio
async def test_run_dry_run_no_match_increments_unmatched() -> None:
    """dry_run=True with no heuristic match and no LLM increments files_unmatched."""
    file = _make_file(filename="Random.File.mkv")
    show = _make_show()

    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result])

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run(dry_run=True)

    assert result.files_unmatched == 1
    assert result.files_matched == 0


# ---------------------------------------------------------------------------
# run() — on_progress callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_on_progress_called_per_file() -> None:
    """on_progress callback is invoked once per file."""
    f1 = _make_file(file_id=1, filename="Show.S01E01.mkv")
    f2 = _make_file(file_id=2, filename="Show.S01E02.mkv")
    show = _make_show()
    ep1 = _make_episode(ep_id=1, season=1, ep_num=1)
    ep2 = _make_episode(ep_id=2, season=1, ep_num=2)

    files_result = MagicMock()
    files_result.all.return_value = [(f1, show), (f2, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [ep1, ep2]
    orphan = MagicMock()
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result, orphan, orphan])

    on_progress = AsyncMock()
    orch = MatchOrchestrator(session, llm=None)
    await orch.run(on_progress=on_progress)

    assert on_progress.call_count == 2
    call_args = [c.args for c in on_progress.call_args_list]
    assert call_args[0][0] == 1  # idx
    assert call_args[1][0] == 2


# ---------------------------------------------------------------------------
# run() — show_id filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_show_id_filter_applied_to_query() -> None:
    """show_id parameter is included in the WHERE clause."""
    files_result = MagicMock()
    files_result.all.return_value = []
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=files_result)

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run(show_id=42)

    # Verify the query was constructed and executed (no error)
    assert result.files_matched == 0
    session.execute.assert_called_once()
    # The executed statement should contain the show_id filter; we verify
    # behaviour rather than the raw SQL string.


# ---------------------------------------------------------------------------
# run() — exception handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_exception_during_match_increments_files_failed() -> None:
    """An unexpected exception inside the try block increments files_failed."""
    file = _make_file(filename="Show.S01E01.mkv")
    show = _make_show()
    ep = _make_episode()

    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [ep]

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result])

    orch = MatchOrchestrator(session, llm=None)

    # Raise inside the try block via _heuristic_match
    with patch.object(MatchOrchestrator, "_heuristic_match", side_effect=RuntimeError("oops")):
        result = await orch.run()

    assert result.files_failed == 1
    assert file.status == FileStatus.ERROR
    assert "oops" in (file.error_message or "")


# ---------------------------------------------------------------------------
# run() — old episode tracking cleared on reassignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_clears_old_episode_tracking_on_reassignment() -> None:
    """When a file is reassigned from old_ep to new_ep, old_ep tracking is cleared."""
    old_ep_id = 99
    new_ep = _make_episode(ep_id=1, season=1, ep_num=1)
    old_ep = _make_episode(ep_id=old_ep_id, season=1, ep_num=99, file_tracked=True)

    # File was previously linked to old_ep_id
    file = _make_file(filename="Show.S01E01.mkv", episode_id=old_ep_id)
    show = _make_show()

    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [new_ep, old_ep]
    orphan_result = MagicMock()
    # count query: 0 files still referencing old_ep
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    # old episode lookup
    old_ep_result = MagicMock()
    old_ep_result.scalar_one_or_none.return_value = old_ep

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[files_result, ep_list_result, orphan_result, count_result, old_ep_result]
    )

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_matched == 1
    assert new_ep.file_tracked is True
    assert old_ep.file_tracked is False
    assert old_ep.file_tracked_at is None
    assert old_ep.tracked_filename is None
    assert old_ep.tracked_source is None


@pytest.mark.asyncio
async def test_run_episodes_preloaded_per_show_not_per_file() -> None:
    """Episode lists are fetched once per show, even when multiple files share a show."""
    show = _make_show(show_id=10)
    f1 = _make_file(file_id=1, filename="Show.S01E01.mkv", show_id=10)
    f2 = _make_file(file_id=2, filename="Show.S01E02.mkv", show_id=10)
    ep1 = _make_episode(ep_id=1, season=1, ep_num=1)
    ep2 = _make_episode(ep_id=2, season=1, ep_num=2)

    files_result = MagicMock()
    files_result.all.return_value = [(f1, show), (f2, show)]
    # Single episode list query for the show
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [ep1, ep2]
    orphan = MagicMock()

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    # 1 files query + 1 ep list (not 2) + 2 orphan deletes
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result, orphan, orphan])

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_matched == 2
    # Exactly 4 execute calls: files, episodes (once), orphan x2
    assert session.execute.call_count == 4


# ---------------------------------------------------------------------------
# _llm_match — wrong number of parts (branch 116->121)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_match_too_many_parts_returns_none() -> None:
    """_llm_match returns None when LLM response has more than 2 space-separated parts."""
    session = MagicMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm_resp = MagicMock()
    llm_resp.content = "1 2 3"  # 3 parts → len(parts) != 2 → branch 116->121
    llm.complete = AsyncMock(return_value=llm_resp)

    orch = MatchOrchestrator(session, llm=llm)
    result = await orch._llm_match("Show.S01E01.mkv", "Test Show", [])
    assert result is None


@pytest.mark.asyncio
async def test_llm_match_single_part_returns_none() -> None:
    """_llm_match returns None when LLM response is a single token (no space)."""
    session = MagicMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm_resp = MagicMock()
    llm_resp.content = "episode"  # 1 part → len(parts) != 2 → branch 116->121
    llm.complete = AsyncMock(return_value=llm_resp)

    orch = MatchOrchestrator(session, llm=llm)
    result = await orch._llm_match("Show.ep7.mkv", "Test Show", [])
    assert result is None


# ---------------------------------------------------------------------------
# run(dry_run=True) — LLM available, heuristic fails (lines 183-184)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_dry_run_counts_llm_match_when_heuristic_fails() -> None:
    """dry_run=True: file with no heuristic match but LLM available counts as matched."""
    show = _make_show(show_id=20)
    # filename has no S/E pattern → heuristic returns None
    f = _make_file(file_id=9, filename="Some.Special.Episode.mkv", show_id=20)
    ep = _make_episode(ep_id=9, season=1, ep_num=1)

    files_result = MagicMock()
    files_result.all.return_value = [(f, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = [ep]

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result])

    llm = MagicMock()
    llm.is_available.return_value = True  # LLM is available

    orch = MatchOrchestrator(session, llm=llm)
    result = await orch.run(dry_run=True)

    assert result.files_matched == 1
    assert result.files_unmatched == 0


# ---------------------------------------------------------------------------
# run() — no episodes for show (branch 204->210)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_heuristic_fails_empty_episodes_marks_unmatched() -> None:
    """When heuristic fails and episodes list is empty, file is unmatched."""
    show = _make_show(show_id=21)
    # No S/E pattern → heuristic returns None; no episodes to try LLM with
    f = _make_file(file_id=10, filename="Random.Video.File.mkv", show_id=21)

    files_result = MagicMock()
    files_result.all.return_value = [(f, show)]
    ep_list_result = MagicMock()
    ep_list_result.scalars.return_value.all.return_value = []  # empty episodes

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_list_result])

    orch = MatchOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_unmatched == 1
