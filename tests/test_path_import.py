"""Tests for path-file batch import — parser and orchestrator."""

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

    def test_compact_sets_absolute_candidate_to_raw_joined_number(self) -> None:
        # No season directory — "212" is ambiguous between S02E12 and a pure
        # absolute episode number; absolute_candidate preserves the raw 212
        # so the orchestrator can try it if the S02E12 guess doesn't pan out.
        line = r"Z:\anime tv\One Piece\One Piece 212.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 2
        assert entry.episode == 12
        assert entry.absolute_candidate == 212

    def test_compact_absolute_candidate_none_for_explicit_markers(self) -> None:
        # An explicit S/E marker is unambiguous — no alternate interpretation
        # is needed.
        line = r"Z:\tv\Show\Season 1\Show.S01E05.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.absolute_candidate is None

    def test_compact_absolute_candidate_none_for_dash_episode(self) -> None:
        # "- 212" at end-of-string is unambiguously a bare episode number via
        # _DASH_EP, matched before the compact heuristic is ever tried.
        line = r"Z:\anime tv\One Piece\One Piece - 212.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season is None
        assert entry.episode == 212
        assert entry.absolute_candidate is None

    # -- Bare "Title NN" (no dash, no keyword) ---------------------------------

    def test_bare_trailing_two_digit_number(self) -> None:
        line = r"Z:\anime tv\Bamboo Blade\Bamboo Blade 20.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season is None
        assert entry.episode == 20
        assert entry.is_absolute

    def test_bare_trailing_one_digit_number(self) -> None:
        line = r"Z:\anime tv\Yawara\Yawara 6.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.episode == 6

    def test_bare_trailing_number_not_matched_when_glued_to_letter(self) -> None:
        # "v2" — no whitespace separator, must not be treated as episode 2.
        line = r"Z:\anime tv\Show\Show v2.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.episode is None

    def test_bare_trailing_number_not_matched_after_season_word(self) -> None:
        # A lone "Season 2" with no episode marker must not have its season
        # number mistaken for an episode number.
        line = r"Z:\anime tv\Show\Show Season 2.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.episode is None

    def test_bare_trailing_number_does_not_shadow_compact_code(self) -> None:
        # 3+ digit numbers are the compact SEEE/SSEEE pattern's territory, not
        # this one — a bare trailing 2-digit number must never intercept a
        # legitimate 3-4 digit compact match.
        line = r"Z:\tv\Criminal Minds\Season 2\criminal.minds.201.hdtv-lol.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 2
        assert entry.episode == 1

    # -- Bugbot-caught regression: bonus-content markers must not be
    # -- swallowed by the bare-trailing-number pattern ------------------------

    @pytest.mark.parametrize(
        "filename",
        [
            "Show NCOP 01.mkv",
            "Show NCED 01.mkv",
            "Show OVA 2.mkv",
            "Show OAD 1.mkv",
            "Show OP 2.mkv",
            "Show ED 1.mkv",
            "Show SP 01.mkv",
            "Show PV 1.mkv",
            "Show CM 3.mkv",
        ],
    )
    def test_bare_trailing_number_skipped_for_non_episode_asset_markers(
        self, filename: str
    ) -> None:
        # Regression: _BARE_TRAILING_EP used to swallow the trailing number on
        # these regardless of the NCOP/OVA/etc. marker, resolving episode=1/2
        # directly from regex and skipping the LLM fallback entirely — even
        # though the LLM's system prompt explicitly knows these markers mean
        # "not a numbered episode." The regex must leave episode=None so
        # _find_episode still calls the LLM.
        line = rf"Z:\anime tv\Show\{filename}"
        entry = parse_line(line)
        assert entry is not None
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
# path_parser — parse_line with a configured library root
# ---------------------------------------------------------------------------


