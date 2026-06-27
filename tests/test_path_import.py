"""Tests for path-file batch import — parser, orchestrator, and API route."""

from io import BytesIO
from pathlib import PurePosixPath, PureWindowsPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.main import app
from jidou.services.path_parser import (
    group_by_show,
    parse_file,
    parse_line,
)

# ---------------------------------------------------------------------------
# path_parser — parse_line
# ---------------------------------------------------------------------------


class TestParseLine:
    def test_skips_blank_line(self) -> None:
        assert parse_line("") is None
        assert parse_line("   ") is None

    def test_skips_comment(self) -> None:
        assert parse_line("# this is a comment") is None

    def test_skips_non_media_extension(self) -> None:
        assert parse_line(r"Z:\anime tv\Show\Season 1\readme.txt") is None

    def test_skips_short_path(self) -> None:
        # Only 3 parts — not enough to extract a show dir
        assert parse_line(r"Z:\anime tv\episode.mkv") is None

    def test_with_season_dir(self) -> None:
        line = r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E03.v2.1080p.BluRay.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Dorohedoro"
        assert entry.season == 1
        assert entry.episode == 3
        assert not entry.is_absolute
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\Dorohedoro"))

    def test_without_season_dir_dash_episode(self) -> None:
        line = r"Z:\anime tv\Hunter x Hunter\[HorribleSubs] Hunter x Hunter - 146 [1080p].mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Hunter x Hunter"
        assert entry.season is None
        assert entry.episode == 146
        assert entry.is_absolute

    def test_subsplease_style(self) -> None:
        line = (
            r"Z:\anime tv\As A Reincarnated Aristocrat\Season 2"
            r"\[SubsPlease] Tensei Kizoku - 06 (1080p) [F5E0AC82].mkv"
        )
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "As A Reincarnated Aristocrat"
        assert entry.season == 2
        assert entry.episode == 6

    def test_predash_episode_with_season_dir(self) -> None:
        # "Show NN - Episode Title [hash]" — episode number before the dash
        line = (
            r"Z:\anime tv\Cowboy Bebop\Season 01"
            r"\Cowboy Bebop 01 - Asteroid Blues [A8550EBD].mkv"
        )
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Cowboy Bebop"
        assert entry.season == 1
        assert entry.episode == 1
        assert not entry.is_absolute

    def test_predash_episode_higher_number(self) -> None:
        line = (
            r"Z:\anime tv\Cowboy Bebop\Season 01"
            r"\Cowboy Bebop 25 - The Real Folk Blues Part I [ABCDEF01].mkv"
        )
        entry = parse_line(line)
        assert entry is not None
        assert entry.episode == 25

    def test_ep_word_style(self) -> None:
        line = r"Z:\anime tv\Yawara\Yawara - Ep 64.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Yawara"
        assert entry.episode == 64
        assert entry.is_absolute

    def test_trailing_dash_number(self) -> None:
        line = r"Z:\anime tv\Seirei no Moribito\Seirei no Moribito - 06.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Seirei no Moribito"
        assert entry.episode == 6

    def test_case_insensitive_season_dir(self) -> None:
        line = r"Z:\anime tv\Show\season 2\Show.S02E01.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 2
        assert entry.episode == 1

    def test_mp4_extension_accepted(self) -> None:
        line = r"Z:\tv\Breaking Bad\Season 1\episode.mp4"
        entry = parse_line(line)
        assert entry is not None

    def test_raw_path_preserved(self) -> None:
        line = r"Z:\anime tv\Show\ep01.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.raw_path == line

    # -- POSIX paths -----------------------------------------------------------

    def test_posix_path_with_season_dir(self) -> None:
        line = "/mnt/media/anime/Dorohedoro/Season 01/Dorohedoro.S01E03.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Dorohedoro"
        assert entry.season == 1
        assert entry.episode == 3
        assert entry.show_root == str(PurePosixPath("/mnt/media/anime/Dorohedoro"))

    def test_posix_path_without_season_dir(self) -> None:
        line = "/home/user/shows/Hunter x Hunter/[HorribleSubs] HxH - 146 [1080p].mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Hunter x Hunter"
        assert entry.episode == 146
        assert entry.is_absolute

    def test_posix_path_skips_short(self) -> None:
        assert parse_line("/Show/ep.mkv") is None

    # -- NxNN release-group format ---------------------------------------------

    def test_nxnn_format_with_season_dir(self) -> None:
        line = r"Z:\tv\Criminal Minds\Season 1\Criminal.Minds.01x01.Extreme.Aggressor.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 1
        assert entry.episode == 1

    def test_nxnn_format_single_digit_season(self) -> None:
        line = r"Z:\tv\Downton Abbey\Season 1\Downton Abbey 1x01 Hdtv [mkv] X264 -mr12.mp4"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 1
        assert entry.episode == 1

    def test_nxnn_format_higher_episode(self) -> None:
        line = r"Z:\tv\Criminal Minds\Season 1\Criminal.Minds.01x22.The.Fisher.King.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 1
        assert entry.episode == 22

    def test_nxnn_format_not_confused_by_show_title(self) -> None:
        # "Hunter x Hunter" — the x in the title must NOT match
        line = r"Z:\anime tv\Hunter x Hunter\[HorribleSubs] Hunter x Hunter - 146 [1080p].mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.episode == 146
        assert entry.season is None

    # -- Compact SEEE format ---------------------------------------------------

    def test_compact_3digit_season2(self) -> None:
        # criminal.minds.201 → S02E01
        line = r"Z:\tv\Criminal Minds\Season 2\criminal.minds.201.hdtv-lol.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 2
        assert entry.episode == 1

    def test_compact_3digit_season9(self) -> None:
        line = r"Z:\tv\Criminal Minds\Season 9\criminal.minds.924.hdtv-lol.mp4"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 9
        assert entry.episode == 24

    def test_compact_4digit_season10(self) -> None:
        # criminal.minds.1001 → S10E01
        line = r"Z:\tv\Criminal Minds\Season 10\criminal.minds.1001.hdtv-lol.mp4"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 10
        assert entry.episode == 1

    def test_compact_4digit_season12(self) -> None:
        line = r"Z:\tv\Criminal Minds\Season 12\criminal.minds.1203.hdtv-lol.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 12
        assert entry.episode == 3

    def test_compact_not_matched_for_quality_number(self) -> None:
        # 720 is a quality token — must not be parsed as S07E20
        line = r"Z:\tv\Show\Season 7\Show.720p.BluRay.mkv"
        entry = parse_line(line)
        # Season from directory, but episode should NOT be 20
        assert entry is not None
        assert entry.episode != 20

    def test_compact_skipped_when_season_disagrees_with_directory(self) -> None:
        # "924" encodes S09E24 but the directory says Season 10 — must not
        # produce S10E24 (wrong episode tracked); episode should be None.
        line = r"Z:\tv\Criminal Minds\Season 10\criminal.minds.924.hdtv-lol.mp4"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 10
        assert entry.episode is None

    # -- "Episode N" / "Season N Episode N" word patterns ---------------------

    def test_episode_word_label(self) -> None:
        line = r"Z:\tv\Criminal Minds\Season 6\Episode 11 - 25 to Life.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 6
        assert entry.episode == 11

    def test_season_episode_word_labels(self) -> None:
        line = r"Z:\tv\Breaking Bad\Season 2\Breaking Bad Season 2 Episode 09 - 4 Days Out.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 2
        assert entry.episode == 9

    # -- Leading number + digit-starting title --------------------------------

    def test_leading_ep_digit_title(self) -> None:
        # "32 - 100th Dirty Job Special" — title starts with digit
        line = r"Z:\tv\Dirty Jobs\Season 2\32 - 100th Dirty Job Special.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 2
        assert entry.episode == 32

    def test_leading_ep_digit_title_season4(self) -> None:
        line = r"Z:\tv\Dirty Jobs\Season 4\19 - 200 Jobs Look-Back.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 4
        assert entry.episode == 19


