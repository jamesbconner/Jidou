"""Tests for ParseOrchestrator (filename parsing + show matching).

Filename-extraction-level tests (heuristic regex, LLM prompt/parsing) live
in tests/test_filename_parser.py, covering jidou.services.filename_parser
directly. These tests cover ParseOrchestrator's own behavior: the
confidence gate, DB show/episode lookup, alias teaching, and local_path
resolution.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator, _sanitize_alias

# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


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
    f.crc32_declared = None
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
    # The fuzzy hit must not have been taught as an alias.
    assert show.aliases == []


async def test_run_exact_show_match_still_gets_aliased():
    """An exact title match (not a fuzzy substring guess) is still taught as an alias."""
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
    """show.content_type=movie routes to local_movie_path / sys_name."""
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
    assert path == "/media/movies/Spirited Away"


async def test_resolve_local_path_falls_back_to_media_type():
    """show.content_type=None falls back to show.media_type."""
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
    assert path == "/media/anime/Naruto"


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

    assert show.local_path == "/media/movies/Spirited Away"


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