class TestParseLineWithRoot:
    def test_bonus_subfolder_no_longer_treated_as_show_dir(self) -> None:
        # Real production example: a bonus-content folder nested under the
        # actual show directory used to be misidentified as show_dir itself.
        line = r"Z:\anime tv\Gurren Lagann\Clean Intro & Endings\Gurren Lagann - Clean Ending.avi"
        entry = parse_line(line, root=r"Z:\anime tv")
        assert entry is not None
        assert entry.show_dir == "Gurren Lagann"
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\Gurren Lagann"))

    def test_season_dir_detected_below_an_extra_subfolder(self) -> None:
        line = (
            r"Z:\anime tv\Re Zero kara Hajimeru Isekai Seikatsu\Season 00"
            r"\Hybrid Remux\ReZERO S00E01.mkv"
        )
        entry = parse_line(line, root=r"Z:\anime tv")
        assert entry is not None
        assert entry.show_dir == "Re Zero kara Hajimeru Isekai Seikatsu"
        assert entry.season == 0

    def test_no_extra_subfolder_still_resolves_normally(self) -> None:
        line = r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E03.mkv"
        entry = parse_line(line, root=r"Z:\anime tv")
        assert entry is not None
        assert entry.show_dir == "Dorohedoro"
        assert entry.season == 1
        assert entry.episode == 3
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\Dorohedoro"))

    def test_path_not_under_root_falls_back_to_old_heuristic(self) -> None:
        line = r"Z:\anime tv\Gurren Lagann\Clean Intro & Endings\Gurren Lagann - Clean Ending.avi"
        entry = parse_line(line, root=r"D:\some\other\root")
        assert entry is not None
        assert entry.show_dir == "Clean Intro & Endings"

    def test_path_style_mismatch_falls_back_gracefully(self) -> None:
        # root given as POSIX while the line is Windows-style — must not raise.
        line = r"Z:\anime tv\Gurren Lagann\Clean Intro & Endings\Gurren Lagann - Clean Ending.avi"
        entry = parse_line(line, root="/data/media/anime")
        assert entry is not None
        assert entry.show_dir == "Clean Intro & Endings"

    def test_no_root_given_uses_old_heuristic(self) -> None:
        line = r"Z:\anime tv\Gurren Lagann\Clean Intro & Endings\Gurren Lagann - Clean Ending.avi"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Clean Intro & Endings"

    def test_posix_root_and_line(self) -> None:
        line = (
            "/mnt/media/anime/Gurren Lagann/Clean Intro & Endings/Gurren Lagann - Clean Ending.avi"
        )
        entry = parse_line(line, root="/mnt/media/anime")
        assert entry is not None
        assert entry.show_dir == "Gurren Lagann"

    def test_parse_file_passes_root_through(self) -> None:
        content = (
            r"Z:\anime tv\Gurren Lagann\Clean Intro & Endings\Gurren Lagann - Clean Ending.avi"
        )
        entries = parse_file(content, root=r"Z:\anime tv")
        assert len(entries) == 1
        assert entries[0].show_dir == "Gurren Lagann"


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

    dedup_result = MagicMock()
    dedup_result.scalar_one_or_none.return_value = None

    session.execute.side_effect = [show_result, ep_result, dedup_result]
    session.commit = AsyncMock()
    session.add = MagicMock()
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)

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

    dedup_result = MagicMock()
    dedup_result.scalar_one_or_none.return_value = None

    session.execute.side_effect = [show_result, abs_miss, s1_hit, dedup_result]
    session.commit = AsyncMock()
    session.add = MagicMock()
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)

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
    mock_response.content = '{"match": 2}'  # LLM picks candidate 2 = original Daredevil
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
async def test_llm_parse_episode_system_prompt_covers_bare_numbers_and_non_episode_assets() -> None:
    """Regression: the episode-parse prompt was trimmed down to 4 lines with
    no guidance at all, losing coverage for bare trailing numbers and
    non-episode bonus content (NCED/NCOP/OVA/etc.) that an earlier, more
    detailed prompt used to handle correctly.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '{"season": null, "episode": 9}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    await orch._llm_parse_episode("Show 09.mkv")

    system_text = llm.complete.call_args.kwargs["system"]
    assert "bare trailing number" in system_text.lower()
    assert "never the season" in system_text.lower()
    assert "ncop" in system_text.lower()
    assert "never infer season" in system_text.lower()


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

    ep, season, ep_num = await orch._find_episode(
        show_id=1, show_title="Criminal Minds", entry=entry
    )
    assert ep is episode
    assert season == 6
    assert ep_num == 11
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

    ep, season, ep_num = await orch._find_episode(show_id=1, show_title="SomeShow", entry=entry)
    assert ep is None
    assert season == 1
    assert ep_num is None


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
# run() — on_progress plumbing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_calls_on_progress_per_show() -> None:
    """on_progress is invoked once per unique show directory with correct idx/total."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\ShowA\ep01.mkv",
            show_dir="ShowA",
            show_root=r"Z:\anime tv\ShowA",
            season=None,
            episode=1,
            is_absolute=True,
        ),
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\ShowB\ep01.mkv",
            show_dir="ShowB",
            show_root=r"Z:\anime tv\ShowB",
            season=None,
            episode=1,
            is_absolute=True,
        ),
    ]

    session = AsyncMock()
    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    progress_calls: list[tuple[int, int, str]] = []

    async def on_progress(current: int, total: int, message: str) -> None:
        progress_calls.append((current, total, message))

    stub_result = MagicMock(action="not_found", episodes_tracked=0, episodes_unmatched=1)
    with patch.object(orch, "_import_show", AsyncMock(return_value=stub_result)):
        await orch.run(entries, on_progress=on_progress)

    assert len(progress_calls) == 2
    assert progress_calls[0][0] == 1
    assert progress_calls[0][1] == 2
    assert progress_calls[1][0] == 2
    assert progress_calls[1][1] == 2


# ---------------------------------------------------------------------------
# _import_show — existing show with unsynced episodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_show_syncs_episodes_when_none_synced() -> None:
    """Existing show with zero synced episodes triggers a TMDB episode sync."""
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
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=0)  # ep_count == 0 -> triggers sync
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=ep_result)
    session.commit = AsyncMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        result = await orch.run(entries)

    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_called_once_with(show)
    assert result.shows_found == 1
    assert result.episodes_tracked == 1


@pytest.mark.asyncio
async def test_import_show_episode_sync_failure_logged_not_raised() -> None:
    """A TMDB episode-sync failure for an existing show is logged, not raised."""
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

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=0)
    no_ep = MagicMock()
    no_ep.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=no_ep)
    session.commit = AsyncMock()

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb, on_event=capture_event)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=RuntimeError("TMDB down")
        )
        result = await orch.run(entries)  # must not raise

    error_events = [(lvl, msg) for lvl, msg in events if lvl == "error"]
    assert len(error_events) == 1
    assert "Episode sync failed" in error_events[0][1]
    assert result.shows_found == 1
    assert result.episodes_unmatched == 1


# ---------------------------------------------------------------------------
# _import_show — dry-run estimation for a brand-new (unpersisted) show
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_new_show_estimates_from_entries() -> None:
    """dry_run + newly-created show (id=None) estimates counts from parsed entries directly."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\ep01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        ),
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\extras.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=None,
            is_absolute=False,
        ),
    ]

    show = MagicMock()
    show.id = None  # dry-run "created" show has no id yet
    show.title = "Show"
    show.tmdb_id = 5
    show.local_path = None

    session = AsyncMock()
    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb, dry_run=True)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        result = await orch.run(entries)

    assert result.episodes_tracked == 1
    assert result.episodes_unmatched == 1
    assert result.show_results[0].unmatched_paths == [entries[1].raw_path]
    # _find_episode must never be reached in this path.
    session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# _import_show — already-tracked episode, mixed results, and dry-run commit skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_show_already_tracked_episode_not_double_counted() -> None:
    """A previously-tracked episode found again keeps file_tracked=True but isn't re-counted."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\ep01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)
    episode.file_tracked = True  # already tracked from a prior import/match

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=ep_result)
    session.commit = AsyncMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        result = await orch.run(entries)

    assert episode.file_tracked is True
    assert result.episodes_tracked == 0  # not newly tracked, so not counted


# ---------------------------------------------------------------------------
# _create_synthetic_import_file — display-only ROUTED DownloadedFile
# ---------------------------------------------------------------------------