# ---------------------------------------------------------------------------
# path_parser — parse_file and group_by_show
# ---------------------------------------------------------------------------


class TestParseFile:
    def test_parse_multiple_shows(self) -> None:
        content = "\n".join(
            [
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E01.mkv",
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E02.mkv",
                r"Z:\anime tv\Hunter x Hunter\[HorribleSubs] Hunter x Hunter - 01 [1080p].mkv",
                "# a comment line",
                "",
                r"Z:\anime tv\Hunter x Hunter\[HorribleSubs] Hunter x Hunter - 02 [1080p].mkv",
            ]
        )
        entries = parse_file(content)
        assert len(entries) == 4

    def test_parse_mixed_path_formats(self) -> None:
        content = "\n".join(
            [
                r"Z:\anime\Dorohedoro\Season 01\ep.mkv",
                "/mnt/media/anime/Dorohedoro/Season 01/ep.mkv",
            ]
        )
        entries = parse_file(content)
        assert len(entries) == 2
        assert all(e.show_dir == "Dorohedoro" for e in entries)

    def test_group_by_show(self) -> None:
        content = "\n".join(
            [
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E01.mkv",
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E02.mkv",
                r"Z:\anime tv\Hunter x Hunter\ep01.mkv",
            ]
        )
        entries = parse_file(content)
        groups = group_by_show(entries)
        assert set(groups.keys()) == {"Dorohedoro", "Hunter x Hunter"}
        assert len(groups["Dorohedoro"]) == 2
        assert len(groups["Hunter x Hunter"]) == 1

    def test_windows_crlf_line_endings(self) -> None:
        content = (
            "Z:\\anime tv\\Show\\Season 1\\Show.S01E01.mkv\r\n"
            "Z:\\anime tv\\Show\\Season 1\\Show.S01E02.mkv\r\n"
        )
        entries = parse_file(content)
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# PathImportOrchestrator (unit — DB and TMDB fully mocked)
# ---------------------------------------------------------------------------


