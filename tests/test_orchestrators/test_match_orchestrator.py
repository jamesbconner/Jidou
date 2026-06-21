"""Tests for ParseOrchestrator (filename parsing + show matching)."""

from unittest.mock import AsyncMock, MagicMock

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator, _heuristic_se, _sanitize_alias

# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def test_heuristic_se_sxxeyy():
    """S01E02 pattern extracts season=1 episode=2."""
    assert _heuristic_se("ShowName.S01E02.1080p.mkv") == (1, 2)


def test_heuristic_se_nxm():
    """NxM pattern extracts season=2 episode=5."""
    assert _heuristic_se("ShowName.2x05.1080p.mkv") == (2, 5)


def test_heuristic_se_no_match():
    """Returns None when no S/E pattern is found."""
    assert _heuristic_se("Movie.Title.2024.1080p.mkv") is None


def test_heuristic_se_avoids_resolution():
    """1920x1080 resolution string is not mistaken for an episode number."""
    assert _heuristic_se("ShowName.1920x1080.mkv") is None


def test_sanitize_alias():
    """Aliases are lowercased and stripped."""
    assert _sanitize_alias("  Attack on Titan  ") == "attack on titan"


# ---------------------------------------------------------------------------
# ParseOrchestrator integration tests
# ---------------------------------------------------------------------------


def _make_file(
    file_id=1,
    filename="Show.S01E01.mkv",
    status=FileStatus.DOWNLOADED,
):
    f = MagicMock()
    f.id = file_id
    f.original_filename = filename
    f.status = status
    f.show_id = None
    f.episode_id = None
    f.matched_by = None
    f.parsed_show_name = None
    f.parsed_season = None
    f.parsed_episode = None
    f.parsed_confidence = None
    f.parsed_content_type = None
    f.error_message = None
    return f


def _make_show(show_id=10, title="Test Show", aliases=None, local_path="/media/show"):
    s = MagicMock()
    s.id = show_id
    s.title = title
    s.aliases = aliases or []
    s.local_path = local_path
    return s


def _make_session(files=None, show=None, episode=None):
    """Return a mock session that yields files on first execute, then show/episode.

    show_result covers both the alias check (scalar_one_or_none) and the
    title-fallback (scalars().first()); both are wired to return *show*.
    """
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = files or []

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    # Wire scalars().first() for the title fallback path
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode

    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result] * 10)
    return session


async def test_run_no_llm_marks_unmatched():
    """Without LLM, heuristic name extracted but no DB match → file is UNMATCHED."""
    file1 = _make_file(filename="UnknownFile.S01E01.mkv")

    session = _make_session(files=[file1])

    orch = ParseOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_unmatched == 1
    assert result.files_matched == 0
    assert file1.status == FileStatus.UNMATCHED


async def test_run_dry_run_does_not_commit():
    """Dry run logs results without committing."""
    file1 = _make_file()

    session = _make_session(files=[file1])

    orch = ParseOrchestrator(session, llm=None)
    result = await orch.run(dry_run=True)

    session.commit.assert_not_called()
    assert result.dry_run is True


async def test_run_with_llm_and_matched_show():
    """When LLM returns a show name and DB finds it, file is MATCHED."""
    file1 = _make_file(filename="Attack.on.Titan.S01E01.1080p.mkv")
    show = _make_show(title="Attack on Titan")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            file_result,
            show_result,  # alias check
            show_result,  # title fallback
            ep_result,  # episode lookup
        ]
    )

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show": "Attack on Titan", "season": 1, "episode": 1, '
        '"content_type": "anime", "confidence": 0.95}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED
    assert file1.show_id == show.id
    assert file1.parsed_show_name == "Attack on Titan"
    assert file1.parsed_season == 1
    assert file1.parsed_episode == 1
    assert file1.parsed_content_type == "anime"


async def test_run_exception_marks_error():
    """An exception during parsing sets file status to ERROR."""
    file1 = _make_file()

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, RuntimeError("DB error")])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show": "Some Show", "season": 1, "episode": 1, "content_type": "tv", "confidence": 0.9}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_failed == 1
    assert file1.status == FileStatus.ERROR


async def test_run_on_progress_called_per_file():
    """on_progress callback is called once per file."""
    file1 = _make_file(file_id=1, filename="ep1.mkv")
    file2 = _make_file(file_id=2, filename="ep2.mkv")

    session = _make_session(files=[file1, file2])
    on_progress = AsyncMock()

    orch = ParseOrchestrator(session, llm=None)
    await orch.run(on_progress=on_progress)

    assert on_progress.call_count == 2