def _make_import_session(
    episode: MagicMock, existing_synthetic_file: MagicMock | None
) -> AsyncMock:
    """Session whose first execute() resolves _find_episode, second resolves
    the synthetic-file dedup check inside _create_synthetic_import_file.
    """
    session = AsyncMock()

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    dedup_result = MagicMock()
    dedup_result.scalar_one_or_none.return_value = existing_synthetic_file
    session.execute = AsyncMock(side_effect=[ep_result, dedup_result])

    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_import_show_creates_synthetic_routed_file_for_newly_tracked_episode() -> None:
    """A newly-tracked imported episode gets a display-only, already-ROUTED DownloadedFile."""
    from jidou.models.downloaded_file import FileStatus
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    raw_path = r"Z:\anime tv\Show\Season 01\ep01.mkv"
    entries = [
        ParsedPathEntry(
            raw_path=raw_path,
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)  # file_tracked=False

    session = _make_import_session(episode, existing_synthetic_file=None)
    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        await orch.run(entries)

    session.add.assert_called_once()
    created_file = session.add.call_args[0][0]
    assert created_file.show_id == show.id
    assert created_file.episode_id == episode.id
    assert created_file.remote_path == f"synthetic-import://{raw_path}"
    assert created_file.local_path == raw_path
    assert created_file.status == FileStatus.ROUTED


@pytest.mark.asyncio
async def test_import_show_skips_synthetic_file_when_already_exists() -> None:
    """Re-importing the same path is idempotent — no duplicate DownloadedFile created."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    raw_path = r"Z:\anime tv\Show\Season 01\ep01.mkv"
    entries = [
        ParsedPathEntry(
            raw_path=raw_path,
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)  # file_tracked=False

    session = _make_import_session(episode, existing_synthetic_file=MagicMock())
    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        await orch.run(entries)

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_import_show_does_not_create_synthetic_file_for_already_tracked_episode() -> None:
    """An episode already tracked (via download or a prior import) never gets a new file record."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\ep01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)
    episode.file_tracked = True  # already tracked

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=ep_result)
    session.add = MagicMock()
    session.commit = AsyncMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        await orch.run(entries)

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_import_show_dry_run_does_not_create_synthetic_file() -> None:
    """Dry-run mode never creates a DownloadedFile, even for a newly-matched episode."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\ep01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)  # file_tracked=False

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=ep_result)
    session.add = MagicMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb, dry_run=True)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        await orch.run(entries)

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_import_show_mixed_matched_and_unmatched_entries() -> None:
    """A show with one matched and one unmatched entry reports accurate mixed counts and events."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\Show.S01E01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        ),
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\Show.S01E99.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=99,
            is_absolute=False,
        ),
    ]

    show = _make_show()
    matched_episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    hit = MagicMock()
    hit.scalar_one_or_none.return_value = matched_episode
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    dedup_miss = MagicMock()
    dedup_miss.scalar_one_or_none.return_value = None

    session = AsyncMock()
    # entry 1: S/E lookup hits, then the synthetic-file dedup check (no existing row).
    # entry 2: S/E lookup misses -> falls through (season==1) to absolute miss -> row-number miss.
    session.execute = AsyncMock(side_effect=[hit, dedup_miss, miss, miss, miss])
    session.commit = AsyncMock()
    session.add = MagicMock()
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)

    events: list[tuple[str, str, object]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg, ctx))

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb, on_event=capture_event)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        result = await orch.run(entries)

    assert result.episodes_tracked == 1
    assert result.episodes_unmatched == 1

    no_match_events = [(lvl, msg, ctx) for lvl, msg, ctx in events if "No match" in msg]
    assert len(no_match_events) == 1
    assert no_match_events[0][0] == "warn"
    assert no_match_events[0][2]["season"] == 1
    assert no_match_events[0][2]["episode"] == 99

    summary_events = [(lvl, msg) for lvl, msg, _ in events if "unmatched file" in msg]
    assert len(summary_events) == 1
    assert summary_events[0][0] == "warn"


@pytest.mark.asyncio
async def test_import_show_emits_info_summary_when_all_tracked() -> None:
    """When every entry for a show is matched, an info-level summary event is emitted."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\ep01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=ep_result)
    session.commit = AsyncMock()

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb, on_event=capture_event)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        await orch.run(entries)

    tracked_events = [(lvl, msg) for lvl, msg in events if msg.startswith("Tracked ")]
    assert len(tracked_events) == 1
    assert tracked_events[0][0] == "info"


# ---------------------------------------------------------------------------
# _import_show — per-file show-name confirmation (issue #282)
# ---------------------------------------------------------------------------


class TestAgreesWithShow:
    def test_exact_normalized_title_match(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import _agrees_with_show

        show = _make_show(title="Daredevil: Born Again")
        assert _agrees_with_show("Daredevil Born Again", show) is True

    def test_alias_match(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import _agrees_with_show

        show = _make_show(title="Attack on Titan")
        show.aliases = ["shingeki no kyojin"]
        assert _agrees_with_show("Shingeki no Kyojin", show) is True

    def test_no_match(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import _agrees_with_show

        show = _make_show(title="One Piece")
        show.aliases = []
        assert _agrees_with_show("Bleach", show) is False


@pytest.mark.asyncio
async def test_import_show_splits_llm_confirmed_mismatch() -> None:
    """A file whose LLM-extracted show name disagrees with the directory's
    resolved show is split off and independently resolved, instead of being
    silently matched against the wrong show.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.filename_parser import FilenameParseResult
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Gurren Lagann\Gurren Lagann - 01.mkv",
            show_dir="Gurren Lagann",
            show_root=r"Z:\anime tv\Gurren Lagann",
            season=None,
            episode=1,
            is_absolute=True,
        ),
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Gurren Lagann\Clean Intro & Endings\Bleach - Clean Ending.mkv",
            show_dir="Gurren Lagann",
            show_root=r"Z:\anime tv\Gurren Lagann",
            season=None,
            episode=None,
            is_absolute=False,
        ),
    ]

    primary_show = _make_show(id=1, tmdb_id=100, title="Gurren Lagann")
    primary_show.aliases = []
    secondary_show = _make_show(id=2, tmdb_id=200, title="Bleach")
    secondary_show.aliases = []

    primary_episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    async def fake_parse_filename(filename: str, llm: object) -> FilenameParseResult:
        if "Bleach" in filename:
            return FilenameParseResult(
                show_name="Bleach",
                season=None,
                episode=None,
                crc32=None,
                content_type="anime",
                confidence=0.9,
                llm_ok=True,
            )
        return FilenameParseResult(
            show_name="Gurren Lagann",
            season=None,
            episode=1,
            crc32=None,
            content_type="anime",
            confidence=0.9,
            llm_ok=True,
        )

    dedup_miss = MagicMock()
    dedup_miss.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=dedup_miss)
    session.commit = AsyncMock()
    session.add = MagicMock()
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)

    tmdb = AsyncMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    orch = PathImportOrchestrator(session, tmdb, llm=llm)

    async def fake_resolve_show(name: str) -> tuple[MagicMock, str]:
        if name == "Bleach":
            return secondary_show, "found"
        return primary_show, "found"

    async def fake_find_episode(
        show_id: int, show_title: str, entry: ParsedPathEntry
    ) -> tuple[MagicMock | None, int | None, int | None]:
        if show_id == primary_show.id:
            return primary_episode, 1, 1
        return None, None, None

    with (
        patch(
            "jidou.orchestrators.path_import_orchestrator.parse_filename",
            fake_parse_filename,
        ),
        patch.object(orch, "_resolve_show", fake_resolve_show),
        patch.object(orch, "_find_episode", fake_find_episode),
    ):
        results = await orch._import_show("Gurren Lagann", entries)

    assert len(results) == 2
    assert results[0].show_dir == "Gurren Lagann"
    assert results[0].episodes_tracked == 1
    assert results[1].show_dir == "Bleach"
    assert results[1].action == "found"
    # The mismatched file was matched against Bleach's own (mocked) episode
    # lookup, which returned None — it ends up unmatched under Bleach, not
    # silently tracked against Gurren Lagann.
    assert results[1].episodes_unmatched == 1