def _make_episode(*, id: int, show_id: int, season: int, episode: int) -> MagicMock:
    ep = MagicMock()
    ep.id = id
    ep.show_id = show_id
    ep.season_number = season
    ep.episode_number = episode
    ep.absolute_episode_number = None
    ep.file_tracked = False
    return ep


def _make_show(*, id: int = 1, tmdb_id: int = 999, title: str = "Dorohedoro") -> MagicMock:
    s = MagicMock()
    s.id = id
    s.tmdb_id = tmdb_id
    s.title = title
    s.aliases = []
    return s


@pytest.mark.asyncio
async def test_orchestrator_creates_show_and_tracks_episode() -> None:
    """Happy path: show not in DB → TMDB create → mark episode tracked."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E01.mkv",
            show_dir="Dorohedoro",
            show_root=r"Z:\anime tv\Dorohedoro",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    found_ep = MagicMock()
    found_ep.scalar_one_or_none.return_value = episode
    session.execute.return_value = found_ep
    session.commit = AsyncMock()

    tmdb = AsyncMock()

    orch = PathImportOrchestrator(session, tmdb, content_type="anime")

    # Patch the private methods so the test focuses on the coordination logic.
    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        result = await orch.run(entries)

    assert result.shows_processed == 1
    assert result.shows_created == 1
    assert result.shows_found == 0
    assert result.episodes_tracked == 1
    assert result.episodes_unmatched == 0
    assert episode.file_tracked is True


@pytest.mark.asyncio
async def test_orchestrator_finds_existing_show() -> None:
    """Show already in DB → skip TMDB → match episode."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Dorohedoro\Season 01\ep.mkv",
            show_dir="Dorohedoro",
            show_root=r"Z:\anime tv\Dorohedoro",
            season=1,
            episode=2,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=20, show_id=1, season=1, episode=2)

    session = AsyncMock()
    show_result = MagicMock()
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode

    session.execute.side_effect = [show_result, ep_result]
    session.commit = AsyncMock()

    tmdb = AsyncMock()

    orch = PathImportOrchestrator(session, tmdb)
    result = await orch.run(entries)

    assert result.shows_found == 1
    assert result.shows_created == 0
    assert result.episodes_tracked == 1
    tmdb.search.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_handles_tmdb_miss() -> None:
    """TMDB returns no results → show_not_found, all episodes unmatched."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\UnknownShow\ep01.mkv",
            show_dir="UnknownShow",
            show_root=r"Z:\anime tv\UnknownShow",
            season=None,
            episode=1,
            is_absolute=True,
        )
    ]

    session = AsyncMock()
    not_found = MagicMock()
    not_found.scalars.return_value.first.return_value = None
    session.execute.return_value = not_found

    tmdb = AsyncMock()
    tmdb.search.return_value = {"results": []}

    orch = PathImportOrchestrator(session, tmdb)
    result = await orch.run(entries)

    assert result.shows_not_found == 1
    assert result.episodes_unmatched == 1
    assert result.episodes_tracked == 0


@pytest.mark.asyncio
async def test_orchestrator_absolute_episode_fallback() -> None:
    """No season dir → absolute lookup by absolute_episode_number first, then s1/eN."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Hunter x Hunter\HxH - 146 [1080p].mkv",
            show_dir="Hunter x Hunter",
            show_root=r"Z:\anime tv\Hunter x Hunter",
            season=None,
            episode=146,
            is_absolute=True,
        )
    ]

    show = _make_show(id=2, tmdb_id=11, title="Hunter x Hunter")
    episode = _make_episode(id=30, show_id=2, season=1, episode=146)

    session = AsyncMock()
    show_result = MagicMock()
    show_result.scalars.return_value.first.return_value = show

    # absolute_episode_number lookup → None (not set), then s1/e146 → found
    abs_miss = MagicMock()
    abs_miss.scalar_one_or_none.return_value = None

    s1_hit = MagicMock()
    s1_hit.scalar_one_or_none.return_value = episode

    session.execute.side_effect = [show_result, abs_miss, s1_hit]
    session.commit = AsyncMock()

    tmdb = AsyncMock()

    orch = PathImportOrchestrator(session, tmdb)
    result = await orch.run(entries)

    assert result.episodes_tracked == 1
    assert episode.file_tracked is True


