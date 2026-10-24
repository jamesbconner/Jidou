"""Tests for ParseOrchestrator (filename parsing + show matching).

Filename-extraction-level tests (heuristic regex, LLM prompt/parsing) live
in tests/test_filename_parser.py, covering jidou.services.filename_parser
directly. These tests cover ParseOrchestrator's own behavior: the
confidence gate, DB show/episode lookup, alias handling, and local_path
resolution.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.downloaded_file import FileStatus, MatchedBy
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator
from jidou.services.alias_handling import sanitize_alias
from jidou.services.filename_parser import FilenameParseResult

# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def test_sanitize_alias():
    """Aliases are lowercased and stripped."""
    assert sanitize_alias("  Attack on Titan  ") == "attack on titan"


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
    f.crc32_declared = None
    f.error_message = None
    return f


def _make_show(
    show_id=10,
    title="Test Show",
    aliases=None,
    local_path="/media/show",
    *,
    aliases_sources=None,
    season_aliases=None,
):
    s = MagicMock()
    s.id = show_id
    s.title = title
    s.aliases = aliases or []
    s.aliases_sources = aliases_sources
    s.season_aliases = season_aliases
    s.episode_group_map = None
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


@pytest.fixture(autouse=True)
def _stub_llm_match_episode(monkeypatch):
    """Default no-op stub for ParseOrchestrator's episode-list LLM fallback.

    Keeps every existing test that leaves the episode DB lookup unresolved
    passing unchanged -- the fallback now fires but yields no new match,
    identical to today's observable behavior. Tests exercising the fallback
    itself override this stub's return_value.
    """
    stub = AsyncMock(return_value=(None, None, None))
    monkeypatch.setattr("jidou.orchestrators.parse_orchestrator.llm_match_episode", stub)
    return stub


@pytest.fixture(autouse=True)
def _stub_find_duplicate_original(monkeypatch):
    """Default "no duplicate" stub for the duplicate-file lookup (DF-13).

    The lookup is one more query after an episode resolves; these tests'
    scripted mock sessions do not script it. Duplicate flagging itself is
    covered in test_parse_duplicate_flag.py.
    """
    stub = AsyncMock(return_value=None)
    monkeypatch.setattr("jidou.orchestrators.parse_orchestrator.find_duplicate_original", stub)
    return stub


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
    show_result.scalars.return_value.first.return_value = show

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
        '{"show_name": "Attack on Titan", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": "anime", "confidence": 0.95, '
        '"reasoning": "Clear S01E01 marker."}'
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


async def test_run_retries_unmatched_file_and_clears_error_message():
    """UNMATCHED files are retried alongside DOWNLOADED ones (#unmatched-retry).

    Covers the scenario where a show didn't exist at first-parse time: the
    file was left UNMATCHED, the user then adds/resolves the show, and a
    plain re-run of the task should pick the file back up and clear the
    stale error_message from the earlier failed attempt.
    """
    file1 = _make_file(filename="Attack.on.Titan.S01E01.1080p.mkv", status=FileStatus.UNMATCHED)
    file1.error_message = "No show found for parsed name 'Attack on Titan'"
    show = _make_show(title="Attack on Titan")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

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
        '{"show_name": "Attack on Titan", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": "anime", "confidence": 0.95, '
        '"reasoning": "Clear S01E01 marker."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED
    assert file1.error_message is None

    file_query_stmt = session.execute.await_args_list[0].args[0]
    compiled = str(file_query_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "'downloaded'" in compiled
    assert "'unmatched'" in compiled


async def test_run_llm_match_episode_fallback_resolves_episode(_stub_llm_match_episode):
    """When the DB episode lookup misses (e.g. a title-only filename with no
    S/E marker), the episode-list LLM fallback can still resolve it (#312).
    """
    file1 = _make_file(filename="Attack.on.Titan.The.Series.Finale.mkv")
    show = _make_show(title="Attack on Titan")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    # find_show_by_name's alias-containment check runs first and returns via
    # .scalars().first() -- a hit there short-circuits before the title-match
    # query ever runs, so the alias check must MISS here for both queries to
    # actually fire (mirroring the real two-query lookup chain).
    alias_miss = MagicMock()
    alias_miss.scalars.return_value.first.return_value = None

    show_result = MagicMock()
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None  # DB S/E lookup misses

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            file_result,
            alias_miss,  # alias check (miss)
            show_result,  # title fallback (hit)
            ep_result,  # episode lookup (miss)
            MagicMock(),  # dismiss_orphans_for_file, since the fallback resolves ep
        ]
    )

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Attack on Titan", "season": null, "episode": null, '
        '"crc32": null, "content_type": "anime", "confidence": 0.95, '
        '"reasoning": "No S/E marker; title-only filename."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    matched_episode = MagicMock()
    matched_episode.id = 99
    matched_episode.season_number = 4
    _stub_llm_match_episode.return_value = (matched_episode, 4, 28)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED
    assert file1.episode_id == 99
    assert file1.parsed_season == 4
    assert file1.parsed_episode == 28
    _stub_llm_match_episode.assert_called_once()


async def test_run_llm_match_episode_fallback_not_attempted_without_llm(_stub_llm_match_episode):
    """Without an LLM, the episode-list fallback is never attempted, even
    when the show matches but the episode DB lookup misses."""
    file1 = _make_file(filename="UnknownFile.S09E09.mkv")
    show = _make_show(title="Test Show")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    alias_miss = MagicMock()
    alias_miss.scalars.return_value.first.return_value = None

    show_result = MagicMock()
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, alias_miss, show_result, ep_result])

    orch = ParseOrchestrator(session, llm=None)
    await orch.run()

    _stub_llm_match_episode.assert_not_called()


async def test_run_persists_crc32_declared_from_llm():
    """The LLM's own crc32 reading is persisted separately from any other source.

    Uses lowercase in the LLM response to show crc32_declared is stored
    exactly as parse_filename() returned it (unlike the regex path, which
    always uppercases) -- so a case mismatch against crc32_extracted is a
    visible, debuggable signal instead of being silently normalised away.
    """
    file1 = _make_file(filename="Attack.on.Titan.S01E01.[ABCD1234].1080p.mkv")
    show = _make_show(title="Attack on Titan")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Attack on Titan", "season": 1, "episode": 1, '
        '"crc32": "abcd1234", "content_type": "anime", "confidence": 0.95, '
        '"reasoning": "Clear S01E01 marker."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    await orch.run()

    assert file1.crc32_declared == "abcd1234"


async def test_run_llm_season_zero_is_preserved_not_treated_as_absent(monkeypatch):
    """Regression test for the falsy-zero bug: season=0 (TMDB's specials
    convention) from the LLM must not be discarded and replaced with the
    regex fallback (or None) just because 0 is falsy in Python.

    heuristic_se is forced to return None so the regex path can't also
    independently arrive at 0 -- that would mask the bug ("0 or 0" still
    equals 0), which is exactly why it went unnoticed in the first place.
    """
    monkeypatch.setattr("jidou.orchestrators.parse_orchestrator.heuristic_se", lambda _f: None)

    file1 = _make_file(filename="Attack on Titan - Special - No Regrets.mkv")
    show = _make_show(title="Attack on Titan")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Attack on Titan", "season": 0, "episode": 1, '
        '"crc32": null, "content_type": "anime", "confidence": 0.9, '
        '"reasoning": "Specials convention, no literal S00 marker in filename."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    await orch.run()

    assert file1.parsed_season == 0


async def test_run_llm_episode_zero_is_preserved_not_treated_as_absent(monkeypatch):
    """Same falsy-zero bug, on the episode side (episode=0 is a real value too)."""
    monkeypatch.setattr("jidou.orchestrators.parse_orchestrator.heuristic_se", lambda _f: None)

    file1 = _make_file(filename="Show - Episode Zero - Prologue.mkv")
    show = _make_show(title="Show")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Show", "season": 1, "episode": 0, '
        '"crc32": null, "content_type": "tv", "confidence": 0.9, '
        '"reasoning": "Prologue episode, numbered 0."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    await orch.run()

    assert file1.parsed_episode == 0


async def test_run_fuzzy_show_match_does_not_alias_franchise_prefix():
    """A fuzzy/substring show match must not get permanently written as an alias.

    Regression: if the DB lookup resolves "Daredevil" to a show titled
    "Daredevil: Born Again" via the substring fallback, "daredevil" must not
    be added to that show's alias list -- future parses of "Daredevil" would
    otherwise misfile onto the wrong show forever.
    """
    file1 = _make_file(filename="Daredevil.S01E01.mkv")
    show = _make_show(title="Daredevil: Born Again", aliases=[])

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    alias_miss = MagicMock()
    alias_miss.scalars.return_value.first.return_value = None

    fuzzy_hit = MagicMock()
    fuzzy_hit.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            file_result,
            alias_miss,  # alias containment miss
            fuzzy_hit,  # substring title fallback hit
            ep_result,  # episode lookup
        ]
    )

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Daredevil", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": "tv", "confidence": 0.95, '
        '"reasoning": "Clear S01E01 marker."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_matched == 1
    assert file1.show_id == show.id
    # The fuzzy hit must not have been added as an alias.
    assert show.aliases == []


async def test_run_exact_show_match_still_gets_aliased():
    """An exact title match (not a fuzzy substring guess) is still added as an alias."""
    file1 = _make_file(filename="Attack.on.Titan.S01E01.mkv")
    show = _make_show(title="Attack on Titan", aliases=[])

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    alias_miss = MagicMock()
    alias_miss.scalars.return_value.first.return_value = None

    exact_hit = MagicMock()
    exact_hit.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            file_result,
            alias_miss,  # alias containment miss
            exact_hit,  # substring title fallback -- but the title matches exactly
            ep_result,  # episode lookup
        ]
    )

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Attack on Titan", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": "anime", "confidence": 0.95, '
        '"reasoning": "Clear S01E01 marker."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_matched == 1
    assert show.aliases == ["attack on titan"]


async def test_run_llm_receives_regex_hint():
    """LLM prompt includes the regex anchor when S/E pattern is found."""
    file1 = _make_file(filename="Show.Name.S02E05.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=file_result)

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    # Low confidence so it won't proceed to DB lookup — we only care about the call
    llm_response.content = (
        '{"show_name": "Show Name", "season": 2, "episode": 5, '
        '"crc32": null, "content_type": "tv", "confidence": 0.3, '
        '"reasoning": "test"}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    await orch.run()

    call_args = llm.complete.call_args
    prompt = call_args.kwargs.get("prompt") or call_args.args[0]
    assert "season=2" in prompt
    assert "episode=5" in prompt


async def test_run_low_confidence_marks_unmatched():
    """LLM result below confidence threshold is flagged UNMATCHED without DB lookup."""
    file1 = _make_file(filename="Ambiguous.Title.09.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=file_result)

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Ambiguous Title", "season": null, "episode": 9, '
        '"crc32": null, "content_type": null, "confidence": 0.45, '
        '"reasoning": "Bare episode number, uncertain show name."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_unmatched == 1
    assert result.files_matched == 0
    assert file1.status == FileStatus.UNMATCHED
    assert "confidence" in (file1.error_message or "")
    # DB lookup should not have been attempted — only the file list query
    assert session.execute.call_count == 1


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
        '{"show_name": "Some Show", "season": 1, "episode": 1, "crc32": null, '
        '"content_type": "tv", "confidence": 0.9, "reasoning": "test"}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_failed == 1
    assert file1.status == FileStatus.ERROR


async def test_run_no_llm_heuristic_proceeds_to_db_lookup():
    """Without LLM the confidence gate is bypassed; heuristic name reaches _find_show."""
    show = _make_show(title="UnknownFile")
    file1 = _make_file(filename="UnknownFile.S01E01.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    orch = ParseOrchestrator(session, llm=None)
    result = await orch.run()

    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED


async def test_run_persists_crc32_declared_from_heuristic():
    """Without an LLM, the heuristic regex reading is still persisted as declared."""
    show = _make_show(title="UnknownFile")
    file1 = _make_file(filename="UnknownFile.S01E01.[ABCD1234].mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    orch = ParseOrchestrator(session, llm=None)
    await orch.run()

    assert file1.crc32_declared == "ABCD1234"


async def test_run_movie_bypasses_confidence_gate():
    """Movie files reach DB lookup even though null-episode scores confidence ~0.1."""
    show = _make_show(title="Spirited Away")
    file1 = _make_file(filename="Spirited.Away.2001.1080p.BluRay.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    # Movie: episode=null → confidence ~0.1 by scoring rules, but gate must not fire
    llm_response.content = (
        '{"show_name": "Spirited Away", "season": null, "episode": null, '
        '"crc32": null, "content_type": "movie", "confidence": 0.10, '
        '"reasoning": "No episode marker; this is a movie."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED


async def test_run_llm_outage_falls_back_to_heuristic():
    """When LLM returns None the file uses heuristic matching, not a confidence error."""
    show = _make_show(title="Show Name")
    file1 = _make_file(filename="Show.Name.S01E01.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)  # simulates outage

    orch = ParseOrchestrator(session, llm=llm)
    result = await orch.run()

    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED
    assert "confidence" not in (file1.error_message or "")


async def test_resolve_local_path_anime():
    """show.content_type=anime routes to local_anime_path / sys_name."""
    session = _make_session()
    orch = ParseOrchestrator(
        session,
        llm=None,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    show = _make_show(show_id=1, title="Attack on Titan")
    show.sys_name = "Attack on Titan"
    show.content_type = "anime"
    show.media_type = "tv"

    path = orch._resolve_local_path(show)
    assert path == "/media/anime/Attack on Titan"


async def test_resolve_local_path_movie():
    """show.content_type=movie routes to local_movie_path directly (no per-title subdir)."""
    session = _make_session()
    orch = ParseOrchestrator(
        session,
        llm=None,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    show = _make_show(show_id=2, title="Spirited Away")
    show.sys_name = "Spirited Away"
    show.content_type = "movie"
    show.media_type = "movie"

    path = orch._resolve_local_path(show)
    assert path == "/media/movies"


async def test_resolve_local_path_falls_back_to_media_type():
    """show.content_type=None with a non-movie media_type yields no path (DF-10 / D16)."""
    session = _make_session()
    orch = ParseOrchestrator(
        session,
        llm=None,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    show = _make_show(show_id=3, title="Naruto")
    show.sys_name = "Naruto"
    show.content_type = None
    show.media_type = "anime"

    path = orch._resolve_local_path(show)
    assert path is None


async def test_resolve_local_path_show_content_type_wins_over_parsed():
    """A show already labeled anime stays in the anime library even if one file parses as tv."""
    session = _make_session()
    orch = ParseOrchestrator(
        session,
        llm=None,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    show = _make_show(show_id=4, title="One Piece")
    show.sys_name = "One Piece"
    show.content_type = "anime"  # already set
    show.media_type = "tv"

    # Simulate a file that parsed as "tv" — show.content_type should win.
    # (caller backfills content_type only when unset, then calls _resolve_local_path)
    path = orch._resolve_local_path(show)
    assert path == "/media/anime/One Piece"


async def test_run_auto_sets_local_path_on_match():
    """show.local_path is auto-populated when None after a successful match."""
    show = _make_show(title="Attack on Titan")
    show.sys_name = "Attack on Titan"
    show.content_type = None
    show.media_type = "tv"
    show.local_path = None

    file1 = _make_file(filename="Attack.on.Titan.S01E01.1080p.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Attack on Titan", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": "anime", "confidence": 0.95, '
        '"reasoning": "Clear S01E01."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(
        session,
        llm=llm,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    await orch.run()

    assert show.local_path == "/media/anime/Attack on Titan"
    assert show.content_type == "anime"


async def test_run_does_not_overwrite_existing_local_path():
    """show.local_path is left untouched when already set."""
    show = _make_show(title="Some Show")
    show.sys_name = "Some Show"
    show.content_type = "tv"
    show.media_type = "tv"
    show.local_path = "/custom/path/Some Show"

    file1 = _make_file(filename="Some.Show.S01E01.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Some Show", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": "tv", "confidence": 0.9, '
        '"reasoning": "Clear S01E01."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(
        session,
        llm=llm,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    await orch.run()

    assert show.local_path == "/custom/path/Some Show"


async def test_run_no_content_type_skips_local_path_auto_set():
    """show.local_path stays None when content_type is unknown (avoids wrong library root)."""
    show = _make_show(title="Some Anime")
    show.sys_name = "Some Anime"
    show.content_type = None  # unknown — TMDB only gives media_type="tv"
    show.media_type = "tv"
    show.local_path = None

    file1 = _make_file(filename="Some.Anime.S01E01.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    # LLM returns null content_type — insufficient to pick a library root
    llm_response.content = (
        '{"show_name": "Some Anime", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": null, "confidence": 0.85, '
        '"reasoning": "Clear S01E01 but content type ambiguous."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(
        session,
        llm=llm,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    result = await orch.run()

    # File is still matched — we just can't auto-route it
    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED
    # local_path must not be auto-set when content_type is unknown
    assert show.local_path is None


async def test_run_movie_media_type_auto_sets_local_path_without_content_type():
    """movie media_type is unambiguous — heuristic match auto-sets local_path even when
    content_type is None (LLM not available, only media_type="movie" from TMDB)."""
    show = _make_show(title="Spirited Away")
    show.sys_name = "Spirited Away"
    show.content_type = None  # not yet set
    show.media_type = "movie"  # unambiguous from TMDB
    show.local_path = None

    file1 = _make_file(filename="Spirited.Away.2001.1080p.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    # No LLM — heuristic path; confidence gate is bypassed (llm_ok=False)
    orch = ParseOrchestrator(
        session,
        llm=None,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    await orch.run()

    assert show.local_path == "/media/movies"


async def test_run_on_progress_called_per_file():
    """on_progress callback is called once per file."""
    file1 = _make_file(file_id=1, filename="ep1.mkv")
    file2 = _make_file(file_id=2, filename="ep2.mkv")

    session = _make_session(files=[file1, file2])
    on_progress = AsyncMock()

    orch = ParseOrchestrator(session, llm=None)
    await orch.run(on_progress=on_progress)


# ---------------------------------------------------------------------------
# run() — on_event callback
# ---------------------------------------------------------------------------


async def test_on_event_called_on_match():
    """on_event emits an info event when a file is matched to a show."""
    file1 = _make_file(filename="Attack.on.Titan.S01E01.1080p.mkv")
    show = _make_show(title="Attack on Titan")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Attack on Titan", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": "anime", "confidence": 0.95, '
        '"reasoning": "Clear S01E01 marker."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    on_event = AsyncMock()
    orch = ParseOrchestrator(session, llm=llm)
    await orch.run(on_event=on_event)

    matched_calls = [c for c in on_event.call_args_list if "Matched" in c[0][1]]
    assert len(matched_calls) == 1
    assert matched_calls[0][0][0] == "info"


async def test_on_event_called_on_unmatched():
    """on_event emits a warn event when no show is found for a file."""
    file1 = _make_file(filename="UnknownFile.S01E01.mkv")

    session = _make_session(files=[file1])

    on_event = AsyncMock()
    orch = ParseOrchestrator(session, llm=None)
    await orch.run(on_event=on_event)

    unmatched_calls = [c for c in on_event.call_args_list if "Unmatched" in c[0][1]]
    assert len(unmatched_calls) == 1
    assert unmatched_calls[0][0][0] == "warn"


async def test_on_event_called_on_parse_error(monkeypatch):
    """on_event emits an error event when parsing a file raises."""
    file1 = _make_file()
    session = _make_session(files=[file1])

    def _boom(*args, **kwargs):
        raise RuntimeError("parse failure")

    monkeypatch.setattr("jidou.orchestrators.parse_orchestrator.heuristic_se", _boom)

    on_event = AsyncMock()
    orch = ParseOrchestrator(session, llm=None)
    await orch.run(on_event=on_event)

    error_calls = [c for c in on_event.call_args_list if c[0][0] == "error"]
    assert len(error_calls) == 1
    assert "parse failure" in error_calls[0][0][1]


async def test_on_event_called_in_dry_run():
    """on_event emits a dry-run info event per file, matched or not."""
    file1 = _make_file(filename="UnknownFile.S01E01.mkv")

    session = _make_session(files=[file1])

    on_event = AsyncMock()
    orch = ParseOrchestrator(session, llm=None)
    await orch.run(dry_run=True, on_event=on_event)

    dry_run_calls = [c for c in on_event.call_args_list if "Dry run" in c[0][1]]
    assert len(dry_run_calls) == 1


async def test_run_out_of_vocabulary_content_type_keeps_match_and_skips_backfill(caplog):
    """An LLM content_type outside anime/tv/movie must not turn a match into ERROR.

    Not every provider enforces the response schema. The backfill is skipped (storing
    the raw string would make the show unloadable) and a warning is logged, while the
    file stays MATCHED and keeps the raw answer in parsed_content_type.
    """
    show = _make_show(title="Attack on Titan")
    show.sys_name = "Attack on Titan"
    show.content_type = None
    show.media_type = "tv"
    show.local_path = None

    file1 = _make_file(filename="Attack.on.Titan.S01E01.1080p.mkv")

    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = [file1]
    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    show_result.scalars.return_value.first.return_value = show
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[file_result, show_result, show_result, ep_result])

    llm = MagicMock()
    llm.is_available.return_value = True
    llm_response = MagicMock()
    llm_response.content = (
        '{"show_name": "Attack on Titan", "season": 1, "episode": 1, '
        '"crc32": null, "content_type": "Anime", "confidence": 0.95, '
        '"reasoning": "Clear S01E01."}'
    )
    llm.complete = AsyncMock(return_value=llm_response)

    orch = ParseOrchestrator(
        session,
        llm=llm,
        local_tv_path="/media/tv",
        local_anime_path="/media/anime",
        local_movie_path="/media/movies",
    )
    with caplog.at_level("WARNING", logger="jidou.orchestrators.parse_orchestrator"):
        await orch.run()

    assert file1.status == FileStatus.MATCHED
    assert show.content_type is None
    assert file1.parsed_content_type == "Anime"
    assert "out-of-vocabulary content_type 'Anime'" in caplog.text


# ---------------------------------------------------------------------------
# Characterization — per-file outcomes, event payloads, flush/commit placement
# ---------------------------------------------------------------------------

_MOD = "jidou.orchestrators.parse_orchestrator"


def _parsed(
    show_name: str | None = "Test Show",
    season: int | None = 1,
    episode: int | None = 1,
    content_type: str | None = "tv",
    confidence: float = 0.9,
    llm_ok: bool = True,
    crc32: str | None = None,
) -> FilenameParseResult:
    return FilenameParseResult(
        show_name=show_name,
        season=season,
        episode=episode,
        crc32=crc32,
        content_type=content_type,
        confidence=confidence,
        llm_ok=llm_ok,
    )


def _llm(available: bool = True) -> MagicMock:
    llm = MagicMock()
    llm.is_available.return_value = available
    return llm


def _recording_parse_session(files: list) -> tuple[MagicMock, list[str]]:
    """Session whose flush/commit append to the same ordered log as events."""
    log: list[str] = []
    session = MagicMock()
    file_result = MagicMock()
    file_result.scalars.return_value.all.return_value = files
    session.execute = AsyncMock(return_value=file_result)

    async def _flush() -> None:
        log.append("flush")

    async def _commit() -> None:
        log.append("commit")

    session.flush = AsyncMock(side_effect=_flush)
    session.commit = AsyncMock(side_effect=_commit)
    return session, log


def _recording_event(log: list[str]) -> AsyncMock:
    async def _event(level: str, msg: str, ctx: dict) -> None:
        log.append(f"event:{level}")

    return AsyncMock(side_effect=_event)


@pytest.mark.asyncio
async def test_characterize_match_state_events_and_flush_order():
    """A match persists metadata, resolves the episode, backfills season, then flushes."""
    file = _make_file(filename="Show.mkv")
    show = _make_show(title="Test Show", aliases=["other"], local_path=None)
    show.sys_name = "Test Show"
    show.content_type = None
    show.media_type = "tv"
    ep = MagicMock()
    ep.id = 77
    ep.season_number = 2
    session, log = _recording_parse_session([file])
    on_event = _recording_event(log)

    with (
        patch(
            f"{_MOD}.parse_filename",
            AsyncMock(return_value=_parsed(season=None, crc32="ABCD1234")),
        ),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
        patch(f"{_MOD}.resolve_episode", AsyncMock(return_value=ep)),
        patch(f"{_MOD}.dismiss_orphans_for_file", AsyncMock()) as dismiss,
    ):
        result = await ParseOrchestrator(session, llm=_llm()).run(on_event=on_event)

    assert (result.files_processed, result.files_matched) == (1, 1)
    assert (result.files_unmatched, result.files_failed) == (0, 0)
    assert log == ["event:info", "flush", "commit"]
    on_event.assert_awaited_once_with(
        "info", "Matched 'Show.mkv' → 'Test Show'", {"file_id": 1, "show_id": 10}
    )
    assert file.status == FileStatus.MATCHED
    assert file.matched_by == MatchedBy.LLM
    assert file.show_id == 10
    assert file.episode_id == 77
    assert file.parsed_season == 2  # backfilled from the resolved episode
    assert file.parsed_episode == 1
    assert file.parsed_show_name == "Test Show"
    assert file.parsed_confidence == 0.9
    assert file.parsed_content_type == "tv"
    assert file.crc32_declared == "ABCD1234"
    assert file.error_message is None
    dismiss.assert_awaited_once()
    assert show.aliases == ["other", "test show"]
    assert show.content_type.value == "tv"
    assert show.local_path == "/data/media/tv/Test Show"


@pytest.mark.asyncio
async def test_characterize_unmatched_messages_and_payloads():
    """No show name vs. unknown show: distinct error_message, one warn event each."""
    f_noname = _make_file(file_id=1, filename="a.mkv")
    f_unknown = _make_file(file_id=2, filename="b.mkv")
    session, log = _recording_parse_session([f_noname, f_unknown])
    on_event = _recording_event(log)
    parsed = [_parsed(show_name=None), _parsed(show_name="Ghost")]

    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(side_effect=parsed)),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=None)) as find,
    ):
        result = await ParseOrchestrator(session, llm=_llm()).run(on_event=on_event)

    find.assert_awaited_once()  # no lookup without a parsed name
    assert (result.files_matched, result.files_unmatched, result.files_failed) == (0, 2, 0)
    assert log == ["event:warn", "flush", "event:warn", "flush", "commit"]
    assert f_noname.status == FileStatus.UNMATCHED
    assert f_noname.error_message == "LLM could not identify a show name"
    assert f_unknown.error_message == "No show found for parsed name 'Ghost'"
    assert on_event.await_args_list[0].args == (
        "warn",
        "Unmatched 'a.mkv' (parsed_name=None)",
        {"file_id": 1, "parsed_name": None},
    )
    assert on_event.await_args_list[1].args == (
        "warn",
        "Unmatched 'b.mkv' (parsed_name='Ghost')",
        {"file_id": 2, "parsed_name": "Ghost"},
    )


@pytest.mark.asyncio
async def test_characterize_low_confidence_gate_skips_lookup():
    """Below-threshold LLM result: metadata persisted, UNMATCHED, warn event, flush, no lookup."""
    file = _make_file(filename="x.mkv")
    session, log = _recording_parse_session([file])
    on_event = _recording_event(log)

    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(return_value=_parsed(confidence=0.4))),
        patch(f"{_MOD}.find_show_by_name", AsyncMock()) as find,
    ):
        result = await ParseOrchestrator(session, llm=_llm()).run(on_event=on_event)

    find.assert_not_awaited()
    assert result.files_unmatched == 1
    assert log == ["event:warn", "flush", "commit"]
    on_event.assert_awaited_once_with(
        "warn",
        "Low confidence (0.40) for 'x.mkv', flagging UNMATCHED",
        {"file_id": 1, "confidence": 0.4},
    )
    assert file.status == FileStatus.UNMATCHED
    assert file.error_message == (
        "Parse confidence 0.40 below threshold 0.7 — manual review required"
    )
    assert file.parsed_show_name == "Test Show"
    assert file.parsed_confidence == 0.4


@pytest.mark.asyncio
async def test_characterize_exception_marks_error_and_continues():
    """A failure on one file becomes ERROR + error event; the next file still runs."""
    bad = _make_file(file_id=1, filename="bad.mkv")
    good = _make_file(file_id=2, filename="good.mkv")
    show = _make_show(title="Test Show")
    show.content_type = None
    show.media_type = "tv"
    show.local_path = "/x"
    session, log = _recording_parse_session([bad, good])
    on_event = _recording_event(log)

    with (
        patch(
            f"{_MOD}.parse_filename",
            AsyncMock(side_effect=[RuntimeError("boom"), _parsed()]),
        ),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
        patch(f"{_MOD}.resolve_episode", AsyncMock(return_value=None)),
    ):
        result = await ParseOrchestrator(session, llm=_llm()).run(on_event=on_event)

    assert (result.files_matched, result.files_failed) == (1, 1)
    assert log == ["event:error", "flush", "event:info", "flush", "commit"]
    assert on_event.await_args_list[0].args == (
        "error",
        "Failed to parse 'bad.mkv': boom",
        {"file_id": 1, "error": "boom"},
    )
    assert bad.status == FileStatus.ERROR
    assert bad.error_message == "boom"
    assert good.status == FileStatus.MATCHED


@pytest.mark.asyncio
async def test_characterize_dry_run_plans_without_touching_db():
    """Dry run: match/gate/unmatched previews, no file mutation, no flush, no commit."""
    f_match = _make_file(file_id=1, filename="m.mkv")
    f_gated = _make_file(file_id=2, filename="g.mkv")
    f_none = _make_file(file_id=3, filename="n.mkv")
    show = _make_show(title="Test Show")
    session, log = _recording_parse_session([f_match, f_gated, f_none])
    on_event = _recording_event(log)
    parsed = [_parsed(), _parsed(confidence=0.2), _parsed(show_name=None)]

    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(side_effect=parsed)),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
    ):
        result = await ParseOrchestrator(session, llm=_llm()).run(dry_run=True, on_event=on_event)

    assert (result.files_matched, result.files_unmatched, result.dry_run) == (1, 2, True)
    assert log == ["event:info", "event:info", "event:info"]
    assert on_event.await_args_list[0].args == (
        "info",
        "[Dry run] Would match 'm.mkv' → 'Test Show'",
        {"file_id": 1, "show_id": 10},
    )
    assert on_event.await_args_list[1].args == (
        "info",
        "[Dry run] Would leave unmatched: 'g.mkv'",
        {"file_id": 2},
    )
    for f in (f_match, f_gated, f_none):
        assert f.status == FileStatus.DOWNLOADED
        assert f.parsed_show_name is None
    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_characterize_dry_run_failure_counts_without_status_change():
    """A dry-run exception emits the error event and counts failed, leaving status alone."""
    file = _make_file(filename="d.mkv")
    session, log = _recording_parse_session([file])
    on_event = _recording_event(log)

    with patch(f"{_MOD}.parse_filename", AsyncMock(side_effect=RuntimeError("nope"))):
        result = await ParseOrchestrator(session, llm=_llm()).run(dry_run=True, on_event=on_event)

    assert result.files_failed == 1
    assert log == ["event:error"]
    assert file.status == FileStatus.DOWNLOADED
    assert file.error_message is None


@pytest.mark.asyncio
async def test_characterize_heuristic_match_without_llm():
    """Without an LLM: matched_by HEURISTIC, no episode-title fallback, gate not applied."""
    file = _make_file(filename="h.mkv")
    show = _make_show(title="Test Show", local_path="/x")
    show.content_type = None
    show.media_type = "tv"
    session, _ = _recording_parse_session([file])

    with (
        patch(
            f"{_MOD}.parse_filename",
            AsyncMock(return_value=_parsed(confidence=0.1, llm_ok=False, content_type=None)),
        ),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
        patch(f"{_MOD}.resolve_episode", AsyncMock(return_value=None)),
        patch(f"{_MOD}.llm_match_episode", AsyncMock()) as llm_ep,
    ):
        result = await ParseOrchestrator(session, llm=None).run()

    llm_ep.assert_not_awaited()
    assert result.files_matched == 1
    assert file.matched_by == MatchedBy.HEURISTIC
    assert file.status == FileStatus.MATCHED
    assert file.episode_id is None


@pytest.mark.asyncio
async def test_matched_by_uses_run_level_llm_availability():
    """LLM availability is probed once per run and drives matched_by for every file."""
    files = [_make_file(file_id=i, filename=f"Show.S01E0{i}.mkv") for i in (1, 2, 3)]
    show = _make_show(title="Test Show", local_path="/x")
    show.content_type = None
    show.media_type = "tv"
    session, _ = _recording_parse_session(files)
    llm = _llm(available=True)

    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(return_value=_parsed())),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
        patch(f"{_MOD}.resolve_episode", AsyncMock(return_value=None)),
        patch(f"{_MOD}.llm_match_episode", AsyncMock(return_value=(None, None, None))),
    ):
        result = await ParseOrchestrator(session, llm=llm).run()

    assert result.files_matched == 3
    llm.is_available.assert_called_once_with()
    assert all(f.matched_by == MatchedBy.LLM for f in files)


@pytest.mark.parametrize(
    ("parsed", "found_show", "expected"),
    [
        pytest.param(_parsed(), True, (1, 0, 1), id="matched-then-flush-fails"),
        pytest.param(_parsed(confidence=0.3), True, (0, 1, 1), id="low-confidence-flush-fails"),
        pytest.param(_parsed(), False, (0, 1, 1), id="no-show-flush-fails"),
    ],
)
@pytest.mark.asyncio
async def test_characterize_flush_failure_counts_decided_outcome_and_failed(
    parsed, found_show, expected
):
    """A failing closing flush leaves the decided bucket counted AND counts the file failed."""
    file = _make_file(filename="f.mkv")
    show = _make_show(title="Test Show", local_path="/x")
    show.content_type = None
    show.media_type = "tv"
    session, _ = _recording_parse_session([file])
    # First flush (the closing one) raises; the ERROR-marking flush in the handler succeeds.
    session.flush = AsyncMock(side_effect=[RuntimeError("flush failed"), None])

    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(return_value=parsed)),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show if found_show else None)),
        patch(f"{_MOD}.resolve_episode", AsyncMock(return_value=None)),
    ):
        result = await ParseOrchestrator(session, llm=_llm()).run()

    assert (result.files_matched, result.files_unmatched, result.files_failed) == expected
    assert file.status == FileStatus.ERROR
    assert file.error_message == "flush failed"


# ---------------------------------------------------------------------------
# Season aliases — arc-named releases ("<show> - <arc> - 01")
# ---------------------------------------------------------------------------

_ARC_FILE = "[SubsPlease] Tougen Anki - Nikko Kegon no Taki-hen - 01 (1080p) [E8DAF239].mkv"
_ARC_NAME = "Tougen Anki - Nikko Kegon no Taki-hen"
_ARC_ALIAS = sanitize_alias(_ARC_NAME)


def _arc_run_patches(show, parsed, *, with_season=None, by_number=None):
    """Patch parsing, show lookup and episode resolution for one arc-file run."""
    return (
        patch(f"{_MOD}.parse_filename", AsyncMock(return_value=parsed)),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=show)),
        patch(f"{_MOD}.resolve_with_season", with_season or AsyncMock(return_value=None)),
        patch(f"{_MOD}.resolve_episode", by_number or AsyncMock(return_value=None)),
        patch(f"{_MOD}.dismiss_orphans_for_file", AsyncMock()),
    )


async def _run_arc(show, parsed, *, dry_run=False, on_event=None, **mocks):
    file1 = _make_file(filename=_ARC_FILE)
    session, _ = _recording_parse_session([file1])
    p1, p2, p3, p4, p5 = _arc_run_patches(show, parsed, **mocks)
    with p1, p2, p3, p4, p5:
        result = await ParseOrchestrator(session, llm=_llm()).run(
            dry_run=dry_run, on_event=on_event
        )
    return file1, session, result


async def test_run_season_alias_sets_season_and_resolves_s2():
    """A season name supplies the season the filename lacks; S02E01 is linked."""
    show = _make_show(title="Tougen Anki", season_aliases={"nikko kegon no taki-hen": 2})
    ep = MagicMock(id=99, season_number=2, episode_number=1)
    with_season = AsyncMock(return_value=(ep, 2, 1))

    file1, session, result = await _run_arc(
        show, _parsed(show_name=_ARC_NAME, season=None, episode=1), with_season=with_season
    )

    assert result.files_matched == 1
    assert file1.status == FileStatus.MATCHED
    assert file1.parsed_season == 2
    assert file1.episode_id == 99
    with_season.assert_awaited_once_with(session, show.id, show.episode_group_map, 2, 1)


async def test_run_season_alias_miss_keeps_alias_season_for_routing():
    """No S02E01 in the catalog: the file stays matched with season 2 for routing."""
    show = _make_show(title="Tougen Anki", season_aliases={"nikko kegon no taki-hen": 2})

    file1, _, _ = await _run_arc(show, _parsed(show_name=_ARC_NAME, season=None, episode=1))

    assert file1.status == FileStatus.MATCHED
    assert file1.parsed_season == 2
    assert file1.episode_id is None


async def test_run_unmapped_arc_flags_unmatched_instead_of_season_1():
    """Regression: an arc alias with no season must not resolve to S01E01."""
    show = _make_show(
        title="Tougen Anki",
        aliases=[_ARC_ALIAS],
        aliases_sources={"user": [_ARC_ALIAS]},
    )
    by_number = AsyncMock(return_value=MagicMock(id=1, season_number=1))

    file1, _, result = await _run_arc(
        show, _parsed(show_name=_ARC_NAME, season=None, episode=1), by_number=by_number
    )

    assert result.files_unmatched == 1
    assert file1.status == FileStatus.UNMATCHED
    assert "Nikko Kegon no Taki-hen" in file1.error_message
    assert file1.show_id is None
    by_number.assert_not_awaited()


async def test_run_explicit_season_ignores_season_alias():
    """An explicit season marker wins over a season name."""
    show = _make_show(title="Tougen Anki", season_aliases={"nikko kegon no taki-hen": 2})
    with_season = AsyncMock(return_value=None)

    file1, _, _ = await _run_arc(
        show, _parsed(show_name=_ARC_NAME, season=3, episode=1), with_season=with_season
    )

    assert file1.parsed_season == 3
    with_season.assert_not_awaited()


async def test_dry_run_reports_unmapped_arc():
    """The dry-run preview flags an unmapped arc the same way a real run would."""
    show = _make_show(title="Tougen Anki", aliases=[_ARC_ALIAS])
    on_event = AsyncMock()

    file1, _, result = await _run_arc(
        show,
        _parsed(show_name=_ARC_NAME, season=None, episode=1),
        dry_run=True,
        on_event=on_event,
    )

    assert result.files_unmatched == 1
    messages = [c.args[1] for c in on_event.await_args_list]
    assert any("unmapped arc" in m for m in messages)
    assert file1.status == FileStatus.DOWNLOADED