@pytest.mark.asyncio
async def test_import_show_no_split_when_llm_confirms_agreement() -> None:
    """A truncated directory name that the LLM resolves to the same show
    (via alias agreement) must not be split off, even though the extracted
    name differs textually from the directory name.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.filename_parser import FilenameParseResult
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Backstabbed in a Backwater Dungeon\ep01.mkv",
            show_dir="Backstabbed in a Backwater Dungeon",
            show_root=r"Z:\anime tv\Backstabbed in a Backwater Dungeon",
            season=None,
            episode=1,
            is_absolute=True,
        )
    ]

    show = _make_show(id=1, tmdb_id=100, title="Backstabbed in a Backwater Dungeon: The Full Title")
    show.aliases = ["backstabbed in a backwater dungeon"]
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    async def fake_parse_filename(filename: str, llm: object) -> FilenameParseResult:
        return FilenameParseResult(
            show_name="Backstabbed in a Backwater Dungeon",
            season=None,
            episode=1,
            crc32=None,
            content_type="anime",
            confidence=0.9,
            llm_ok=True,
        )

    dedup_miss = MagicMock()
    dedup_miss.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=dedup_miss)
    session.commit = AsyncMock()
    session.add = MagicMock()
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)

    tmdb = AsyncMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    orch = PathImportOrchestrator(session, tmdb, llm=llm)

    async def fake_find_episode(
        show_id: int, show_title: str, entry: ParsedPathEntry
    ) -> tuple[MagicMock, int, int]:
        return episode, 1, 1

    with (
        patch(
            "jidou.orchestrators.path_import_orchestrator.parse_filename",
            fake_parse_filename,
        ),
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        patch.object(orch, "_find_episode", fake_find_episode),
    ):
        results = await orch._import_show("Backstabbed in a Backwater Dungeon", entries)

    assert len(results) == 1
    assert results[0].episodes_tracked == 1


@pytest.mark.asyncio
async def test_import_show_heuristic_only_never_splits() -> None:
    """Without an LLM (heuristic-only extraction), a generic filename with no
    real show title in it (e.g. "extras.mkv") must not trigger a split, even
    though its heuristically-extracted "show name" disagrees with the real
    show — heuristic extraction is too unreliable to justify a split.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\ep01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        ),
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\extras.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=None,
            is_absolute=False,
        ),
    ]

    show = _make_show(title="Show")
    show.aliases = []
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    dedup_miss = MagicMock()
    dedup_miss.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=dedup_miss)
    session.commit = AsyncMock()
    session.add = MagicMock()
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)

    tmdb = AsyncMock()
    # No llm= passed — parse_filename() will use the real heuristic fallback.
    orch = PathImportOrchestrator(session, tmdb)

    async def fake_find_episode(
        show_id: int, show_title: str, entry: ParsedPathEntry
    ) -> tuple[MagicMock | None, int | None, int | None]:
        if entry.episode == 1:
            return episode, 1, 1
        return None, 1, None

    with (
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        patch.object(orch, "_find_episode", fake_find_episode),
    ):
        results = await orch._import_show("Show", entries)

    assert len(results) == 1
    assert results[0].episodes_tracked == 1
    assert results[0].episodes_unmatched == 1


@pytest.mark.asyncio
async def test_import_show_dry_run_does_not_commit() -> None:
    """dry_run=True must never call session.commit()."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Season 01\ep01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    show.id = 1  # already exists — not the "new dry-run show" early-return path

    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=ep_result)
    session.commit = AsyncMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb, dry_run=True)

    with patch.object(orch, "_db_find_show", AsyncMock(return_value=show)):
        await orch.run(entries)

    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# _tmdb_create_show — TMDB call failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tmdb_create_show_search_exception_returns_not_found() -> None:
    """A TMDB search failure is caught, emits an error event, and returns not_found."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    session = AsyncMock()
    tmdb = AsyncMock()
    tmdb.search = AsyncMock(side_effect=RuntimeError("TMDB API down"))

    orch = PathImportOrchestrator(session, tmdb, on_event=capture_event)
    show, action = await orch._tmdb_create_show("SomeShow")

    assert show is None
    assert action == "not_found"
    error_events = [(lvl, msg) for lvl, msg in events if lvl == "error"]
    assert len(error_events) == 1
    assert "TMDB search failed" in error_events[0][1]