@pytest.mark.asyncio
async def test_db_find_show_exact_match_only() -> None:
    """_db_find_show must not return a show whose title merely CONTAINS the search name.

    Regression: "Daredevil" must not match "Daredevil: Born Again" in the DB.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    born_again = _make_show(id=1, tmdb_id=202555, title="Daredevil: Born Again")

    session = AsyncMock()
    # Alias lookup → no match.
    alias_result = MagicMock()
    alias_result.scalars.return_value.first.return_value = None
    # Title exact-match lookup → also no match (Born Again ≠ Daredevil).
    title_result = MagicMock()
    title_result.scalars.return_value.first.return_value = None
    session.execute.side_effect = [alias_result, title_result]

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    # Even though "Daredevil: Born Again" exists in the DB, searching for
    # "Daredevil" must return None (not the Born Again show).
    _ = born_again  # exists in DB conceptually; mock returns None above
    result = await orch._db_find_show("Daredevil")
    assert result is None


@pytest.mark.asyncio
async def test_db_find_show_does_not_match_prefix_substring() -> None:
    """_db_find_show("Daredevil Born Again") must not match a show titled "Daredevil".

    Regression: the reverse direction — the longer search must not hit a shorter title.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    session = AsyncMock()
    alias_result = MagicMock()
    alias_result.scalars.return_value.first.return_value = None
    title_result = MagicMock()
    title_result.scalars.return_value.first.return_value = None
    session.execute.side_effect = [alias_result, title_result]

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)
    result = await orch._db_find_show("Daredevil Born Again")
    assert result is None