@pytest.mark.asyncio
async def test_tmdb_create_show_get_details_exception_returns_not_found() -> None:
    """A TMDB get_details failure after a successful search is caught, returns not_found."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    session = AsyncMock()
    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(side_effect=RuntimeError("TMDB API down"))

    orch = PathImportOrchestrator(session, tmdb, on_event=capture_event)
    show, action = await orch._tmdb_create_show("SomeShow")

    assert show is None
    assert action == "not_found"
    error_events = [(lvl, msg) for lvl, msg in events if lvl == "error"]
    assert any("get_details failed" in msg for _, msg in error_events)


@pytest.mark.asyncio
async def test_tmdb_create_show_supplemental_calls_failure_does_not_block_creation() -> None:
    """get_external_ids and get_episode_groups failures are best-effort; show is still created."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.scalar = AsyncMock(return_value=5)

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(side_effect=RuntimeError("external ids down"))
    tmdb.get_episode_groups = AsyncMock(side_effect=RuntimeError("episode groups down"))

    orch = PathImportOrchestrator(session, tmdb)

    with patch(
        "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
    ) as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        with patch("jidou.orchestrators.alias_orchestrator.generate_aliases", AsyncMock()):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None
    assert show.external_ids == {}
    assert show.episode_groups == []


async def test_tmdb_create_show_stores_adult_flag() -> None:
    """A TMDB details response with adult=true is stored on the created Show."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.scalar = AsyncMock(return_value=5)

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42, "adult": True})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={})

    orch = PathImportOrchestrator(session, tmdb)

    with patch(
        "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
    ) as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        with patch("jidou.orchestrators.alias_orchestrator.generate_aliases", AsyncMock()):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None
    assert show.adult is True


# ---------------------------------------------------------------------------
# _tmdb_create_show — IntegrityError race condition on insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tmdb_create_show_integrity_error_finds_existing_show() -> None:
    """A race-condition IntegrityError on insert falls back to a DB lookup by title."""
    from sqlalchemy.exc import IntegrityError

    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}
    existing_show = _make_show(id=99, tmdb_id=42, title="SomeShow")

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup key")))
    session.rollback = AsyncMock()

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb)

    with patch.object(orch, "_db_find_show", AsyncMock(return_value=existing_show)):
        show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "found"
    assert show is existing_show
    session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_tmdb_create_show_integrity_error_no_fallback_returns_not_found() -> None:
    """IntegrityError with no fallback match returns not_found."""
    from sqlalchemy.exc import IntegrityError

    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup key")))
    session.rollback = AsyncMock()

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb)

    with patch.object(orch, "_db_find_show", AsyncMock(return_value=None)):
        show, action = await orch._tmdb_create_show("SomeShow")

    assert show is None
    assert action == "not_found"


# ---------------------------------------------------------------------------
# _tmdb_create_show — episode sync and alias generation failures (new show)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tmdb_create_show_episode_sync_failure_still_returns_created() -> None:
    """Episode sync failure for a newly-created show is logged; show creation still succeeds."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb, on_event=capture_event)

    with patch(
        "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
    ) as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=RuntimeError("sync failed")
        )
        with patch("jidou.orchestrators.alias_orchestrator.generate_aliases", AsyncMock()):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None
    error_events = [
        (lvl, msg) for lvl, msg in events if lvl == "error" and "Episode sync failed" in msg
    ]
    assert len(error_events) == 1


@pytest.mark.asyncio
async def test_tmdb_create_show_alias_generation_failure_logged_not_raised() -> None:
    """A generate_aliases failure does not prevent the show from being returned as created."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.scalar = AsyncMock(return_value=10)

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb)

    with patch(
        "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
    ) as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        with patch(
            "jidou.orchestrators.alias_orchestrator.generate_aliases",
            AsyncMock(side_effect=RuntimeError("alias generation blew up")),
        ):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None


# ---------------------------------------------------------------------------
# _llm_parse_episode — additional failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_parse_episode_complete_raises_returns_none_none() -> None:
    """An exception from llm.complete() is caught; (None, None) is returned."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("LLM provider down"))

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    season, episode = await orch._llm_parse_episode("some.file.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_response_none_returns_none_none() -> None:
    """llm.complete() returning None (provider unavailable) yields (None, None)."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    season, episode = await orch._llm_parse_episode("some.file.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_non_integer_values_return_none_none() -> None:
    """Non-integer season/episode values in the LLM's JSON are handled gracefully."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '{"season": "two", "episode": 1}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    season, episode = await orch._llm_parse_episode("some.file.mkv")
    assert season is None
    assert episode is None


# ---------------------------------------------------------------------------
# _find_episode — additional lookup branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_episode_season_gt_1_miss_tries_absolute_lookup_then_llm() -> None:
    """A season>1 S/E miss tries absolute-number lookups before the LLM."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    session = AsyncMock()
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=miss)

    orch = PathImportOrchestrator(session, AsyncMock())

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\Season 3\Show.S03E99.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=3,
        episode=99,
        is_absolute=False,
    )

    with patch.object(
        orch, "_llm_match", AsyncMock(return_value=(None, None, None))
    ) as mock_llm_match:
        ep, season, ep_num = await orch._find_episode(show_id=1, show_title="Show", entry=entry)

    assert ep is None
    assert season == 3
    assert ep_num == 99
    mock_llm_match.assert_called_once()
    # S/E lookup + absolute_episode_number lookup + row-number lookup = 3.
    assert session.execute.call_count == 3


@pytest.mark.asyncio
async def test_find_episode_season_gt_1_miss_resolves_via_absolute_lookup() -> None:
    """A season>1 S/E miss that resolves via absolute lookup never reaches the LLM."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    matched_episode = _make_episode(id=9, show_id=1, season=1, episode=99)

    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = matched_episode

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[miss, hit])

    orch = PathImportOrchestrator(session, AsyncMock())

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\Season 3\Show.S03E99.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=3,
        episode=99,
        is_absolute=False,
    )

    with patch.object(orch, "_llm_match", AsyncMock(return_value=(None, None, None))) as mock_llm:
        ep, season, ep_num = await orch._find_episode(show_id=1, show_title="Show", entry=entry)

    assert ep is matched_episode
    assert season == 3
    assert ep_num == 99
    mock_llm.assert_not_called()
    assert session.execute.call_count == 2


@pytest.mark.asyncio
async def test_find_episode_season_gt_1_miss_uses_absolute_candidate_over_bare_episode() -> None:
    """An ambiguous compact-code guess (e.g. "212" -> S02E12) uses the raw
    joined number for the absolute lookup, not the split episode component —
    this is exactly the "One Piece 212" / "Bleach 260" scenario.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    matched_episode = _make_episode(id=9, show_id=1, season=1, episode=212)

    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = matched_episode

    bound_absolute_numbers: list[int] = []

    async def capture_execute(stmt: object) -> MagicMock:
        params = stmt.compile().params  # type: ignore[attr-defined]
        if "absolute_episode_number_1" in params:
            bound_absolute_numbers.append(params["absolute_episode_number_1"])
            return hit
        return miss

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=capture_execute)

    orch = PathImportOrchestrator(session, AsyncMock())

    # Compact-code guessed S02E12 from "212", but absolute_candidate=212 is
    # the raw number — that's what must be used for the absolute lookup.
    entry = ParsedPathEntry(
        raw_path=r"Z:\anime tv\One Piece\One Piece 212.mkv",
        show_dir="One Piece",
        show_root=r"Z:\anime tv\One Piece",
        season=2,
        episode=12,
        is_absolute=False,
        absolute_candidate=212,
    )

    with patch.object(orch, "_llm_match", AsyncMock(return_value=(None, None, None))) as mock_llm:
        ep, _season, _ep_num = await orch._find_episode(
            show_id=1, show_title="One Piece", entry=entry
        )

    assert ep is matched_episode
    mock_llm.assert_not_called()
    assert bound_absolute_numbers == [212]


@pytest.mark.asyncio
async def test_find_episode_absolute_number_column_hit() -> None:
    """No season known; absolute_episode_number column match is used directly."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    episode = _make_episode(id=5, show_id=1, season=1, episode=146)
    episode.absolute_episode_number = 146

    session = AsyncMock()
    abs_hit = MagicMock()
    abs_hit.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=abs_hit)

    orch = PathImportOrchestrator(session, AsyncMock())

    entry = ParsedPathEntry(
        raw_path=r"Z:\anime tv\HxH\HxH - 146.mkv",
        show_dir="HxH",
        show_root=r"Z:\anime tv\HxH",
        season=None,
        episode=146,
        is_absolute=True,
    )

    ep, season, ep_num = await orch._find_episode(show_id=1, show_title="HxH", entry=entry)
    assert ep is episode
    assert season is None
    assert ep_num == 146
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_find_episode_falls_through_to_llm_match_when_all_lookups_fail() -> None:
    """When absolute and row-number lookups both miss, falls back to the LLM."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    session = AsyncMock()
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=miss)

    orch = PathImportOrchestrator(session, AsyncMock())

    entry = ParsedPathEntry(
        raw_path=r"Z:\anime tv\HxH\HxH - 999.mkv",
        show_dir="HxH",
        show_root=r"Z:\anime tv\HxH",
        season=None,
        episode=999,
        is_absolute=True,
    )

    with patch.object(
        orch, "_llm_match", AsyncMock(return_value=(None, None, None))
    ) as mock_llm_match:
        ep, season, ep_num = await orch._find_episode(show_id=1, show_title="HxH", entry=entry)

    assert ep is None
    assert season is None
    assert ep_num == 999
    mock_llm_match.assert_called_once()
    # absolute lookup + row-number lookup = 2 execute calls before giving up.
    assert session.execute.call_count == 2


# ---------------------------------------------------------------------------
# _llm_pick_candidate — additional failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_pick_candidate_complete_raises_returns_none() -> None:
    """An exception from llm.complete() is caught; None is returned."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    result = await orch._llm_pick_candidate("Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_response_none_returns_none() -> None:
    """llm.complete() returning None yields None."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    result = await orch._llm_pick_candidate("Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_invalid_json_returns_none() -> None:
    """Malformed JSON from the LLM is handled gracefully."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = "I'm not sure which one matches."
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    result = await orch._llm_pick_candidate("Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_non_integer_match_returns_none() -> None:
    """A non-integer 'match' value in the LLM's JSON is handled gracefully."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '{"match": "one"}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    result = await orch._llm_pick_candidate("Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_out_of_range_index_returns_none() -> None:
    """An out-of-range candidate index from the LLM is handled gracefully."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '{"match": 99}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    result = await orch._llm_pick_candidate("Show", [{"name": "Show", "id": 1}])
    assert result is None


# ---------------------------------------------------------------------------
# _llm_match — unit tests
# ---------------------------------------------------------------------------


def _make_ep_row(season: int, episode: int, name: str = "Episode") -> MagicMock:
    """Build a mock Episode row for the LLM episode-list prompt."""
    ep = MagicMock()
    ep.season_number = season
    ep.episode_number = episode
    ep.name = name
    return ep


@pytest.mark.asyncio
async def test_llm_match_unavailable_returns_none() -> None:
    """When no LLM is configured, _llm_match returns None immediately."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock())  # no llm

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    assert season is None
    assert episode_num is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_llm_match_no_episodes_returns_none() -> None:
    """When the show has no episode rows at all, returns None without calling the LLM."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock()

    session = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=empty)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    assert season is None
    assert episode_num is None
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_llm_match_complete_raises_returns_none() -> None:
    """An exception from llm.complete() is caught; None is returned."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_response_none_returns_none() -> None:
    """llm.complete() returning None yields None."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_invalid_json_returns_none() -> None:
    """Malformed JSON from the LLM is handled gracefully."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    mock_response = MagicMock()
    mock_response.content = "not json at all"
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_non_dict_json_returns_none() -> None:
    """Valid JSON that isn't a dict (e.g. a bare list) is handled gracefully."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    mock_response = MagicMock()
    mock_response.content = "[1, 2, 3]"
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_missing_season_or_episode_returns_none() -> None:
    """A JSON response missing season or episode is treated as no match."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    mock_response = MagicMock()
    mock_response.content = '{"season": null, "episode": null}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_non_integer_season_episode_returns_none() -> None:
    """Non-integer season/episode values in the LLM's JSON are handled gracefully."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    mock_response = MagicMock()
    mock_response.content = '{"season": "one", "episode": 1}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    # Only ONE execute() call is expected — the initial episode-list query.  The
    # non-integer season/episode values must short-circuit before any S/E lookup.
    session.execute = AsyncMock(return_value=eps_result)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    assert season is None
    assert episode_num is None
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_llm_match_success_returns_episode() -> None:
    """A valid LLM match resolves to the correct Episode row via a fresh S/E lookup."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    mock_response = MagicMock()
    mock_response.content = '{"season": 1, "episode": 5}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    matched_episode = _make_episode(id=5, show_id=1, season=1, episode=5)

    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 5, "The One")]

    match_result = MagicMock()
    match_result.scalar_one_or_none.return_value = matched_episode

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[eps_result, match_result])

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is matched_episode
    assert season == 1
    assert episode_num == 5


@pytest.mark.asyncio
async def test_llm_match_markdown_fence_stripped() -> None:
    """JSON wrapped in a code fence is still parsed correctly."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    mock_response = MagicMock()
    mock_response.content = '```json\n{"season": 2, "episode": 3}\n```'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    matched_episode = _make_episode(id=7, show_id=1, season=2, episode=3)

    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(2, 3)]
    match_result = MagicMock()
    match_result.scalar_one_or_none.return_value = matched_episode

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[eps_result, match_result])

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is matched_episode
    assert season == 2
    assert episode_num == 3