@pytest.mark.asyncio
async def test_tmdb_candidate_scan_finds_exact_match_beyond_top5() -> None:
    """Exact-match scan must search ALL candidates, not just the first five.

    Regression: TMDB's recency bias can rank "Daredevil: Born Again" (position 0)
    above the 2015 "Daredevil" (position 6).  Limiting the scan to [:5] caused the
    orchestrator to select "Born Again" for a directory named "Daredevil", creating
    the wrong show.  The scan must walk the full results list so the exact-normalized
    match at any position wins over the top-relevance fallback.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    # Simulate TMDB returning "Daredevil: Born Again" first (positions 0-4),
    # with the original "Daredevil" at position 5 (i.e. the 6th result).
    born_again = {"id": 202555, "name": "Daredevil: Born Again", "media_type": "tv"}
    original = {"id": 61889, "name": "Daredevil", "media_type": "tv"}
    tmdb_results = [born_again] * 5 + [original]

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    session = AsyncMock()
    tmdb = AsyncMock()
    tmdb.search.return_value = {"results": tmdb_results}
    tmdb.get_details.return_value = {"name": "Daredevil", "id": 61889}
    tmdb.get_external_ids.return_value = {}
    tmdb.get_episode_groups.return_value = {"results": []}

    orch = PathImportOrchestrator(session, tmdb, dry_run=True, on_event=capture_event)

    with patch.object(orch, "_db_find_show", AsyncMock(return_value=None)):
        show, action = await orch._tmdb_create_show("Daredevil")

    # Must have selected the original Daredevil, not Born Again.
    assert action == "created"
    assert show is not None
    tmdb.get_details.assert_called_once_with(61889, media_type="tv")

    # The selection event must be "info" (exact match), not "warn" (fallback).
    match_events = [(lvl, msg) for lvl, msg in events if "matched" in msg or "falling back" in msg]
    assert len(match_events) == 1
    assert match_events[0][0] == "info", "exact match should emit info, not warn"
    assert "Daredevil" in match_events[0][1]


@pytest.mark.asyncio
async def test_tmdb_fallback_emits_warn_when_no_exact_match() -> None:
    """When no candidate matches the directory name exactly, emit a warn-level event.

    This makes it immediately visible in the event log that the import used a
    best-guess rather than a confirmed match, prompting the user to verify.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    # All candidates are "Daredevil: Born Again" — no exact match for "Daredevil".
    born_again = {"id": 202555, "name": "Daredevil: Born Again", "media_type": "tv"}

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    session = AsyncMock()
    tmdb = AsyncMock()
    tmdb.search.return_value = {"results": [born_again]}
    tmdb.get_details.return_value = {"name": "Daredevil: Born Again", "id": 202555}
    tmdb.get_external_ids.return_value = {}
    tmdb.get_episode_groups.return_value = {"results": []}

    orch = PathImportOrchestrator(session, tmdb, dry_run=True, on_event=capture_event)

    with patch.object(orch, "_db_find_show", AsyncMock(return_value=None)):
        _, action = await orch._tmdb_create_show("Daredevil")

    assert action == "created"
    # The fallback selection must surface as a warning so the user sees it.
    fallback_events = [(lvl, msg) for lvl, msg in events if "falling back" in msg]
    assert len(fallback_events) == 1
    assert fallback_events[0][0] == "warn"


@pytest.mark.asyncio
async def test_llm_pick_candidate_resolves_article_mismatch() -> None:
    """LLM is invoked when exact match fails and picks the right candidate.

    "Daredevil" does not normalized-match "Marvel's Daredevil", so the LLM
    must be consulted and its answer (candidate 2) must be selected.
    """
    from unittest.mock import MagicMock

    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    born_again = {"id": 202555, "name": "Daredevil: Born Again", "media_type": "tv"}
    original = {"id": 61889, "name": "Marvel's Daredevil", "media_type": "tv"}

    mock_response = MagicMock()
    mock_response.content = "2"  # LLM picks candidate 2 = original Daredevil
    # is_available is sync; only complete is async.
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    tmdb = AsyncMock()
    tmdb.search.return_value = {"results": [born_again, original]}
    tmdb.get_details.return_value = {"name": "Marvel's Daredevil", "id": 61889}
    tmdb.get_external_ids.return_value = {}
    tmdb.get_episode_groups.return_value = {"results": []}

    orch = PathImportOrchestrator(session, tmdb, dry_run=True, llm=llm)

    with patch.object(orch, "_db_find_show", AsyncMock(return_value=None)):
        show, action = await orch._tmdb_create_show("Daredevil")

    assert action == "created"
    assert show is not None
    tmdb.get_details.assert_called_once_with(61889, media_type="tv")
    llm.complete.assert_called_once()


# ---------------------------------------------------------------------------
# _llm_parse_episode — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_parse_episode_unavailable_returns_none() -> None:
    """When LLM is not configured, _llm_parse_episode returns (None, None)."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    session = AsyncMock()
    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)  # no llm kwarg

    season, episode = await orch._llm_parse_episode("criminal.minds.201.hdtv-lol.avi")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_valid_json() -> None:
    """LLM returning valid JSON yields the correct (season, episode) pair."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '{"season": 2, "episode": 1}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    season, episode = await orch._llm_parse_episode("criminal.minds.201.hdtv-lol.avi")
    assert season == 2
    assert episode == 1