@pytest.mark.asyncio
async def test_llm_match_db_lookup_miss_returns_none() -> None:
    """A parsed season/episode with no matching Episode row in the DB returns None."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    mock_response = MagicMock()
    mock_response.content = '{"season": 9, "episode": 99}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    miss_result = MagicMock()
    miss_result.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[eps_result, miss_result])

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)
    assert ep is None
    # The proposed season/episode must still be surfaced even though no DB
    # row matched it — this is what the "No match" event downstream relies on.
    assert season == 9
    assert episode_num == 99


@pytest.mark.asyncio
async def test_llm_pick_candidate_markdown_fence_stripped() -> None:
    """JSON wrapped in a code fence is still parsed correctly."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '```json\n{"match": 1}\n```'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    result = await orch._llm_pick_candidate("Show", [{"name": "Show", "id": 1}])
    assert result == {"name": "Show", "id": 1}


@pytest.mark.asyncio
async def test_llm_pick_candidate_null_match_returns_none() -> None:
    """A valid JSON response with match=null means the LLM found no confident match."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    mock_response = MagicMock()
    mock_response.content = '{"match": null}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    result = await orch._llm_pick_candidate("Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_find_episode_llm_fills_in_season_when_originally_none() -> None:
    """When both season and episode are unknown, the LLM's season is adopted too."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    episode = _make_episode(id=8, show_id=1, season=4, episode=12)

    mock_response = MagicMock()
    mock_response.content = '{"season": 4, "episode": 12}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=hit)

    orch = PathImportOrchestrator(session, AsyncMock(), llm=llm)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\some_unusual_filename.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,  # regex could not determine season
        episode=None,  # regex could not determine episode either
        is_absolute=True,
    )

    ep, season, ep_num = await orch._find_episode(show_id=1, show_title="Show", entry=entry)
    assert ep is episode
    assert season == 4
    assert ep_num == 12
    # Confirms the S/E lookup ran with the LLM-supplied season (4), not a miss.
    assert session.execute.call_count == 1


# ---------------------------------------------------------------------------
# LLM fallback diagnostics — outcomes must be visible via on_event, not just
# the Python logger, and the final "No match" event must reflect any LLM
# adjustment rather than always the pre-LLM regex output.
# ---------------------------------------------------------------------------


def _event_capture() -> tuple[list[tuple[str, str, object]], Any]:
    events: list[tuple[str, str, object]] = []

    async def capture(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg, ctx))

    return events, capture