@pytest.mark.asyncio
async def test_llm_parse_episode_null_season() -> None:
    """LLM may return season=null when only episode can be determined."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '{"season": null, "episode": 7}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    season, episode = await orch._llm_parse_episode("Show.Episode.07.mkv")
    assert season is None
    assert episode == 7


@pytest.mark.asyncio
async def test_llm_parse_episode_invalid_json_returns_none() -> None:
    """Malformed LLM response is handled gracefully; (None, None) is returned."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = "I cannot determine the episode number."
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    season, episode = await orch._llm_parse_episode("some.unusual.filename.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_non_dict_json_returns_none() -> None:
    """Bare JSON null (valid JSON but not a dict) must not crash with AttributeError."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = "null"
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    season, episode = await orch._llm_parse_episode("some.unusual.filename.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_sends_known_season_hint() -> None:
    """known_season is included in the prompt when supplied."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '{"season": 6, "episode": 11}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    await orch._llm_parse_episode("Episode 11 - 25 to Life.avi", known_season=6)

    call_kwargs = llm.complete.call_args
    prompt_text = call_kwargs.kwargs.get("prompt") or call_kwargs.args[0]
    assert "Known season from directory: 6" in prompt_text


@pytest.mark.asyncio
async def test_llm_parse_episode_markdown_fence_stripped() -> None:
    """JSON wrapped in a code fence is still parsed correctly."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '```json\n{"season": 3, "episode": 5}\n```'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    season, episode = await orch._llm_parse_episode("Show.S03E05.mkv")
    assert season == 3
    assert episode == 5


# ---------------------------------------------------------------------------
# _find_episode — LLM filename-parse fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_episode_uses_llm_when_episode_none() -> None:
    """When regex gives episode=None, the LLM parses the filename and hits the DB."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    episode = _make_episode(id=10, show_id=1, season=6, episode=11)

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute.return_value = ep_result

    mock_response = MagicMock()
    mock_response.content = '{"season": 6, "episode": 11}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Criminal Minds\Season 6\Episode 11 - 25 to Life.avi",
        show_dir="Criminal Minds",
        show_root=r"Z:\tv\Criminal Minds",
        season=6,
        episode=None,  # regex could not parse
        is_absolute=False,
    )

    result = await orch._find_episode(show_id=1, show_title="Criminal Minds", entry=entry)
    assert result is episode
    llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_find_episode_returns_none_when_llm_also_fails() -> None:
    """If episode is None and LLM also returns None, _find_episode returns None."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    session = AsyncMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=MagicMock(content='{"season": null, "episode": null}'))

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\SomeShow\Season 1\SomeShow.Extras.mkv",
        show_dir="SomeShow",
        show_root=r"Z:\tv\SomeShow",
        season=1,
        episode=None,
        is_absolute=False,
    )

    result = await orch._find_episode(show_id=1, show_title="SomeShow", entry=entry)
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_returns_none_falls_back() -> None:
    """When LLM returns NONE the orchestrator falls back to candidates[0] with a warn."""
    from unittest.mock import MagicMock

    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    born_again = {"id": 202555, "name": "Daredevil: Born Again", "media_type": "tv"}

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    mock_response = MagicMock()
    mock_response.content = "NONE"
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    tmdb = AsyncMock()
    tmdb.search.return_value = {"results": [born_again]}
    tmdb.get_details.return_value = {"name": "Daredevil: Born Again", "id": 202555}
    tmdb.get_external_ids.return_value = {}
    tmdb.get_episode_groups.return_value = {"results": []}

    orch = PathImportOrchestrator(session, tmdb, dry_run=True, llm=llm, on_event=capture_event)

    with patch.object(orch, "_db_find_show", AsyncMock(return_value=None)):
        _, action = await orch._tmdb_create_show("Daredevil")

    assert action == "created"
    # Must have fallen back to candidates[0] with a warn.
    fallback = [(lvl, msg) for lvl, msg in events if "falling back" in msg]
    assert len(fallback) == 1
    assert fallback[0][0] == "warn"


def test_normalize_title_strips_punctuation() -> None:
    """_normalize_title makes 'Daredevil Born Again' match 'Daredevil: Born Again'."""
    from jidou.orchestrators.path_import_orchestrator import _normalize_title

    assert _normalize_title("Daredevil: Born Again") == _normalize_title("Daredevil Born Again")
    # But "Daredevil" must NOT match "Daredevil: Born Again".
    assert _normalize_title("Daredevil") != _normalize_title("Daredevil: Born Again")
    # Basic cases.
    assert _normalize_title("Hunter x Hunter") == "hunter x hunter"
    assert _normalize_title("Re:Zero") == _normalize_title("Re Zero")


@pytest.mark.asyncio
async def test_orchestrator_sets_local_path_when_unset() -> None:
    """show_root from entry is persisted to show.local_path when not already set."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Dorohedoro\Season 01\ep.mkv",
            show_dir="Dorohedoro",
            show_root=r"Z:\anime tv\Dorohedoro",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    show.local_path = None  # explicitly unset

    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute.return_value = ep_result
    session.commit = AsyncMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        await orch.run(entries)

    assert show.local_path == r"Z:\anime tv\Dorohedoro"