class TestLlmFallbackDiagnostics:
    async def test_run_emits_notice_when_llm_unavailable(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

        events, capture = _event_capture()
        session = AsyncMock()
        orch = PathImportOrchestrator(session, AsyncMock(), on_event=capture)

        await orch.run([])

        notices = [(lvl, msg) for lvl, msg, _ in events if "LLM not configured" in msg]
        assert len(notices) == 1
        assert notices[0][0] == "warn"

    async def test_run_does_not_emit_notice_when_llm_available(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

        events, capture = _event_capture()
        llm = MagicMock()
        llm.is_available.return_value = True
        session = AsyncMock()
        orch = PathImportOrchestrator(session, AsyncMock(), llm=llm, on_event=capture)

        await orch.run([])

        assert not [msg for _, msg, _ in events if "LLM not configured" in msg]

    async def test_llm_parse_episode_exception_is_emitted(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

        events, capture = _event_capture()
        llm = MagicMock()
        llm.is_available.return_value = True
        llm.complete = AsyncMock(side_effect=RuntimeError("connection refused"))

        orch = PathImportOrchestrator(AsyncMock(), AsyncMock(), llm=llm, on_event=capture)
        result = await orch._llm_parse_episode("Bamboo Blade 20.mkv")

        assert result == (None, None)
        failures = [(lvl, msg) for lvl, msg, _ in events if "episode-parse failed" in msg]
        assert len(failures) == 1
        assert failures[0][0] == "warn"
        assert "connection refused" in failures[0][1]

    async def test_llm_parse_episode_success_is_emitted(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

        events, capture = _event_capture()
        mock_response = MagicMock()
        mock_response.content = '{"season": null, "episode": 20}'
        llm = MagicMock()
        llm.is_available.return_value = True
        llm.complete = AsyncMock(return_value=mock_response)

        orch = PathImportOrchestrator(AsyncMock(), AsyncMock(), llm=llm, on_event=capture)
        result = await orch._llm_parse_episode("Bamboo Blade 20.mkv")

        assert result == (None, 20)
        successes = [(lvl, msg, ctx) for lvl, msg, ctx in events if "LLM episode-parse:" in msg]
        assert len(successes) == 1
        assert successes[0][0] == "info"
        assert successes[0][2] == {
            "filename": "Bamboo Blade 20.mkv",
            "season": None,
            "episode": 20,
        }

    async def test_llm_match_exception_is_emitted(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
        from jidou.services.path_parser import ParsedPathEntry

        events, capture = _event_capture()
        llm = MagicMock()
        llm.is_available.return_value = True
        llm.complete = AsyncMock(side_effect=RuntimeError("timed out"))

        session = AsyncMock()
        eps_result = MagicMock()
        eps_result.scalars.return_value.all.return_value = [
            _make_episode(id=1, show_id=1, season=1, episode=1)
        ]
        session.execute = AsyncMock(return_value=eps_result)

        orch = PathImportOrchestrator(session, AsyncMock(), llm=llm, on_event=capture)
        entry = ParsedPathEntry(
            raw_path=r"Z:\tv\Show\Show 01.mkv",
            show_dir="Show",
            show_root=r"Z:\tv\Show",
            season=None,
            episode=1,
            is_absolute=True,
        )

        ep, season, episode_num = await orch._llm_match(show_id=1, show_title="Show", entry=entry)

        assert ep is None
        assert season is None
        assert episode_num is None
        failures = [(lvl, msg) for lvl, msg, _ in events if "episode-list match failed" in msg]
        assert len(failures) == 1
        assert failures[0][0] == "warn"
        assert "timed out" in failures[0][1]

    async def test_llm_pick_candidate_exception_is_emitted(self) -> None:
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

        events, capture = _event_capture()
        llm = MagicMock()
        llm.is_available.return_value = True
        llm.complete = AsyncMock(side_effect=RuntimeError("bad gateway"))

        orch = PathImportOrchestrator(AsyncMock(), AsyncMock(), llm=llm, on_event=capture)
        result = await orch._llm_pick_candidate("Show", [{"name": "Show", "id": 1}])

        assert result is None
        failures = [(lvl, msg) for lvl, msg, _ in events if "show-match failed" in msg]
        assert len(failures) == 1
        assert failures[0][0] == "warn"
        assert "bad gateway" in failures[0][1]

    async def test_no_match_event_reflects_llm_resolved_season_episode(self) -> None:
        """The final 'No match' event must show the LLM-adjusted season/episode,
        not the pre-LLM regex output that entry.season/entry.episode still hold.
        """
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
        from jidou.services.path_parser import ParsedPathEntry

        events, capture = _event_capture()
        mock_response = MagicMock()
        mock_response.content = '{"season": null, "episode": 20}'
        llm = MagicMock()
        llm.is_available.return_value = True
        llm.complete = AsyncMock(return_value=mock_response)

        session = AsyncMock()
        miss = MagicMock()
        miss.scalar_one_or_none.return_value = None
        eps_result = MagicMock()
        eps_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[miss, miss, eps_result])

        show = MagicMock(
            id=1, title="Bamboo Blade", tmdb_id=1, local_path="Z:\\anime tv\\Bamboo Blade"
        )
        orch = PathImportOrchestrator(session, AsyncMock(), llm=llm, on_event=capture)

        entry = ParsedPathEntry(
            raw_path=r"Z:\anime tv\Bamboo Blade\Bamboo Blade 20.mkv",
            show_dir="Bamboo Blade",
            show_root=r"Z:\anime tv\Bamboo Blade",
            season=None,
            episode=None,  # regex could not parse "Bamboo Blade 20"
            is_absolute=False,
        )

        with patch.object(orch, "_db_find_show", AsyncMock(return_value=show)):
            await orch._import_show("Bamboo Blade", [entry])

        no_match = [(lvl, msg, ctx) for lvl, msg, ctx in events if msg.startswith("No match:")]
        assert len(no_match) == 1
        # Regex alone would have logged (S?E?) — the LLM resolved episode=20.
        assert no_match[0][1] == "No match: Bamboo Blade 20.mkv (S?E20)"
        assert no_match[0][2]["season"] is None
        assert no_match[0][2]["episode"] == 20

    async def test_find_episode_surfaces_llm_season_when_episode_still_none(self) -> None:
        """Bugbot-caught regression: _llm_parse_episode can resolve a season
        without an episode. That season must not be silently discarded just
        because the overall attempt still failed.
        """
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
        from jidou.services.path_parser import ParsedPathEntry

        mock_response = MagicMock()
        mock_response.content = '{"season": 2, "episode": null}'
        llm = MagicMock()
        llm.is_available.return_value = True
        llm.complete = AsyncMock(return_value=mock_response)

        orch = PathImportOrchestrator(AsyncMock(), AsyncMock(), llm=llm)
        entry = ParsedPathEntry(
            raw_path=r"Z:\tv\Show\Show Extras.mkv",
            show_dir="Show",
            show_root=r"Z:\tv\Show",
            season=None,  # regex found no season either
            episode=None,
            is_absolute=True,
        )

        ep, season, episode_num = await orch._find_episode(
            show_id=1, show_title="Show", entry=entry
        )

        assert ep is None
        assert season == 2  # LLM's season must be surfaced, not discarded
        assert episode_num is None

    async def test_find_episode_uses_llm_match_season_episode_over_stale_locals(self) -> None:
        """Bugbot-caught regression: when _llm_match proposes a season/episode
        that has no matching DB row, _find_episode must report what
        _llm_match actually proposed, not the season/episode from before
        _llm_match ran, so the "No match" event agrees with the separate
        "LLM episode-list match proposed ..." warn event.
        """
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
        from jidou.services.path_parser import ParsedPathEntry

        session = AsyncMock()
        miss = MagicMock()
        miss.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=miss)

        orch = PathImportOrchestrator(session, AsyncMock())
        entry = ParsedPathEntry(
            raw_path=r"Z:\tv\Show\Season 3\Show.S03E99.mkv",
            show_dir="Show",
            show_root=r"Z:\tv\Show",
            season=3,
            episode=99,
            is_absolute=False,
        )

        # _llm_match proposed S05E10, distinct from the pre-existing S03E99.
        with patch.object(orch, "_llm_match", AsyncMock(return_value=(None, 5, 10))):
            ep, season, episode_num = await orch._find_episode(
                show_id=1, show_title="Show", entry=entry
            )

        assert ep is None
        assert season == 5
        assert episode_num == 10