@pytest.mark.asyncio
async def test_orchestrator_does_not_overwrite_existing_local_path() -> None:
    """A user-set local_path is not overwritten on re-import."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Dorohedoro\Season 01\ep.mkv",
            show_dir="Dorohedoro",
            show_root=r"Z:\anime tv\Dorohedoro",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    show.local_path = r"D:\custom\path\Dorohedoro"  # already set by user

    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute.return_value = ep_result
    session.commit = AsyncMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        await orch.run(entries)

    assert show.local_path == r"D:\custom\path\Dorohedoro"


# ---------------------------------------------------------------------------
# POST /api/import/text — API route
# ---------------------------------------------------------------------------


def _import_route_session_override(task: MagicMock) -> "type[AsyncMock]":
    """Session that returns the given task on flush then yields it."""

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    return _mock_session  # type: ignore[return-value]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestImportTextRoute:
    def test_invalid_content_type_returns_400(self, client: TestClient) -> None:
        data = {"content_type": "invalid", "dry_run": False}
        files = {"file": ("paths.txt", BytesIO(b"Z:\\anime tv\\Show\\ep.mkv"), "text/plain")}
        resp = client.post("/api/import/text", data=data, files=files)
        assert resp.status_code == 400
        assert "content_type" in resp.json()["detail"]

    def test_file_too_large_returns_422(self, client: TestClient) -> None:
        large_content = b"Z:\\anime tv\\Show\\ep.mkv\n" * 600_000  # ~14 MB
        files = {"file": ("paths.txt", BytesIO(large_content), "text/plain")}
        resp = client.post("/api/import/text", data={"content_type": "anime"}, files=files)
        assert resp.status_code == 422
        assert "too large" in resp.json()["detail"]

    def test_valid_upload_dispatches_task(self, client: TestClient) -> None:
        from jidou.database import get_session
        from jidou.models.task import BackgroundTask, TaskStatus

        task = MagicMock(spec=BackgroundTask)
        task.id = 1
        task.celery_task_id = "abc-123"
        task.task_type = "import"
        task.status = TaskStatus.PENDING.value
        task.progress_current = 0
        task.progress_total = 0
        task.progress_message = None
        task.dry_run = False
        from datetime import UTC, datetime

        task.result_summary = None
        task.created_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        task.completed_at = None

        async def _mock_session() -> AsyncMock:
            session = AsyncMock()
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            with (
                patch(
                    "jidou.api.routes.import_routes.create_task_record",
                    AsyncMock(return_value=task),
                ),
                patch("jidou.workers.import_tasks.path_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock()
                content = b"Z:\\anime tv\\Show\\Season 1\\Show.S01E01.mkv\n"
                files = {"file": ("paths.txt", BytesIO(content), "text/plain")}
                resp = client.post(
                    "/api/import/text",
                    data={"content_type": "anime", "dry_run": False},
                    files=files,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["task_type"] == "import"
