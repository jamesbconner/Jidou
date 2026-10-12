"""Tests for path-file batch import — parser and orchestrator."""

import os
import pprint
import sys
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.file_filters import MEDIA_EXTENSIONS
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

    @pytest.mark.parametrize("ext", sorted(MEDIA_EXTENSIONS))
    def test_parse_line_accepts_every_scan_extension(self, ext: str) -> None:
        # Bulk import must track every extension the SFTP scan tracks (D19).
        assert len(MEDIA_EXTENSIONS) >= 12
        entry = parse_line(rf"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E03{ext}")
        assert entry is not None
        assert entry.show_dir == "Dorohedoro"

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

    def test_raw_path_is_encoded_for_literal_percent(self) -> None:
        """raw_path is run through encode_path_bytes, matching scan_show_directory.

        Regression test: without this, a bulk-imported file with a literal
        '%' in its name would store an unencoded local_path, which no longer
        compares equal to a later scan-local-files result for the same file
        (scan_show_directory always escapes '%' — see path_transport.py).
        show_root/show_dir must NOT be encoded — show_root can become
        show.local_path, a real filesystem path.
        """
        line = r"Z:\anime tv\Show\Season 01\100% Complete.S01E01.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.raw_path == r"Z:\anime tv\Show\Season 01\100%25 Complete.S01E01.mkv"
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\Show"))

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

    def test_compact_excludes_current_year_release_tag(self) -> None:
        # A scene-release year tag for "this year" must never be treated as
        # a compact SxxExx guess. The exclusion upper bound tracks the
        # current year dynamically (see _YEAR_EXCLUSION_HEADROOM_YEARS)
        # rather than a fixed cutoff that would eventually go stale.
        year = date.today().year
        line = rf"Z:\tv\Show\Show.Name.{year}.1080p.WEB-DL.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season is None
        assert entry.episode is None

    def test_compact_excludes_near_future_release_tag(self) -> None:
        # Headroom beyond "this year" so a near-future release date is also
        # excluded, not just the current year.
        year = date.today().year + 2
        line = rf"Z:\tv\Show\Show.Name.{year}.1080p.WEB-DL.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season is None
        assert entry.episode is None

    def test_compact_excludes_year_1900_lower_bound(self) -> None:
        line = r"Z:\tv\Show\Show.Name.1900.DVDRip.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season is None
        assert entry.episode is None

    def test_compact_matches_number_beyond_year_exclusion_headroom(self) -> None:
        # A bare compact token safely past the headroom window is still
        # parsed as a season/episode guess, not swallowed by the exclusion.
        year = date.today().year + 3
        line = rf"Z:\tv\Show\Show.Name.{year}.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == year // 100
        assert entry.episode == year % 100

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
# path_parser — directories_only (shows_only import mode)
# ---------------------------------------------------------------------------


class TestParseLineDirectoriesOnly:
    def test_directory_line_with_trailing_backslash(self) -> None:
        entry = parse_line(
            "Z:\\anime tv\\Wistoria Wand and Sword\\",
            root=r"Z:\anime tv",
            directories_only=True,
        )
        assert entry is not None
        assert entry.show_dir == "Wistoria Wand and Sword"
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\Wistoria Wand and Sword"))
        assert entry.season is None
        assert entry.episode is None
        assert entry.is_absolute is False

    def test_directory_line_without_trailing_separator(self) -> None:
        """The mode flag is the signal, not the trailing slash — a bare
        directory line works identically with or without one."""
        entry = parse_line(r"Z:\anime tv\KILL BLUE", root=r"Z:\anime tv", directories_only=True)
        assert entry is not None
        assert entry.show_dir == "KILL BLUE"
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\KILL BLUE"))

    def test_directory_line_raw_path_is_encoded_for_literal_percent(self) -> None:
        """raw_path is encoded here too, for the same reason as the file-line case —
        show_root stays unencoded since it can become show.local_path."""
        entry = parse_line("Z:\\anime tv\\100% Anime\\", root=r"Z:\anime tv", directories_only=True)
        assert entry is not None
        assert entry.raw_path == r"Z:\anime tv\100%25 Anime"
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\100% Anime"))

    def test_directory_line_rejected_when_directories_only_false(self) -> None:
        """Backward compatible: without the mode flag, a non-media line is
        still just skipped, exactly as before this feature existed."""
        entry = parse_line("Z:\\anime tv\\KILL BLUE\\", root=r"Z:\anime tv")
        assert entry is None

    def test_media_extension_line_still_parses_normally_in_directories_only_mode(
        self,
    ) -> None:
        """A full per-episode file path still works even with directories_only=True
        — a directory listing and a file listing can be mixed in one import."""
        entry = parse_line(
            r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E01.mkv",
            root=r"Z:\anime tv",
            directories_only=True,
        )
        assert entry is not None
        assert entry.show_dir == "Dorohedoro"
        assert entry.season == 1
        assert entry.episode == 1

    def test_directory_line_no_root_configured_uses_last_segment(self) -> None:
        entry = parse_line("Z:\\anime tv\\KILL BLUE\\", directories_only=True)
        assert entry is not None
        assert entry.show_dir == "KILL BLUE"
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\KILL BLUE"))

    def test_directory_line_not_under_root_falls_back(self) -> None:
        entry = parse_line(
            "Z:\\anime tv\\KILL BLUE\\", root=r"D:\some\other\root", directories_only=True
        )
        assert entry is not None
        assert entry.show_dir == "KILL BLUE"

    def test_nested_subdirectory_still_resolves_to_anchored_show_dir(self) -> None:
        """A directory-only line pointing at a subfolder under the show (e.g. a
        bonus-content folder) still anchors to the show itself, not the subfolder."""
        entry = parse_line(
            "Z:\\anime tv\\Gurren Lagann\\Clean Intro & Endings\\",
            root=r"Z:\anime tv",
            directories_only=True,
        )
        assert entry is not None
        assert entry.show_dir == "Gurren Lagann"
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\Gurren Lagann"))

    def test_line_that_is_exactly_the_root_returns_none(self) -> None:
        entry = parse_line("Z:\\anime tv\\", root=r"Z:\anime tv", directories_only=True)
        assert entry is None

    def test_posix_directory_line(self) -> None:
        entry = parse_line(
            "/mnt/media/anime/Dorohedoro", root="/mnt/media/anime", directories_only=True
        )
        assert entry is not None
        assert entry.show_dir == "Dorohedoro"

    def test_parse_file_directories_only_mixed_with_file_lines(self) -> None:
        content = "\n".join(
            [
                "Z:\\anime tv\\KILL BLUE\\",
                r"Z:\anime tv\Wistoria Wand and Sword",
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E01.mkv",
                "# a comment",
                "",
            ]
        )
        entries = parse_file(content, root=r"Z:\anime tv", directories_only=True)
        assert {e.show_dir for e in entries} == {
            "KILL BLUE",
            "Wistoria Wand and Sword",
            "Dorohedoro",
        }
        dorohedoro = next(e for e in entries if e.show_dir == "Dorohedoro")
        assert dorohedoro.episode == 1


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
# path_parser — scan_show_directory (real filesystem I/O via tmp_path)
# ---------------------------------------------------------------------------


class TestScanShowDirectory:
    def test_returns_empty_list_when_directory_missing(self, tmp_path: Path) -> None:
        from jidou.services.path_parser import scan_show_directory

        assert scan_show_directory(str(tmp_path / "does-not-exist")) == []

    def test_recursive_false_ignores_subdirectory_files(self, tmp_path: Path) -> None:
        """recursive=False (movie scan) lists only top-level files.

        Used when show_root is a shared root (e.g. the movies base path)
        rather than a directory exclusive to one show — descending would
        surface other titles' files.
        """
        from jidou.services.path_parser import scan_show_directory

        (tmp_path / "Top Level Movie.mkv").write_text("x")
        subdir = tmp_path / "Some Other Title (2019)"
        subdir.mkdir()
        (subdir / "Some Other Title.mkv").write_text("x")

        entries = scan_show_directory(str(tmp_path), recursive=False)
        assert len(entries) == 1
        assert Path(entries[0].raw_path).name == "Top Level Movie.mkv"

    def test_finds_media_files_in_season_subfolders(self, tmp_path: Path) -> None:
        from jidou.services.path_parser import scan_show_directory

        season_dir = tmp_path / "Season 01"
        season_dir.mkdir()
        (season_dir / "Show.S01E01.mkv").write_text("x")
        (season_dir / "Show.S01E02.mkv").write_text("x")
        (tmp_path / "readme.txt").write_text("not media")

        entries = scan_show_directory(str(tmp_path))
        assert len(entries) == 2
        assert {e.episode for e in entries} == {1, 2}
        assert all(e.season == 1 for e in entries)
        assert all(e.show_dir == tmp_path.name for e in entries)

    def test_season_from_directory_overrides_filename_when_present(self, tmp_path: Path) -> None:
        from jidou.services.path_parser import scan_show_directory

        season_dir = tmp_path / "Season 02"
        season_dir.mkdir()
        (season_dir / "Show - 05.mkv").write_text("x")

        entries = scan_show_directory(str(tmp_path))
        assert len(entries) == 1
        assert entries[0].season == 2
        assert entries[0].episode == 5

    def test_absolute_numbering_with_no_season_folder(self, tmp_path: Path) -> None:
        from jidou.services.path_parser import scan_show_directory

        (tmp_path / "HxH - 146.mkv").write_text("x")

        entries = scan_show_directory(str(tmp_path))
        assert len(entries) == 1
        assert entries[0].season is None
        assert entries[0].episode == 146
        assert entries[0].is_absolute is True

    def test_nested_bonus_content_directory_still_scanned(self, tmp_path: Path) -> None:
        from jidou.services.path_parser import scan_show_directory

        bonus_dir = tmp_path / "Season 01" / "Extras"
        bonus_dir.mkdir(parents=True)
        (bonus_dir / "Show.S01E01.mkv").write_text("x")

        entries = scan_show_directory(str(tmp_path))
        assert len(entries) == 1
        assert entries[0].season == 1
        assert entries[0].episode == 1

    def test_symlinked_season_directory_is_scanned(self, tmp_path: Path) -> None:
        """A season folder relocated to another drive/mount and replaced with
        a symlink must still be scanned — regression test for pathlib's
        rglob("*") silently never descending into symlinked directories
        (true on every current Python version, not just 3.13)."""
        from jidou.services.path_parser import scan_show_directory

        show_dir = tmp_path / "show"
        real_season = tmp_path / "real_season_02"
        show_dir.mkdir()
        real_season.mkdir()
        (show_dir / "Season 01").mkdir()
        (show_dir / "Season 01" / "Show.S01E01.mkv").write_text("x")
        (real_season / "Show.S02E01.mkv").write_text("x")

        try:
            (show_dir / "Season 02").symlink_to(real_season, target_is_directory=True)
        except OSError:
            pytest.skip("Creating symlinks requires elevated privileges on this platform")

        entries = scan_show_directory(str(show_dir))
        assert {(e.season, e.episode) for e in entries} == {(1, 1), (2, 1)}

    def test_symlink_cycle_does_not_hang(self, tmp_path: Path) -> None:
        """A symlink cycle (e.g. a stray symlink pointing back at an
        ancestor directory) must not make the walk recurse forever —
        regression test for the followlinks=True walk introduced to fix
        symlinked season directories."""
        from jidou.services.path_parser import scan_show_directory

        show_dir = tmp_path / "show"
        (show_dir / "Season 01").mkdir(parents=True)
        (show_dir / "Season 01" / "Show.S01E01.mkv").write_text("x")

        try:
            (show_dir / "Season 01" / "loop").symlink_to(show_dir, target_is_directory=True)
        except OSError:
            pytest.skip("Creating symlinks requires elevated privileges on this platform")

        entries = scan_show_directory(str(show_dir))
        # Asserted as both count and set: a failed cycle guard would revisit
        # "Season 01" through the loop symlink on every pass, producing
        # duplicate S01E01 entries that a set-only comparison would hide.
        assert len(entries) == 1
        assert {(e.season, e.episode) for e in entries} == {(1, 1)}

    def test_results_sorted_by_path(self, tmp_path: Path) -> None:
        from jidou.services.path_parser import scan_show_directory

        (tmp_path / "Show - 02.mkv").write_text("x")
        (tmp_path / "Show - 01.mkv").write_text("x")

        entries = scan_show_directory(str(tmp_path))
        assert [e.raw_path for e in entries] == sorted(e.raw_path for e in entries)

    def test_sample_file_excluded(self, tmp_path: Path) -> None:
        """A file with 'sample' in its name is excluded, matching file_filters.py
        (the same rule the SFTP scan pipeline already applies)."""
        from jidou.services.path_parser import scan_show_directory

        (tmp_path / "Show.S01E01.sample.mkv").write_text("x")
        (tmp_path / "Show.S01E01.mkv").write_text("x")

        entries = scan_show_directory(str(tmp_path))
        assert [Path(e.raw_path).name for e in entries] == ["Show.S01E01.mkv"]

    def test_sample_directory_pruned(self, tmp_path: Path) -> None:
        """Files inside a 'Sample'-named directory are excluded entirely."""
        from jidou.services.path_parser import scan_show_directory

        sample_dir = tmp_path / "Sample"
        sample_dir.mkdir()
        (sample_dir / "preview.mkv").write_text("x")
        (tmp_path / "Show.S01E01.mkv").write_text("x")

        entries = scan_show_directory(str(tmp_path))
        assert [Path(e.raw_path).name for e in entries] == ["Show.S01E01.mkv"]

    @pytest.mark.skipif(
        sys.platform != "linux",
        reason=(
            "Reproducing the bug requires creating a file with a raw non-UTF-8 byte in its "
            "name. NTFS (Windows) stores filenames as UTF-16, so this scenario doesn't apply "
            "there; APFS (macOS) validates filenames as UTF-8 at the filesystem level and "
            "rejects the write outright (OSError: Illegal byte sequence). Linux (and the "
            "production Docker containers, which are always Linux) treats filenames as "
            "opaque bytes, which is exactly what triggers the surrogateescape decode this "
            "test guards against."
        ),
    )
    def test_non_utf8_filename_does_not_crash(self, tmp_path: Path) -> None:
        """A filename with a raw non-UTF-8 byte (e.g. a legacy Latin-1 name from
        an older NAS/Windows share) must not crash the scan — regression test
        for UnicodeEncodeError: 'utf-8' codec can't encode character '\\udce9'.
        raw_path must also decode back to the exact original bytes, so the
        file can still be located on disk when confirming a match (see
        path_transport.decode_path_bytes and link_episode_file).
        """
        from jidou.services.path_parser import scan_show_directory
        from jidou.services.path_transport import decode_path_bytes

        # Byte 0xE9 is 'é' in Latin-1/cp1252 but invalid standalone UTF-8;
        # Python surrogateescape-decodes it to '\udce9' when reading it back
        # via pathlib, reproducing the bug through a real filesystem read.
        bad_name = b"Show.S01E01.Am\xe9lie.mkv"
        full_path = os.path.join(os.fsencode(str(tmp_path)), bad_name)
        with open(full_path, "wb") as f:
            f.write(b"x")

        entries = scan_show_directory(str(tmp_path))

        assert len(entries) == 1
        # Must survive UTF-8 JSON encoding — this is exactly what a FastAPI
        # response does and what previously raised UnicodeEncodeError.
        entries[0].raw_path.encode("utf-8")
        assert entries[0].raw_path.encode("utf-8").decode("utf-8") == entries[0].raw_path
        # The unrecoverable byte is percent-encoded; everything else in the
        # filename is preserved untouched (readable, not replaced/lossy).
        assert Path(entries[0].raw_path).name == "Show.S01E01.Am%E9lie.mkv"
        # Decoding it back resolves to the exact real file on disk.
        assert Path(decode_path_bytes(entries[0].raw_path)).is_file()
        assert entries[0].season == 1
        assert entries[0].episode == 1

    @pytest.mark.skipif(
        sys.platform != "linux",
        reason=(
            "Reproducing the bug requires creating a directory with a raw non-UTF-8 byte in "
            "its name. NTFS (Windows) stores filenames as UTF-16, so this scenario doesn't "
            "apply there; APFS (macOS) validates filenames as UTF-8 at the filesystem level "
            "and rejects the write outright. Linux (and the production Docker containers, "
            "which are always Linux) treats filenames as opaque bytes."
        ),
    )
    def test_recovers_legacy_cp1252_show_directory_name(self, tmp_path: Path) -> None:
        """Regression test: a show directory that predates Jidou (created by some
        other tool, e.g. an archive extractor) can have a raw cp1252-encoded byte
        for an accented character instead of UTF-8 -- cp1252 'é' is the single
        byte 0xE9; UTF-8 'é' is the two bytes 0xC3 0xA9. Show.local_path in the
        database is the clean UTF-8 string, so a literal Path(local_path).is_dir()
        fails even though the directory is right there, and scan_show_directory
        previously returned [] unconditionally -- exactly the "No new media files
        found" symptom reported for a show with 'é' in its title."""
        from jidou.services.path_parser import scan_show_directory

        # Byte 0xE9 stands in for the UTF-8 "é" (0xC3 0xA9) the database expects.
        bad_dir_bytes = os.path.join(os.fsencode(str(tmp_path)), b"Am\xe9lie")
        os.mkdir(bad_dir_bytes)
        with open(os.path.join(bad_dir_bytes, b"Show.S01E01.mkv"), "wb") as f:
            f.write(b"x")

        clean_local_path = str(tmp_path / "Amélie")
        entries = scan_show_directory(clean_local_path)

        assert len(entries) == 1
        assert entries[0].season == 1
        assert entries[0].episode == 1

    def test_no_matching_directory_returns_empty_list(self, tmp_path: Path) -> None:
        """A show_root with no cp1252-recoverable match in the parent directory
        still returns [] rather than raising."""
        from jidou.services.path_parser import scan_show_directory

        (tmp_path / "Some Other Show").mkdir()

        assert scan_show_directory(str(tmp_path / "Amélie")) == []


class TestPathComparisonKey:
    def test_same_posix_path_matches_itself(self) -> None:
        from jidou.services.path_parser import path_comparison_key

        assert path_comparison_key("/data/media/anime/Show/Season 01/ep.mkv") == (
            path_comparison_key("/data/media/anime/Show/Season 01/ep.mkv")
        )

    def test_windows_and_posix_style_match_when_suffix_agrees(self) -> None:
        """A Windows-style bulk-import path and a POSIX-style live scan path
        for the same show/season/filename compare equal, even though the
        roots are completely different strings."""
        from jidou.services.path_parser import path_comparison_key

        windows_style = r"Z:\anime tv\Show\Season 01\Show - 01.mkv"
        posix_style = "/data/media/anime/Show/Season 01/Show - 01.mkv"
        assert path_comparison_key(windows_style) == path_comparison_key(posix_style)

    def test_different_filename_does_not_match(self) -> None:
        from jidou.services.path_parser import path_comparison_key

        a = "/data/media/anime/Show/Season 01/Show - 01.mkv"
        b = "/data/media/anime/Show/Season 01/Show - 02.mkv"
        assert path_comparison_key(a) != path_comparison_key(b)

    def test_case_insensitive(self) -> None:
        from jidou.services.path_parser import path_comparison_key

        assert path_comparison_key("/data/Show/Season 01/EP.MKV") == path_comparison_key(
            "/data/show/season 01/ep.mkv"
        )


class TestDetectSeasonFromSegments:
    def test_returns_season_from_matching_segment(self) -> None:
        from jidou.services.path_parser import _detect_season_from_segments

        assert _detect_season_from_segments(["Season 02", "Extras"]) == 2

    def test_returns_none_when_no_segment_matches(self) -> None:
        from jidou.services.path_parser import _detect_season_from_segments

        assert _detect_season_from_segments(["Extras", "Misc"]) is None

    def test_first_match_wins(self) -> None:
        from jidou.services.path_parser import _detect_season_from_segments

        assert _detect_season_from_segments(["Season 02", "Season 01"]) == 2


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


def _make_show(
    *,
    id: int = 1,
    tmdb_id: int = 999,
    title: str = "Dorohedoro",
    content_type: str = "anime",
) -> MagicMock:
    s = MagicMock()
    s.id = id
    s.tmdb_id = tmdb_id
    s.title = title
    s.aliases = []
    s.content_type = content_type
    s.media_type = "tv"
    s.sys_name = title
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
    """show.local_path is computed from content_type/sys_name, not entries[0].show_root.

    Regression test: entries[0].show_root is the raw *host-side* path typed
    into the import file (e.g. a UNC path like ``//nas-1821/video/tv/...``),
    not the container-side path that scan_show_directory/RouteOrchestrator
    expect. See jidou.services.path_resolution.resolve_show_local_path.
    """
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

    show = _make_show(content_type="anime")
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

    assert show.local_path == "/data/media/anime/Dorohedoro"
    assert show.local_path != entries[0].show_root


@pytest.mark.asyncio
async def test_orchestrator_sets_local_path_from_container_base_for_content_type() -> None:
    """A tv-content-type show gets the configured tv base, not the anime one.

    Regression test for the bug where a TV show bulk-imported from a
    Windows/UNC host path (e.g. ``//nas-1821/video/tv/The Boys``) ended up
    with that host path stored verbatim as local_path, breaking
    scan_show_directory (and RouteOrchestrator) since neither can see that
    path inside the container.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"\\nas-1821\video\tv\The Boys\Season 1\ep.mkv",
            show_dir="The Boys",
            show_root=r"\\nas-1821\video\tv\The Boys",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show(title="The Boys", content_type="tv")
    show.local_path = None

    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute.return_value = ep_result
    session.commit = AsyncMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(
        session,
        tmdb,
        local_tv_path="/data/media/tv",
        local_anime_path="/data/media/anime",
        local_movie_path="/data/media/movies",
    )

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        await orch.run(entries)

    assert show.local_path == "/data/media/tv/The Boys"
    assert show.local_path != entries[0].show_root


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


@pytest.mark.asyncio
async def test_import_show_backfills_episode_group_map_for_already_synced_show() -> None:
    """An existing show with episodes already synced but no episode_group_map
    (e.g. synced before this feature existed) must still get the map
    backfilled via ensure_episode_group_map so the cour/season remap works.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Frieren\Season 01\ep.mkv",
            show_dir="Frieren",
            show_root=r"Z:\anime tv\Frieren",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show(title="Frieren")
    show.episode_group_map = None
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=5)  # ep_count > 0 -> no full re-sync
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
        mock_tmdb_orch_cls.return_value.ensure_episode_group_map = AsyncMock()
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        result = await orch.run(entries)

    mock_tmdb_orch_cls.return_value.ensure_episode_group_map.assert_called_once_with(show)
    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_not_called()
    assert result.shows_found == 1
    assert result.episodes_tracked == 1


@pytest.mark.asyncio
async def test_import_show_skips_backfill_when_episode_group_map_already_set() -> None:
    """An already-synced show whose episode_group_map is already populated
    (even if it's an empty dict, meaning 'checked, no groups exist') must
    not trigger a redundant backfill call on every import touch.
    """
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
    show.episode_group_map = {"6": {"1": {"1": [1, 1]}}}
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=5)
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
        mock_tmdb_orch_cls.return_value.ensure_episode_group_map = AsyncMock()
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        await orch.run(entries)

    mock_tmdb_orch_cls.return_value.ensure_episode_group_map.assert_called_once_with(show)
    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_not_called()


@pytest.mark.asyncio
async def test_import_show_skips_backfill_when_episode_group_map_is_confirmed_empty() -> None:
    """An empty dict ({}) means 'checked, TMDB has no qualifying groups' —
    must not trigger a redundant backfill call on every import touch,
    distinguishing it from None ('never checked').
    """
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
    show.episode_group_map = {}  # confirmed empty — not the same as None
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=5)
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
        mock_tmdb_orch_cls.return_value.ensure_episode_group_map = AsyncMock()
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        await orch.run(entries)

    mock_tmdb_orch_cls.return_value.ensure_episode_group_map.assert_called_once_with(show)
    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_not_called()


@pytest.mark.asyncio
async def test_import_show_episode_group_map_backfill_failure_logged_not_raised() -> None:
    """An ensure_episode_group_map failure for an already-synced show is logged, not raised."""
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
    show.episode_group_map = None
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=5)
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
        patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.ensure_episode_group_map = AsyncMock(
            side_effect=RuntimeError("TMDB down")
        )
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        result = await orch.run(entries)  # must not raise

    assert result.shows_found == 1
    assert result.episodes_tracked == 1


@pytest.mark.asyncio
async def test_import_show_backfills_episode_group_map_in_dry_run_too() -> None:
    """Bugbot-caught regression: dry_run must not skip ensure_episode_group_map
    for an already-synced show. episode_group_map/absolute_episode_number are
    derived TMDB cache data, not a user-visible import side effect -- skipping
    the backfill in dry_run would make a preview's matching diverge from what
    a real run actually resolves (e.g. showing a file as unmatched in preview
    that a real run would match after the remap backfill).
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Frieren\Season 01\ep.mkv",
            show_dir="Frieren",
            show_root=r"Z:\anime tv\Frieren",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show(title="Frieren")
    show.episode_group_map = None
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=5)  # ep_count > 0
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=ep_result)

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb, dry_run=True)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.ensure_episode_group_map = AsyncMock()
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        result = await orch.run(entries)

    mock_tmdb_orch_cls.return_value.ensure_episode_group_map.assert_called_once_with(show)
    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_not_called()
    assert result.shows_found == 1
    assert result.episodes_tracked == 1
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_import_show_dry_run_skips_full_sync_for_never_synced_show() -> None:
    """dry_run must still skip the full sync_show_episodes call (a real DB
    write) when a found show has zero episodes -- only the read-only
    episode_group_map backfill is exempted from dry_run, not episode creation.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Frieren\Season 01\ep.mkv",
            show_dir="Frieren",
            show_root=r"Z:\anime tv\Frieren",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show(title="Frieren")

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=0)  # ep_count == 0
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=miss)

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb, dry_run=True)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.ensure_episode_group_map = AsyncMock()
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        await orch.run(entries)

    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_not_called()
    mock_tmdb_orch_cls.return_value.ensure_episode_group_map.assert_not_called()


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
    # Regression test (issue #424): without these, a later rematch's Phase 3
    # orphan-relink pass can never find this row.
    assert created_file.parsed_season == episode.season_number
    assert created_file.parsed_episode == episode.episode_number


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
        session: object,
        llm: object,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
        episode_group_map: dict | None = None,
        on_event: object = None,
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
        patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", fake_find_episode
        ),
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
async def test_import_show_per_entry_parse_failure_does_not_abort_batch() -> None:
    """One entry's parse_filename failure must not lose the rest of the show's batch.

    Regression test: parse_filename was called per-entry inside a loop with
    no try/except, so an unexpected exception on any single file would
    abort the whole directory's import instead of just that one file.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.filename_parser import FilenameParseResult
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Show - 01.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=None,
            episode=1,
            is_absolute=True,
        ),
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Show\Show - 02.mkv",
            show_dir="Show",
            show_root=r"Z:\anime tv\Show",
            season=None,
            episode=2,
            is_absolute=True,
        ),
    ]

    show = _make_show(id=1, tmdb_id=100, title="Show")
    show.aliases = []
    ep1 = _make_episode(id=10, show_id=1, season=1, episode=1)
    ep2 = _make_episode(id=11, show_id=1, season=1, episode=2)

    async def fake_parse_filename(filename: str, llm: object) -> FilenameParseResult:
        if "01" in filename:
            raise RuntimeError("unexpected LLM client failure")
        return FilenameParseResult(
            show_name="Show",
            season=None,
            episode=2,
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
        return show, "found"

    async def fake_find_episode(
        session: object,
        llm: object,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
        episode_group_map: dict | None = None,
        on_event: object = None,
    ) -> tuple[MagicMock | None, int | None, int | None]:
        return (ep1, 1, 1) if entry.episode == 1 else (ep2, 1, 2)

    with (
        patch(
            "jidou.orchestrators.path_import_orchestrator.parse_filename",
            fake_parse_filename,
        ),
        patch.object(orch, "_resolve_show", fake_resolve_show),
        patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", fake_find_episode
        ),
    ):
        results = await orch._import_show("Show", entries)

    # Both entries end up in the same (non-split) result -- the failed
    # parse fell back to trusting the directory, same as a not-llm_ok result.
    assert len(results) == 1
    assert results[0].show_dir == "Show"
    assert results[0].episodes_tracked == 2


@pytest.mark.asyncio
async def test_import_show_split_does_not_auto_set_wrong_local_path() -> None:
    """Bugbot-caught regression: a split-off secondary show must not get
    local_path auto-set from entries[0].show_root — that reflects the
    *primary* directory's root (Gurren Lagann), not the secondary show's
    (Bleach) actual location, so writing it would point Bleach at Gurren
    Lagann's library folder.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.filename_parser import FilenameParseResult
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
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
    secondary_show.local_path = None

    async def fake_parse_filename(filename: str, llm: object) -> FilenameParseResult:
        return FilenameParseResult(
            show_name="Bleach",
            season=None,
            episode=None,
            crc32=None,
            content_type="anime",
            confidence=0.9,
            llm_ok=True,
        )

    session = AsyncMock()
    tmdb = AsyncMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    orch = PathImportOrchestrator(session, tmdb, llm=llm)

    async def fake_resolve_show(name: str) -> tuple[MagicMock, str]:
        if name == "Bleach":
            return secondary_show, "found"
        return primary_show, "found"

    async def fake_find_episode(
        session: object,
        llm: object,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
        episode_group_map: dict | None = None,
        on_event: object = None,
    ) -> tuple[None, None, None]:
        return None, None, None

    with (
        patch(
            "jidou.orchestrators.path_import_orchestrator.parse_filename",
            fake_parse_filename,
        ),
        patch.object(orch, "_resolve_show", fake_resolve_show),
        patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", fake_find_episode
        ),
    ):
        await orch._import_show("Gurren Lagann", entries)

    assert secondary_show.local_path is None


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
        session: object,
        llm: object,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
        episode_group_map: dict | None = None,
        on_event: object = None,
    ) -> tuple[MagicMock, int, int]:
        return episode, 1, 1

    with (
        patch(
            "jidou.orchestrators.path_import_orchestrator.parse_filename",
            fake_parse_filename,
        ),
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", fake_find_episode
        ),
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
        session: object,
        llm: object,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
        episode_group_map: dict | None = None,
        on_event: object = None,
    ) -> tuple[MagicMock | None, int | None, int | None]:
        if entry.episode == 1:
            return episode, 1, 1
        return None, 1, None

    with (
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", fake_find_episode
        ),
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

    with patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        with patch("jidou.orchestrators._show_provisioning.generate_aliases", AsyncMock()):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None
    assert show.external_ids == {}
    # episode_groups stays None (not []) on a failed fetch so a later sync
    # can retry, rather than being treated as TMDB-confirmed-empty forever.
    assert show.episode_groups is None


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

    with patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        with patch("jidou.orchestrators._show_provisioning.generate_aliases", AsyncMock()):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None
    assert show.adult is True


# ---------------------------------------------------------------------------
# _tmdb_create_show — IntegrityError race condition on insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tmdb_create_show_integrity_error_finds_existing_show() -> None:
    """A race-condition IntegrityError on insert falls back to a DB lookup by tmdb_id."""
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

    refind = AsyncMock(return_value=existing_show)
    with patch("jidou.orchestrators.path_import_orchestrator.find_show_by_tmdb_id", refind):
        show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "found"
    assert show is existing_show
    session.rollback.assert_called_once()
    refind.assert_awaited_once_with(session, 42)


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

    with patch(
        "jidou.orchestrators.path_import_orchestrator.find_show_by_tmdb_id",
        AsyncMock(return_value=None),
    ):
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

    with patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=RuntimeError("sync failed")
        )
        with patch("jidou.orchestrators._show_provisioning.generate_aliases", AsyncMock()):
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

    with patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        with patch(
            "jidou.orchestrators._show_provisioning.generate_aliases",
            AsyncMock(side_effect=RuntimeError("alias generation blew up")),
        ):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None


@pytest.mark.asyncio
async def test_tmdb_create_show_commits_before_episode_sync() -> None:
    """The new show row is committed before the best-effort sync/alias steps run.

    Regression test: without this checkpoint, a session.rollback() needed to
    recover from a failed sync_show_episodes()/generate_aliases() flush would
    also undo the show's own not-yet-committed INSERT.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    calls: list[str] = []

    session = AsyncMock()
    session.add = MagicMock(side_effect=lambda _obj: calls.append("add"))
    session.flush = AsyncMock(side_effect=lambda: calls.append("flush"))
    session.commit = AsyncMock(side_effect=lambda: calls.append("commit"))
    session.scalar = AsyncMock(return_value=10)

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb)

    with patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=lambda _show: calls.append("sync_episodes")
        )
        with patch(
            "jidou.orchestrators._show_provisioning.generate_aliases",
            AsyncMock(side_effect=lambda *a, **kw: calls.append("generate_aliases")),
        ):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None
    # commit must land before sync/alias -- not after, and not skipped.
    assert calls.index("commit") < calls.index("sync_episodes")
    assert calls.index("commit") < calls.index("generate_aliases")


@pytest.mark.asyncio
async def test_tmdb_create_show_episode_sync_failure_rolls_back() -> None:
    """A failed episode sync for a newly-created show rolls back the session.

    Without this, the session is left in SQLAlchemy's PendingRollbackError
    state, and the very next DB operation -- the next show in this import
    batch, alias generation's own flush, etc. -- crashes on an unrelated,
    already-stale failure instead of proceeding.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb)

    with patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=RuntimeError("sync failed")
        )
        with patch("jidou.orchestrators._show_provisioning.generate_aliases", AsyncMock()):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None
    session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_tmdb_create_show_alias_generation_failure_rolls_back() -> None:
    """A failed alias generation for a newly-created show rolls back the session."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.scalar = AsyncMock(return_value=10)

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb)

    with patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        with patch(
            "jidou.orchestrators._show_provisioning.generate_aliases",
            AsyncMock(side_effect=RuntimeError("alias generation blew up")),
        ):
            show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created"
    assert show is not None
    session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_tmdb_create_show_integrity_error_fallback_syncs_missing_episodes() -> None:
    """Regression test for issue #413: the race-recovery fallback must run the
    same zero-episode check/sync the normal 'found in DB' path already has.

    Without this, the losing side of a concurrent show-creation race could
    see zero episodes (if the winning side's own sync hadn't finished yet)
    and report every file in its batch as unmatched -- a false negative
    caused entirely by timing, not a real data problem.
    """
    from sqlalchemy.exc import IntegrityError

    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}
    existing_show = _make_show(id=99, tmdb_id=42, title="SomeShow")

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup key")))
    session.rollback = AsyncMock()
    session.scalar = AsyncMock(return_value=0)  # no episodes synced yet

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch(
            "jidou.orchestrators.path_import_orchestrator.find_show_by_tmdb_id",
            AsyncMock(return_value=existing_show),
        ),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "found"
    assert show is existing_show
    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_awaited_once_with(existing_show)


@pytest.mark.asyncio
async def test_tmdb_create_show_integrity_error_fallback_skips_sync_when_episodes_exist() -> None:
    """The race-recovery fallback does not re-sync a show that already has episodes."""
    from sqlalchemy.exc import IntegrityError

    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    result_item = {"id": 42, "name": "SomeShow", "media_type": "tv"}
    existing_show = _make_show(id=99, tmdb_id=42, title="SomeShow")

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup key")))
    session.rollback = AsyncMock()
    session.scalar = AsyncMock(return_value=12)  # winning side's sync already finished

    tmdb = AsyncMock()
    tmdb.search = AsyncMock(return_value={"results": [result_item]})
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch(
            "jidou.orchestrators.path_import_orchestrator.find_show_by_tmdb_id",
            AsyncMock(return_value=existing_show),
        ),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.ensure_episode_group_map = AsyncMock()
        show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "found"
    assert show is existing_show
    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_not_called()
    mock_tmdb_orch_cls.return_value.ensure_episode_group_map.assert_awaited_once_with(existing_show)


# ---------------------------------------------------------------------------
# _resolve_show / _sync_episodes_if_needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_show_found_with_no_episodes_syncs_them() -> None:
    """An existing show with zero synced episodes is synced before being returned."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    show = _make_show()

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=0)

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock()
        result_show, action = await orch._resolve_show("SomeShow")

    assert action == "found"
    assert result_show is show
    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_awaited_once_with(show)


@pytest.mark.asyncio
async def test_resolve_show_episode_sync_failure_rolls_back() -> None:
    """Regression test for issue #412: a failed episode sync for an existing
    show rolls back the session rather than leaving it poisoned with
    PendingRollbackError for the next DB operation."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    show = _make_show()

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=0)
    session.rollback = AsyncMock()

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=RuntimeError("sync failed")
        )
        result_show, action = await orch._resolve_show("SomeShow")

    assert action == "found"
    assert result_show is show
    session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_show_found_with_episodes_ensures_group_map() -> None:
    """An existing show with episodes already synced skips re-sync but still
    ensures the episode_group_map is up to date."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    show = _make_show()

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=12)

    tmdb = AsyncMock()
    orch = PathImportOrchestrator(session, tmdb)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
        ) as mock_tmdb_orch_cls,
    ):
        mock_tmdb_orch_cls.return_value.ensure_episode_group_map = AsyncMock()
        result_show, action = await orch._resolve_show("SomeShow")

    assert action == "found"
    assert result_show is show
    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_not_called()
    mock_tmdb_orch_cls.return_value.ensure_episode_group_map.assert_awaited_once_with(show)


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


# ---------------------------------------------------------------------------
# _process_show_entries — same-batch resolution collisions
# (episodes_already_tracked)
# ---------------------------------------------------------------------------


class TestProcessShowEntriesDuplicateDetection:
    async def test_second_entry_resolving_to_same_episode_is_counted_separately(self) -> None:
        """Two files that both resolve to the same Episode row must not be
        silently absorbed into episodes_tracked or episodes_unmatched -- they're
        counted (and reported) as episodes_already_tracked instead. This is
        the observability half of the Frieren regression: even for a show the
        episode_groups remap doesn't perfectly handle, a resolution collision
        is never invisible.
        """
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
        from jidou.services.path_parser import ParsedPathEntry

        show = _make_show(id=1, tmdb_id=100, title="Frieren")
        show.local_path = r"Z:\anime tv\Frieren"
        show.episode_group_map = None
        shared_episode = _make_episode(id=42, show_id=1, season=1, episode=4)

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

        entries = [
            ParsedPathEntry(
                raw_path=r"Z:\anime tv\Frieren\Season 01\Frieren.S01E04.mkv",
                show_dir="Frieren",
                show_root=r"Z:\anime tv\Frieren",
                season=1,
                episode=4,
                is_absolute=False,
            ),
            ParsedPathEntry(
                raw_path=r"Z:\anime tv\Frieren\Season 02\Frieren.S02E01.mkv",
                show_dir="Frieren",
                show_root=r"Z:\anime tv\Frieren",
                season=2,
                episode=1,
                is_absolute=False,
            ),
        ]

        async def fake_find_episode(
            session: object,
            llm: object,
            show_id: int,
            show_title: str,
            entry: ParsedPathEntry,
            episode_group_map: dict | None = None,
            on_event: object = None,
        ) -> tuple[MagicMock, int | None, int | None]:
            return shared_episode, entry.season, entry.episode

        events, capture = _event_capture()
        orch = PathImportOrchestrator(session, AsyncMock(), on_event=capture)

        with patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", fake_find_episode
        ):
            result = await orch._process_show_entries("Frieren", show, "found", entries)

        assert result.episodes_tracked == 1
        assert result.episodes_already_tracked == 1
        assert result.episodes_unmatched == 0
        assert result.already_tracked_paths == [entries[1].raw_path]

        dup_events = [msg for _, msg, _ in events if "resolved to the same episode" in msg]
        assert len(dup_events) == 1
        assert "S01E04" in dup_events[0]

    async def test_cross_group_collision_detected_via_shared_episode_ids(self) -> None:
        """When primary and secondary groups (from _import_show's split logic)
        resolve to the same show and the same episode, the collision must be
        visible in episodes_already_tracked — not silently lost because each
        _process_show_entries call used to get its own fresh collision set.
        """
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
        from jidou.services.path_parser import ParsedPathEntry

        show = _make_show(id=1, tmdb_id=100, title="Frieren")
        show.local_path = r"Z:\anime tv\Frieren"
        show.episode_group_map = {}
        show.aliases = ["sousou no frieren"]
        shared_episode = _make_episode(id=42, show_id=1, season=1, episode=4)

        dedup_miss = MagicMock()
        dedup_miss.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(return_value=dedup_miss)
        session.commit = AsyncMock()
        session.scalar = AsyncMock(return_value=5)  # ep_count > 0
        session.add = MagicMock()
        nested_ctx = AsyncMock()
        nested_ctx.__aenter__.return_value = None
        nested_ctx.__aexit__.return_value = False
        session.begin_nested = MagicMock(return_value=nested_ctx)

        # Two entries that will end up in different groups (primary vs secondary)
        # but resolve to the same episode.
        entries = [
            ParsedPathEntry(
                raw_path=r"Z:\anime tv\Frieren\Season 01\Frieren.S01E04.mkv",
                show_dir="Frieren",
                show_root=r"Z:\anime tv\Frieren",
                season=1,
                episode=4,
                is_absolute=False,
            ),
            ParsedPathEntry(
                raw_path=r"Z:\anime tv\Frieren\Season 02\Other Show S02E01.mkv",
                show_dir="Frieren",
                show_root=r"Z:\anime tv\Frieren",
                season=2,
                episode=1,
                is_absolute=False,
            ),
        ]

        async def fake_find_episode(
            session: object,
            llm: object,
            show_id: int,
            show_title: str,
            entry: ParsedPathEntry,
            episode_group_map: dict | None = None,
            on_event: object = None,
        ) -> tuple[MagicMock, int | None, int | None]:
            # Both entries resolve to the same episode
            return shared_episode, entry.season, entry.episode

        from jidou.services.filename_parser import FilenameParseResult

        # Simulate: first file agrees with the show, second file disagrees
        # (LLM says it belongs to "Other Show") — triggering a split.
        call_count = {"n": 0}

        async def fake_parse_filename(filename: str, llm: object = None) -> FilenameParseResult:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First file: agrees with the primary show
                return FilenameParseResult(
                    show_name="Frieren",
                    season=1,
                    episode=4,
                    crc32=None,
                    content_type="anime",
                    confidence=0.95,
                    llm_ok=True,
                )
            else:
                # Second file: disagrees — LLM says "Other Show"
                return FilenameParseResult(
                    show_name="Other Show",
                    season=2,
                    episode=1,
                    crc32=None,
                    content_type="anime",
                    confidence=0.95,
                    llm_ok=True,
                )

        _events, capture = _event_capture()
        orch = PathImportOrchestrator(session, AsyncMock(), on_event=capture)

        with (
            patch.object(orch, "_db_find_show", AsyncMock(return_value=show)),
            patch(
                "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode",
                fake_find_episode,
            ),
            patch(
                "jidou.orchestrators.path_import_orchestrator.parse_filename",
                fake_parse_filename,
            ),
            # Secondary resolution finds the same show via alias
            patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        ):
            results = await orch._import_show("Frieren", entries)

        # Primary group: 1 file tracked (S01E04)
        # Secondary group: 1 file resolves to same episode → already_tracked
        total_tracked = sum(r.episodes_tracked for r in results)
        total_already = sum(r.episodes_already_tracked for r in results)
        total_unmatched = sum(r.episodes_unmatched for r in results)

        assert total_tracked == 1
        assert total_already == 1
        assert total_unmatched == 0


# ---------------------------------------------------------------------------
# Import modes: "shows_only" and "episodes_only" (issue #338)
# ---------------------------------------------------------------------------


def test_orchestrator_mode_defaults_to_full() -> None:
    """Omitting `mode=` keeps the pre-existing full-import behavior."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    orch = PathImportOrchestrator(AsyncMock(), AsyncMock())
    assert orch.mode == "full"


@pytest.mark.asyncio
async def test_path_import_result_mode_field_propagates() -> None:
    """PathImportResult.mode reflects the orchestrator's configured mode."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    for mode in ("full", "shows_only", "episodes_only"):
        orch = PathImportOrchestrator(AsyncMock(), AsyncMock(), mode=mode)
        result = await orch.run([])
        assert result.mode == mode


@pytest.mark.asyncio
async def test_shows_only_skips_episode_matching_loop() -> None:
    """mode='shows_only' resolves the show but never calls _find_episode."""
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
    session = AsyncMock()
    session.commit = AsyncMock()
    tmdb = AsyncMock()

    events, capture = _event_capture()
    orch = PathImportOrchestrator(session, tmdb, mode="shows_only", on_event=capture)
    find_episode_spy = AsyncMock()

    with (
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", find_episode_spy
        ),
    ):
        result = await orch.run(entries)

    find_episode_spy.assert_not_called()
    assert result.episodes_tracked == 0
    assert result.episodes_unmatched == 0
    assert result.mode == "shows_only"
    assert any("episode matching skipped" in msg for _, msg, _ in events)


@pytest.mark.asyncio
async def test_shows_only_directory_entry_skips_mismatch_check_entirely() -> None:
    """A directory-only ParsedPathEntry never reaches parse_filename() at all —
    its "filename" would just be its own directory name, so the check would
    only ever compare that name against a differently-normalized copy of
    itself, never a real second name.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import parse_file

    entries = parse_file("Z:\\anime tv\\KILL BLUE\\", root=r"Z:\anime tv", directories_only=True)
    assert len(entries) == 1
    assert entries[0].is_directory is True

    show = _make_show(title="KILL BLUE")
    show.aliases = []
    session = AsyncMock()
    session.commit = AsyncMock()
    tmdb = AsyncMock()
    llm = MagicMock()
    llm.is_available.return_value = True

    orch = PathImportOrchestrator(session, tmdb, llm=llm, mode="shows_only")
    parse_filename_spy = AsyncMock()

    with (
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        patch(
            "jidou.orchestrators.path_import_orchestrator.parse_filename",
            parse_filename_spy,
        ),
    ):
        results = await orch._import_show("KILL BLUE", entries)

    parse_filename_spy.assert_not_called()
    assert len(results) == 1  # no spurious split
    assert results[0].show_dir == "KILL BLUE"


@pytest.mark.asyncio
async def test_shows_only_directory_entry_does_not_false_split_on_llm_renormalization() -> None:
    """Regression: a directory-only entry must not get split off because the
    per-file LLM's title-cleanup pass normalizes its own directory name
    differently than _agrees_with_show's punctuation stripping does (e.g. a
    hyphenated compound word getting merged into one word by the LLM but
    turned into two space-separated words by punctuation stripping).

    Without the is_directory skip, this reproduces a real false-positive: the
    directory "Show Iron Blooded Orphans" resolves to a show titled
    "Show: Iron-Blooded Orphans", and the per-file LLM call on that directory
    name (treated as a "filename") returns "Show Ironblooded Orphans" —
    which disagrees with _agrees_with_show's normalized "show iron blooded
    orphans" (hyphen -> space, not merged), triggering a bogus split even
    though it's the same show being compared against a mangled copy of itself.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.filename_parser import FilenameParseResult
    from jidou.services.path_parser import parse_file

    entries = parse_file(
        "Z:\\anime tv\\Show Iron Blooded Orphans\\", root=r"Z:\anime tv", directories_only=True
    )
    assert len(entries) == 1

    show = _make_show(title="Show: Iron-Blooded Orphans")
    show.aliases = ["show iron blooded orphans"]
    session = AsyncMock()
    session.commit = AsyncMock()
    tmdb = AsyncMock()
    llm = MagicMock()
    llm.is_available.return_value = True

    orch = PathImportOrchestrator(session, tmdb, llm=llm, mode="shows_only")

    async def mangling_parse_filename(filename: str, llm_arg: object) -> FilenameParseResult:
        # Simulates the LLM merging "Iron Blooded" into one word during its
        # own title-cleanup pass -- this is real observed behavior, not a
        # contrived input.
        return FilenameParseResult(
            show_name=filename.replace("Iron Blooded", "Ironblooded"),
            season=None,
            episode=None,
            crc32=None,
            content_type="anime",
            confidence=0.9,
            llm_ok=True,
        )

    with (
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        patch(
            "jidou.orchestrators.path_import_orchestrator.parse_filename",
            mangling_parse_filename,
        ),
    ):
        results = await orch._import_show("Show Iron Blooded Orphans", entries)

    assert len(results) == 1  # no split, even though the mangled name would disagree
    assert results[0].show_dir == "Show Iron Blooded Orphans"
    assert results[0].action == "found"


@pytest.mark.asyncio
async def test_shows_only_skips_matching_for_dry_run_existing_show() -> None:
    """Regression: shows_only + dry_run on an *existing* show (show.id is not
    None) must not fall through into either the dry-run-estimate block or the
    real matching loop — both would otherwise populate non-zero counters.
    """
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

    show = _make_show()  # show.id = 1 — an already-existing show, not freshly created
    session = AsyncMock()
    tmdb = AsyncMock()

    orch = PathImportOrchestrator(session, tmdb, mode="shows_only", dry_run=True)
    find_episode_spy = AsyncMock()

    with (
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, "found"))),
        patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", find_episode_spy
        ),
    ):
        result = await orch.run(entries)

    find_episode_spy.assert_not_called()
    assert result.episodes_tracked == 0
    assert result.episodes_unmatched == 0


@pytest.mark.asyncio
async def test_episodes_only_never_calls_tmdb_search() -> None:
    """mode='episodes_only': a show not in the DB is reported unmatched;
    TMDB is never queried."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
    from jidou.services.path_parser import ParsedPathEntry

    entries = [
        ParsedPathEntry(
            raw_path=r"Z:\anime tv\Unknown Show\Season 01\ep.mkv",
            show_dir="Unknown Show",
            show_root=r"Z:\anime tv\Unknown Show",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    session = AsyncMock()
    tmdb = AsyncMock()

    orch = PathImportOrchestrator(session, tmdb, mode="episodes_only")

    with patch.object(orch, "_db_find_show", AsyncMock(return_value=None)):
        result = await orch.run(entries)

    tmdb.search.assert_not_called()
    assert result.shows_not_found == 1
    assert result.episodes_unmatched == 1


@pytest.mark.asyncio
async def test_episodes_only_matches_against_existing_show() -> None:
    """mode='episodes_only': normal episode matching proceeds unaffected for
    a show already in the DB — mirrors test_orchestrator_finds_existing_show.
    """
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

    orch = PathImportOrchestrator(session, tmdb, mode="episodes_only")
    result = await orch.run(entries)

    assert result.shows_found == 1
    assert result.episodes_tracked == 1
    tmdb.search.assert_not_called()


@pytest.mark.asyncio
async def test_episodes_only_skips_per_file_mismatch_check() -> None:
    """mode='episodes_only' never calls parse_filename() — no per-file
    mismatch split, even for a file whose name suggests a different show.
    """
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
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
    primary_episode = _make_episode(id=10, show_id=1, season=1, episode=1)

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
    orch = PathImportOrchestrator(session, tmdb, llm=llm, mode="episodes_only")

    parse_filename_spy = AsyncMock()

    async def fake_find_episode(
        session: object,
        llm: object,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
        episode_group_map: dict | None = None,
        on_event: object = None,
    ) -> tuple[MagicMock | None, int | None, int | None]:
        return primary_episode, 1, 1

    with (
        patch.object(orch, "_resolve_show", AsyncMock(return_value=(primary_show, "found"))),
        patch(
            "jidou.orchestrators.path_import_orchestrator.match_entry_to_episode", fake_find_episode
        ),
        patch(
            "jidou.orchestrators.path_import_orchestrator.parse_filename",
            parse_filename_spy,
        ),
    ):
        results = await orch._import_show("Gurren Lagann", entries)

    parse_filename_spy.assert_not_called()
    assert len(results) == 1
    assert results[0].show_dir == "Gurren Lagann"


# ---------------------------------------------------------------------------
# Episode-count reporting in _tmdb_create_show / _sync_episodes_if_needed
# (ORC-9 characterization: pins the emitted count text and the failure path).
# ---------------------------------------------------------------------------


async def _run_create_show(
    *, scalar_value: object, sync_error: Exception | None = None
) -> tuple[list[tuple[str, str]], AsyncMock]:
    """Drive a non-dry-run ``_tmdb_create_show`` and capture its (level, message) events."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    events: list[tuple[str, str]] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg))

    session = AsyncMock()
    session.add = MagicMock()
    session.scalar = AsyncMock(return_value=scalar_value)
    tmdb = AsyncMock()
    tmdb.search.return_value = {"results": [{"id": 61889, "name": "Daredevil", "media_type": "tv"}]}
    tmdb.get_details.return_value = {"name": "Daredevil", "id": 61889}
    tmdb.get_external_ids.return_value = {}
    tmdb.get_episode_groups.return_value = {"results": []}
    orch = PathImportOrchestrator(session, tmdb, on_event=capture_event)

    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as mock_tmdb_orch_cls,
        patch("jidou.orchestrators._show_provisioning.generate_aliases", AsyncMock()),
    ):
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock(side_effect=sync_error)
        _, action = await orch._tmdb_create_show("Daredevil")

    assert action == "created"
    return events, session.scalar


@pytest.mark.asyncio
async def test_create_show_reports_synced_episode_count() -> None:
    """After a successful episode sync, the event carries the show's episode count."""
    events, scalar = await _run_create_show(scalar_value=13)

    assert ("info", "Synced 13 episodes for 'Daredevil'") in events
    scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_show_reports_zero_synced_episodes() -> None:
    """A show whose sync produced no rows reports 0 rather than skipping the event."""
    events, _ = await _run_create_show(scalar_value=0)

    assert ("info", "Synced 0 episodes for 'Daredevil'") in events


@pytest.mark.asyncio
async def test_create_show_sync_failure_emits_error_and_skips_count() -> None:
    """A failed sync is reported as an error; the count is never queried or emitted."""
    events, scalar = await _run_create_show(scalar_value=5, sync_error=RuntimeError("boom"))

    assert ("error", "Episode sync failed for 'Daredevil': boom") in events
    assert not any(msg.startswith("Synced ") for _, msg in events)
    scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_show_found_with_episodes_does_not_resync() -> None:
    """A positive episode count skips the sync even though the show already exists."""
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=1)
    orch = PathImportOrchestrator(session, AsyncMock())
    show = _make_show()

    with patch(
        "jidou.orchestrators.path_import_orchestrator.TMDBOrchestrator"
    ) as mock_tmdb_orch_cls:
        await orch._sync_episodes_if_needed(show)

    mock_tmdb_orch_cls.return_value.sync_show_episodes.assert_not_called()
    session.scalar.assert_awaited_once()


# ---------------------------------------------------------------------------
# ORC-11 characterization: the full observable sequence of a path import
# (events, progress ticks, session writes, TMDB calls, collaborator calls),
# pinned before ``_process_show_entries`` / ``_tmdb_create_show`` were
# decomposed. Each scenario yields one ordered log compared against a golden
# value, so a refactor that reorders or drops any step fails here. The golden
# values were captured from, and verified against, the pre-refactor code.
# ---------------------------------------------------------------------------


def _orc11_entry(name: str, season: int | None = 1, episode: int | None = 1) -> Any:
    from jidou.services.path_parser import ParsedPathEntry

    return ParsedPathEntry(
        raw_path=rf"Z:\anime tv\Frieren\Season 01\{name}",
        show_dir="Frieren",
        show_root=r"Z:\anime tv\Frieren",
        season=season,
        episode=episode,
        is_absolute=season is None,
    )


def _orc11_raised(exc: Exception) -> tuple[str, str, str]:
    """Describe a propagated error; DB errors use ``orig`` to avoid version-specific doc URLs."""
    orig = getattr(exc, "orig", None)
    return ("raised", type(exc).__name__, str(orig if orig is not None else exc))


def _orc11_base(path: str) -> str:
    return path.rsplit("\\", 1)[-1]


class _Orc11Harness:
    """Records every observable step of a path import into one ordered ``log``."""

    def __init__(self, *, ep_count: int = 5, raise_in_event: str | None = None) -> None:
        self.log: list[tuple[Any, ...]] = []
        self.raise_in_event = raise_in_event
        self.ep_count = ep_count
        self.search_result: Any = {"results": [{"id": 77, "name": "Frieren", "media_type": "tv"}]}
        self.search_error: Exception | None = None
        self.details_error: Exception | None = None
        self.sync_error: Exception | None = None
        self.flush_error: Exception | None = None
        self.match_plan: dict[str, Any] = {}
        self.session = AsyncMock()
        self.session.add = MagicMock(
            side_effect=lambda obj: self.log.append(("add", type(obj).__name__))
        )
        self.session.commit = AsyncMock(side_effect=lambda: self.log.append(("commit",)))
        self.session.rollback = AsyncMock(side_effect=lambda: self.log.append(("rollback",)))
        self.session.flush = AsyncMock(side_effect=self._flush)
        self.session.scalar = AsyncMock(side_effect=self._scalar)
        self.tmdb = AsyncMock()
        self.tmdb.search = AsyncMock(side_effect=self._search)
        self.tmdb.get_details = AsyncMock(side_effect=self._get_details)
        self.tmdb.get_external_ids = AsyncMock(side_effect=self._external_ids)
        self.tmdb.get_episode_groups = AsyncMock(side_effect=self._groups)

    async def _flush(self) -> None:
        self.log.append(("flush",))
        if self.flush_error:
            raise self.flush_error

    async def _scalar(self, *_a: object, **_k: object) -> int:
        self.log.append(("count_episodes",))
        return self.ep_count

    async def _search(self, query: str, media_type: str = "tv") -> Any:
        self.log.append(("tmdb.search", query, media_type))
        if self.search_error:
            raise self.search_error
        return self.search_result

    async def _get_details(self, tmdb_id: int, media_type: str = "tv") -> Any:
        self.log.append(("tmdb.get_details", tmdb_id, media_type))
        if self.details_error:
            raise self.details_error
        return {"name": "Frieren", "id": tmdb_id}

    async def _external_ids(self, *a: object, **_k: object) -> Any:
        self.log.append(("tmdb.get_external_ids", *a))
        return {}

    async def _groups(self, *a: object, **_k: object) -> Any:
        self.log.append(("tmdb.get_episode_groups", *a))
        return {"results": []}

    async def on_event(self, level: str, msg: str, ctx: object = None) -> None:
        self.log.append(("event", level, msg, ctx))
        if self.raise_in_event and self.raise_in_event in msg:
            raise RuntimeError("sink down")

    async def on_progress(self, cur: int, total: int, msg: str) -> None:
        self.log.append(("progress", cur, total, msg))
        if self.match_plan.get("cancel_at") == cur:
            raise RuntimeError("cancelled")

    def _fake_tmdb_orchestrator(self) -> Any:
        harness = self

        class _Fake:
            def __init__(self, session: object, tmdb: object) -> None:
                pass

            async def sync_show_episodes(self, show: Any) -> None:
                harness.log.append(("sync_show_episodes", show.title))
                if harness.sync_error:
                    raise harness.sync_error

            async def ensure_episode_group_map(self, show: Any) -> None:
                harness.log.append(("ensure_episode_group_map", show.title))

        return _Fake

    async def _match(
        self,
        session: object,
        llm: object,
        show_id: int | None,
        show_title: str,
        entry: Any,
        episode_group_map: object = None,
        on_event: object = None,
    ) -> Any:
        name = _orc11_base(entry.raw_path)
        self.log.append(("match", show_id, show_title, name, episode_group_map))
        plan = self.match_plan[name]
        if isinstance(plan, Exception):
            raise plan
        return plan

    async def _synthetic(
        self, session: object, show_id: int, ep_id: int, path: str, **kw: Any
    ) -> None:
        self.log.append(("synthetic", show_id, ep_id, _orc11_base(path), kw))
        if "synthetic" in self.match_plan:
            raise self.match_plan["synthetic"]

    def patches(self) -> Any:
        from contextlib import ExitStack

        stack = ExitStack()
        mod = "jidou.orchestrators.path_import_orchestrator"
        fake = self._fake_tmdb_orchestrator()
        stack.enter_context(patch(f"{mod}.TMDBOrchestrator", fake))
        stack.enter_context(patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator", fake))
        stack.enter_context(patch(f"{mod}.match_entry_to_episode", self._match))
        stack.enter_context(patch(f"{mod}.create_synthetic_import_file", self._synthetic))

        async def gen_aliases(show: Any, tmdb: object, llm: object = None) -> None:
            self.log.append(("generate_aliases", show.title))

        stack.enter_context(
            patch("jidou.orchestrators._show_provisioning.generate_aliases", gen_aliases)
        )
        return stack

    def orchestrator(self, **kw: Any) -> Any:
        from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

        return PathImportOrchestrator(self.session, self.tmdb, on_event=self.on_event, **kw)


def _orc11_show(*, local_path: str | None = None, id: int | None = 1) -> MagicMock:
    show = _make_show(id=id, tmdb_id=77, title="Frieren")  # type: ignore[arg-type]
    show.local_path = local_path
    show.episode_group_map = None
    return show


def _orc11_ep(id: int, season: int, episode: int, tracked: bool = False) -> MagicMock:
    ep = _make_episode(id=id, show_id=1, season=season, episode=episode)
    ep.file_tracked = tracked
    return ep


def _orc11_summary(result: Any) -> Any:
    return (
        result.shows_processed,
        result.shows_created,
        result.shows_found,
        result.shows_not_found,
        result.episodes_tracked,
        result.episodes_unmatched,
        result.episodes_already_tracked,
        result.mode,
        [
            (
                r.show_dir,
                r.tmdb_id,
                r.tmdb_title,
                r.action,
                r.episodes_tracked,
                r.episodes_unmatched,
                r.episodes_already_tracked,
                [_orc11_base(p) for p in r.unmatched_paths],
                [_orc11_base(p) for p in r.already_tracked_paths],
            )
            for r in result.show_results
        ],
    )


_ORC11_MIXED_NAMES = ("a.mkv", "b.mkv", "c.mkv", "d.mkv", "e.mkv")


def _orc11_mixed_plan(h: _Orc11Harness) -> tuple[MagicMock, MagicMock]:
    """Plan: new, unmatched, duplicate of new, previously tracked, unmatched without numbers."""
    ep1 = _orc11_ep(1, 1, 1)
    ep3 = _orc11_ep(3, 1, 3, tracked=True)
    h.match_plan = {
        "a.mkv": (ep1, 1, 1),
        "b.mkv": (None, 1, 2),
        "c.mkv": (ep1, 1, 1),
        "d.mkv": (ep3, 1, 3),
        "e.mkv": (None, None, None),
    }
    return ep1, ep3


async def _orc11_run(
    h: _Orc11Harness,
    *,
    show: Any = None,
    entries: list[Any] | None = None,
    progress: bool = True,
    **orch_kw: Any,
) -> tuple[Any, Any]:
    """Run ``orch.run``; return ``(summary-or-exception-repr, log)``."""
    orch = h.orchestrator(**orch_kw)
    entries = entries or [_orc11_entry(n) for n in _ORC11_MIXED_NAMES]
    outcome: Any
    with h.patches(), patch.object(orch, "_db_find_show", AsyncMock(return_value=show)):
        try:
            result = await orch.run(entries, on_progress=h.on_progress if progress else None)
            outcome = _orc11_summary(result)
        except Exception as exc:
            outcome = _orc11_raised(exc)
    return outcome, h.log


async def _orc11_success() -> Any:
    h = _Orc11Harness()
    show = _orc11_show()
    ep1, ep3 = _orc11_mixed_plan(h)
    out = await _orc11_run(h, show=show)
    return (
        *out,
        ep1.file_tracked,
        ep1.tracked_filename and _orc11_base(ep1.tracked_filename),
        ep3.file_tracked,
        show.local_path is not None,
    )


async def _orc11_dry_run_existing() -> Any:
    h = _Orc11Harness()
    show = _orc11_show()
    ep1, ep3 = _orc11_mixed_plan(h)
    ep3.file_tracked = False
    out = await _orc11_run(h, show=show, dry_run=True)
    return (*out, ep1.file_tracked, ep3.file_tracked, show.local_path)


async def _orc11_dry_run_new_show() -> Any:
    """Dry-run create: no id, so counts are estimated from the parsed entries."""
    h = _Orc11Harness()
    entries = [
        _orc11_entry("a.mkv"),
        _orc11_entry("b.mkv", None, None),
        _orc11_entry("c.mkv", 1, 3),
    ]
    return await _orc11_run(h, show=None, entries=entries, dry_run=True)


async def _orc11_create_full() -> Any:
    """Non-dry-run create: insert, commit, sync, aliases, then match, then commit."""
    h = _Orc11Harness()
    h.match_plan = {"a.mkv": (_orc11_ep(1, 1, 1), 1, 1)}
    return await _orc11_run(h, show=None, entries=[_orc11_entry("a.mkv")])


async def _orc11_create_sync_fails() -> Any:
    h = _Orc11Harness()
    h.sync_error = RuntimeError("tmdb down")
    h.match_plan = {"a.mkv": (None, 1, 1)}
    return await _orc11_run(h, show=None, entries=[_orc11_entry("a.mkv")])


async def _orc11_tmdb_search_fails() -> Any:
    h = _Orc11Harness()
    h.search_error = RuntimeError("search 500")
    return await _orc11_run(h, show=None)


async def _orc11_tmdb_details_fail() -> Any:
    h = _Orc11Harness()
    h.details_error = RuntimeError("details 500")
    return await _orc11_run(h, show=None)


async def _orc11_tmdb_no_results() -> Any:
    h = _Orc11Harness()
    h.search_result = {"results": [{"id": 1, "name": "x", "media_type": "person"}]}
    return await _orc11_run(h, show=None)


async def _orc11_tmdb_fallback_no_exact() -> Any:
    h = _Orc11Harness()
    h.search_result = {
        "results": [
            {"id": 5, "name": "Other One", "media_type": "tv"},
            {"id": 6, "name": "Other Two"},
        ]
    }
    h.match_plan = {"a.mkv": (None, 1, 1)}
    return await _orc11_run(h, show=None, entries=[_orc11_entry("a.mkv")])


async def _orc11_create_insert_race_loses() -> Any:
    """Flush raises IntegrityError: rollback, refind the winner, adopt it."""
    from sqlalchemy.exc import IntegrityError

    h = _Orc11Harness()
    h.flush_error = IntegrityError("stmt", {}, Exception("dup"))
    winner = _orc11_show()
    h.match_plan = {"a.mkv": (None, 1, 1)}
    orch = h.orchestrator()
    outcome: Any
    # The directory-name lookup misses; the post-rollback tmdb_id refind finds the winner.
    with (
        h.patches(),
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch(
            "jidou.orchestrators.path_import_orchestrator.find_show_by_tmdb_id",
            AsyncMock(return_value=winner),
        ),
    ):
        try:
            outcome = _orc11_summary(await orch.run([_orc11_entry("a.mkv")]))
        except Exception as exc:
            outcome = _orc11_raised(exc)
    return outcome, h.log


async def _orc11_mid_show_db_error() -> Any:
    from sqlalchemy.exc import OperationalError

    h = _Orc11Harness()
    ep1, _ = _orc11_mixed_plan(h)
    h.match_plan["b.mkv"] = OperationalError("stmt", {}, Exception("conn lost"))
    out = await _orc11_run(h, show=_orc11_show())
    return (*out, ep1.file_tracked)


async def _orc11_synthetic_file_error() -> Any:
    h = _Orc11Harness()
    _orc11_mixed_plan(h)
    h.match_plan["synthetic"] = RuntimeError("insert failed")
    return await _orc11_run(h, show=_orc11_show())


async def _orc11_sync_if_needed_fails() -> Any:
    """Found show with zero episodes whose sync fails: rollback, error event, import continues."""
    h = _Orc11Harness(ep_count=0)
    h.sync_error = RuntimeError("sync boom")
    _orc11_mixed_plan(h)
    return await _orc11_run(h, show=_orc11_show())


async def _orc11_sync_if_needed_ok_dry_run() -> Any:
    h = _Orc11Harness(ep_count=0)
    _orc11_mixed_plan(h)
    return await _orc11_run(h, show=_orc11_show(), dry_run=True)


async def _orc11_event_raises_on_no_match() -> Any:
    h = _Orc11Harness(raise_in_event="No match")
    _orc11_mixed_plan(h)
    return await _orc11_run(h, show=_orc11_show())


async def _orc11_event_raises_on_duplicate() -> Any:
    h = _Orc11Harness(raise_in_event="resolved to the same episode")
    _orc11_mixed_plan(h)
    return await _orc11_run(h, show=_orc11_show())


async def _orc11_event_raises_on_summary() -> Any:
    h = _Orc11Harness(raise_in_event="file(s) for 'Frieren'")
    _orc11_mixed_plan(h)
    return await _orc11_run(h, show=_orc11_show())


async def _orc11_event_raises_on_clean_summary() -> Any:
    h = _Orc11Harness(raise_in_event="Tracked 1 episode(s)")
    h.match_plan = {"a.mkv": (_orc11_ep(1, 1, 1), 1, 1)}
    return await _orc11_run(h, show=_orc11_show(), entries=[_orc11_entry("a.mkv")])


async def _orc11_cancelled_on_second_show() -> Any:
    h = _Orc11Harness()
    h.match_plan = {"a.mkv": (_orc11_ep(1, 1, 1), 1, 1), "cancel_at": 2}
    first = _orc11_entry("a.mkv")
    second = _orc11_entry("a.mkv")
    second.show_dir = "Other"
    return await _orc11_run(h, show=_orc11_show(), entries=[first, second])


async def _orc11_shows_only() -> Any:
    h = _Orc11Harness()
    return await _orc11_run(h, show=_orc11_show(), mode="shows_only")


async def _orc11_shows_only_dry_run() -> Any:
    h = _Orc11Harness()
    return await _orc11_run(h, show=_orc11_show(), mode="shows_only", dry_run=True)


async def _orc11_episodes_only_missing_show() -> Any:
    h = _Orc11Harness()
    return await _orc11_run(h, show=None, mode="episodes_only")


async def _orc11_local_path_already_set() -> Any:
    h = _Orc11Harness()
    h.match_plan = {"a.mkv": (_orc11_ep(1, 1, 1), 1, 1)}
    show = _orc11_show(local_path="/already")
    out = await _orc11_run(h, show=show, entries=[_orc11_entry("a.mkv")])
    return (*out, show.local_path)


async def _orc11_split_off_secondary_show() -> Any:
    """A file whose own name disagrees is resolved as a second show with no auto local_path."""
    from jidou.services.filename_parser import FilenameParseResult

    h = _Orc11Harness()
    primary = _orc11_show()
    other = _make_show(id=2, tmdb_id=88, title="Other Show")
    other.local_path = None
    other.episode_group_map = None
    ep1 = _orc11_ep(1, 1, 1)
    h.match_plan = {"a.mkv": (ep1, 1, 1), "b.mkv": (ep1, 1, 1)}

    async def parse(filename: str, llm: object = None) -> Any:
        name = "Frieren" if filename == "a.mkv" else "Other Show"
        return FilenameParseResult(
            show_name=name,
            season=1,
            episode=1,
            crc32=None,
            content_type="anime",
            confidence=0.9,
            llm_ok=True,
        )

    orch = h.orchestrator()
    finder = AsyncMock(side_effect=[primary, other])
    entries = [_orc11_entry("a.mkv"), _orc11_entry("b.mkv")]
    outcome: Any
    with (
        h.patches(),
        patch.object(orch, "_db_find_show", finder),
        patch("jidou.orchestrators.path_import_orchestrator.parse_filename", parse),
    ):
        try:
            outcome = _orc11_summary(await orch.run(entries))
        except Exception as exc:
            outcome = _orc11_raised(exc)
    return outcome, h.log


ORC11_SCENARIOS: dict[str, Any] = {
    "success": _orc11_success,
    "dry_run_existing": _orc11_dry_run_existing,
    "dry_run_new_show": _orc11_dry_run_new_show,
    "create_full": _orc11_create_full,
    "create_sync_fails": _orc11_create_sync_fails,
    "tmdb_search_fails": _orc11_tmdb_search_fails,
    "tmdb_details_fail": _orc11_tmdb_details_fail,
    "tmdb_no_results": _orc11_tmdb_no_results,
    "tmdb_fallback_no_exact": _orc11_tmdb_fallback_no_exact,
    "create_insert_race_loses": _orc11_create_insert_race_loses,
    "mid_show_db_error": _orc11_mid_show_db_error,
    "synthetic_file_error": _orc11_synthetic_file_error,
    "sync_if_needed_fails": _orc11_sync_if_needed_fails,
    "sync_if_needed_ok_dry_run": _orc11_sync_if_needed_ok_dry_run,
    "event_raises_on_no_match": _orc11_event_raises_on_no_match,
    "event_raises_on_duplicate": _orc11_event_raises_on_duplicate,
    "event_raises_on_summary": _orc11_event_raises_on_summary,
    "event_raises_on_clean_summary": _orc11_event_raises_on_clean_summary,
    "cancelled_on_second_show": _orc11_cancelled_on_second_show,
    "shows_only": _orc11_shows_only,
    "shows_only_dry_run": _orc11_shows_only_dry_run,
    "episodes_only_missing_show": _orc11_episodes_only_missing_show,
    "local_path_already_set": _orc11_local_path_already_set,
    "split_off_secondary_show": _orc11_split_off_secondary_show,
}

ORC11_GOLDEN: dict[str, str] = {
    "cancelled_on_second_show": r"""
(('raised', 'RuntimeError', 'cancelled'),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 2, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('event', 'info', "Tracked 1 episode(s) for 'Frieren'", None),
  ('commit',),
  ('progress', 2, 2, 'Importing Other')])""",
    "create_full": r"""
((1, 1, 0, 0, 1, 0, 0, 'full', [('Frieren', 77, 'Frieren', 'created', 1, 0, 0, [], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Not in DB — searching TMDB for 'Frieren'", None),
  ('event', 'info', "Calling TMDB search for 'Frieren'", None),
  ('tmdb.search', 'Frieren', 'tv'),
  ('event',
   'info',
   "TMDB matched 'Frieren' (id=77)",
   {'candidates': 1, 'match': 'exact', 'tmdb_id': 77}),
  ('tmdb.get_details', 77, 'tv'),
  ('tmdb.get_external_ids', 77),
  ('tmdb.get_episode_groups', 77),
  ('add', 'Show'),
  ('flush',),
  ('commit',),
  ('event',
   'info',
   "Created show 'Frieren' (id=None, tmdb_id=77)",
   {'show_id': None, 'tmdb_id': 77}),
  ('event', 'info', "Syncing episodes for 'Frieren' from TMDB", None),
  ('sync_show_episodes', 'Frieren'),
  ('count_episodes',),
  ('event', 'info', "Synced 5 episodes for 'Frieren'", None),
  ('generate_aliases', 'Frieren'),
  ('flush',),
  ('event', 'info', "Generated aliases for 'Frieren'", None),
  ('match', None, 'Frieren', 'a.mkv', None),
  ('synthetic', None, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('event', 'info', "Tracked 1 episode(s) for 'Frieren'", None),
  ('commit',)])""",
    "create_insert_race_loses": r"""
((1, 0, 1, 0, 0, 1, 0, 'full', [('Frieren', 77, 'Frieren', 'found', 0, 1, 0, ['a.mkv'], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('event', 'info', "Not in DB — searching TMDB for 'Frieren'", None),
  ('event', 'info', "Calling TMDB search for 'Frieren'", None),
  ('tmdb.search', 'Frieren', 'tv'),
  ('event',
   'info',
   "TMDB matched 'Frieren' (id=77)",
   {'candidates': 1, 'match': 'exact', 'tmdb_id': 77}),
  ('tmdb.get_details', 77, 'tv'),
  ('tmdb.get_external_ids', 77),
  ('tmdb.get_episode_groups', 77),
  ('add', 'Show'),
  ('flush',),
  ('rollback',),
  ('event', 'info', "Show 'Frieren' already existed (concurrent create)", None),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('event',
   'warn',
   'No match: a.mkv (S01E01)',
   {'episode': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\a.mkv', 'season': 1}),
  ('event',
   'warn',
   "1 unmatched file(s) for 'Frieren'",
   {'episodes_already_tracked': 0, 'episodes_tracked': 0, 'episodes_unmatched': 1}),
  ('commit',)])""",
    "create_sync_fails": r"""
((1, 1, 0, 0, 0, 1, 0, 'full', [('Frieren', 77, 'Frieren', 'created', 0, 1, 0, ['a.mkv'], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Not in DB — searching TMDB for 'Frieren'", None),
  ('event', 'info', "Calling TMDB search for 'Frieren'", None),
  ('tmdb.search', 'Frieren', 'tv'),
  ('event',
   'info',
   "TMDB matched 'Frieren' (id=77)",
   {'candidates': 1, 'match': 'exact', 'tmdb_id': 77}),
  ('tmdb.get_details', 77, 'tv'),
  ('tmdb.get_external_ids', 77),
  ('tmdb.get_episode_groups', 77),
  ('add', 'Show'),
  ('flush',),
  ('commit',),
  ('event',
   'info',
   "Created show 'Frieren' (id=None, tmdb_id=77)",
   {'show_id': None, 'tmdb_id': 77}),
  ('event', 'info', "Syncing episodes for 'Frieren' from TMDB", None),
  ('sync_show_episodes', 'Frieren'),
  ('rollback',),
  ('event', 'error', "Episode sync failed for 'Frieren': tmdb down", None),
  ('generate_aliases', 'Frieren'),
  ('flush',),
  ('event', 'info', "Generated aliases for 'Frieren'", None),
  ('match', None, 'Frieren', 'a.mkv', None),
  ('event',
   'warn',
   'No match: a.mkv (S01E01)',
   {'episode': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\a.mkv', 'season': 1}),
  ('event',
   'warn',
   "1 unmatched file(s) for 'Frieren'",
   {'episodes_already_tracked': 0, 'episodes_tracked': 0, 'episodes_unmatched': 1}),
  ('commit',)])""",
    "dry_run_existing": r"""
((1,
  0,
  1,
  0,
  2,
  2,
  1,
  'full',
  [('Frieren', 77, 'Frieren', 'found', 2, 2, 1, ['b.mkv', 'e.mkv'], ['c.mkv'])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('match', 1, 'Frieren', 'b.mkv', None),
  ('event',
   'warn',
   'No match: b.mkv (S01E02)',
   {'episode': 2, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\b.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'c.mkv', None),
  ('event',
   'warn',
   "'c.mkv' resolved to the same episode (S01E01) as another file in this import — check for a "
   'season/episode numbering mismatch',
   {'episode': 1, 'episode_id': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\c.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'd.mkv', None),
  ('match', 1, 'Frieren', 'e.mkv', None),
  ('event',
   'warn',
   'No match: e.mkv (S?E?)',
   {'episode': None, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\e.mkv', 'season': None}),
  ('event',
   'warn',
   "2 unmatched, 1 resolved to a duplicate episode file(s) for 'Frieren'",
   {'episodes_already_tracked': 1, 'episodes_tracked': 2, 'episodes_unmatched': 2})],
 False,
 False,
 None)""",
    "dry_run_new_show": r"""
((1, 1, 0, 0, 2, 1, 0, 'full', [('Frieren', 77, 'Frieren', 'created', 2, 1, 0, ['b.mkv'], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Not in DB — searching TMDB for 'Frieren'", None),
  ('event', 'info', "Calling TMDB search for 'Frieren'", None),
  ('tmdb.search', 'Frieren', 'tv'),
  ('event',
   'info',
   "TMDB matched 'Frieren' (id=77)",
   {'candidates': 1, 'match': 'exact', 'tmdb_id': 77}),
  ('tmdb.get_details', 77, 'tv'),
  ('tmdb.get_external_ids', 77),
  ('tmdb.get_episode_groups', 77),
  ('event', 'info', "[dry-run] Would create show 'Frieren' (tmdb_id=77)", None)])""",
    "episodes_only_missing_show": r"""
((1,
  0,
  0,
  1,
  0,
  5,
  0,
  'episodes_only',
  [('Frieren',
    None,
    None,
    'not_found',
    0,
    5,
    0,
    ['a.mkv', 'b.mkv', 'c.mkv', 'd.mkv', 'e.mkv'],
    [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('event',
   'info',
   'Running in episodes-only mode — no new shows will be created; files under a show not already '
   'in the database will be reported unmatched',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Not in DB — skipping (episodes-only mode): 'Frieren'", None),
  ('event',
   'warn',
   "Show 'Frieren' not found in database (episodes-only mode) — 5 file(s) unmatched",
   None)])""",
    "event_raises_on_clean_summary": r"""
((1, 0, 1, 0, 1, 0, 0, 'full', [('Frieren', 77, 'Frieren', 'found', 1, 0, 0, [], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('event', 'info', "Tracked 1 episode(s) for 'Frieren'", None),
  ('commit',)])""",
    "event_raises_on_duplicate": r"""
((1,
  0,
  1,
  0,
  1,
  2,
  1,
  'full',
  [('Frieren', 77, 'Frieren', 'found', 1, 2, 1, ['b.mkv', 'e.mkv'], ['c.mkv'])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('match', 1, 'Frieren', 'b.mkv', None),
  ('event',
   'warn',
   'No match: b.mkv (S01E02)',
   {'episode': 2, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\b.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'c.mkv', None),
  ('event',
   'warn',
   "'c.mkv' resolved to the same episode (S01E01) as another file in this import — check for a "
   'season/episode numbering mismatch',
   {'episode': 1, 'episode_id': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\c.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'd.mkv', None),
  ('match', 1, 'Frieren', 'e.mkv', None),
  ('event',
   'warn',
   'No match: e.mkv (S?E?)',
   {'episode': None, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\e.mkv', 'season': None}),
  ('event',
   'warn',
   "2 unmatched, 1 resolved to a duplicate episode file(s) for 'Frieren'",
   {'episodes_already_tracked': 1, 'episodes_tracked': 1, 'episodes_unmatched': 2}),
  ('commit',)])""",
    "event_raises_on_no_match": r"""
((1,
  0,
  1,
  0,
  1,
  2,
  1,
  'full',
  [('Frieren', 77, 'Frieren', 'found', 1, 2, 1, ['b.mkv', 'e.mkv'], ['c.mkv'])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('match', 1, 'Frieren', 'b.mkv', None),
  ('event',
   'warn',
   'No match: b.mkv (S01E02)',
   {'episode': 2, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\b.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'c.mkv', None),
  ('event',
   'warn',
   "'c.mkv' resolved to the same episode (S01E01) as another file in this import — check for a "
   'season/episode numbering mismatch',
   {'episode': 1, 'episode_id': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\c.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'd.mkv', None),
  ('match', 1, 'Frieren', 'e.mkv', None),
  ('event',
   'warn',
   'No match: e.mkv (S?E?)',
   {'episode': None, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\e.mkv', 'season': None}),
  ('event',
   'warn',
   "2 unmatched, 1 resolved to a duplicate episode file(s) for 'Frieren'",
   {'episodes_already_tracked': 1, 'episodes_tracked': 1, 'episodes_unmatched': 2}),
  ('commit',)])""",
    "event_raises_on_summary": r"""
((1,
  0,
  1,
  0,
  1,
  2,
  1,
  'full',
  [('Frieren', 77, 'Frieren', 'found', 1, 2, 1, ['b.mkv', 'e.mkv'], ['c.mkv'])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('match', 1, 'Frieren', 'b.mkv', None),
  ('event',
   'warn',
   'No match: b.mkv (S01E02)',
   {'episode': 2, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\b.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'c.mkv', None),
  ('event',
   'warn',
   "'c.mkv' resolved to the same episode (S01E01) as another file in this import — check for a "
   'season/episode numbering mismatch',
   {'episode': 1, 'episode_id': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\c.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'd.mkv', None),
  ('match', 1, 'Frieren', 'e.mkv', None),
  ('event',
   'warn',
   'No match: e.mkv (S?E?)',
   {'episode': None, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\e.mkv', 'season': None}),
  ('event',
   'warn',
   "2 unmatched, 1 resolved to a duplicate episode file(s) for 'Frieren'",
   {'episodes_already_tracked': 1, 'episodes_tracked': 1, 'episodes_unmatched': 2}),
  ('commit',)])""",
    "local_path_already_set": r"""
((1, 0, 1, 0, 1, 0, 0, 'full', [('Frieren', 77, 'Frieren', 'found', 1, 0, 0, [], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('event', 'info', "Tracked 1 episode(s) for 'Frieren'", None),
  ('commit',)],
 '/already')""",
    "mid_show_db_error": r"""
(('raised', 'OperationalError', 'conn lost'),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('match', 1, 'Frieren', 'b.mkv', None)],
 True)""",
    "shows_only": r"""
((1, 0, 1, 0, 0, 0, 0, 'shows_only', [('Frieren', 77, 'Frieren', 'found', 0, 0, 0, [], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('event',
   'info',
   'Running in shows-only mode — episode matching will be skipped for all shows',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('event',
   'info',
   "Show ready: 'Frieren' (found) — episode matching skipped (shows-only mode)",
   None),
  ('commit',)])""",
    "shows_only_dry_run": r"""
((1, 0, 1, 0, 0, 0, 0, 'shows_only', [('Frieren', 77, 'Frieren', 'found', 0, 0, 0, [], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('event',
   'info',
   'Running in shows-only mode — episode matching will be skipped for all shows',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('event',
   'info',
   "Show ready: 'Frieren' (found) — episode matching skipped (shows-only mode)",
   None)])""",
    "split_off_secondary_show": r"""
((1,
  0,
  2,
  0,
  1,
  0,
  1,
  'full',
  [('Frieren', 77, 'Frieren', 'found', 1, 0, 0, [], []),
   ('Other Show', 88, 'Other Show', 'found', 0, 0, 1, [], ['b.mkv'])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('event', 'info', "Tracked 1 episode(s) for 'Frieren'", None),
  ('commit',),
  ('event',
   'warn',
   "1 file(s) under 'Frieren' appear to belong to 'Other Show' instead — resolving separately",
   {'count': 1, 'directory': 'Frieren', 'extracted_name': 'Other Show'}),
  ('event', 'info', "Found in DB: 'Other Show'", {'show_id': 2, 'tmdb_id': 88}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Other Show'),
  ('event',
   'warn',
   "'Other Show' was split off from a mismatched directory — local_path was not auto-set; "
   'configure it manually via PATCH /shows/2',
   {'show_id': 2}),
  ('match', 2, 'Other Show', 'b.mkv', None),
  ('event',
   'warn',
   "'b.mkv' resolved to the same episode (S01E01) as another file in this import — check for a "
   'season/episode numbering mismatch',
   {'episode': 1, 'episode_id': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\b.mkv', 'season': 1}),
  ('event',
   'warn',
   "1 resolved to a duplicate episode file(s) for 'Other Show'",
   {'episodes_already_tracked': 1, 'episodes_tracked': 0, 'episodes_unmatched': 0}),
  ('commit',)])""",
    "success": r"""
((1,
  0,
  1,
  0,
  1,
  2,
  1,
  'full',
  [('Frieren', 77, 'Frieren', 'found', 1, 2, 1, ['b.mkv', 'e.mkv'], ['c.mkv'])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('match', 1, 'Frieren', 'b.mkv', None),
  ('event',
   'warn',
   'No match: b.mkv (S01E02)',
   {'episode': 2, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\b.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'c.mkv', None),
  ('event',
   'warn',
   "'c.mkv' resolved to the same episode (S01E01) as another file in this import — check for a "
   'season/episode numbering mismatch',
   {'episode': 1, 'episode_id': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\c.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'd.mkv', None),
  ('match', 1, 'Frieren', 'e.mkv', None),
  ('event',
   'warn',
   'No match: e.mkv (S?E?)',
   {'episode': None, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\e.mkv', 'season': None}),
  ('event',
   'warn',
   "2 unmatched, 1 resolved to a duplicate episode file(s) for 'Frieren'",
   {'episodes_already_tracked': 1, 'episodes_tracked': 1, 'episodes_unmatched': 2}),
  ('commit',)],
 True,
 'a.mkv',
 True,
 True)""",
    "sync_if_needed_fails": r"""
((1,
  0,
  1,
  0,
  1,
  2,
  1,
  'full',
  [('Frieren', 77, 'Frieren', 'found', 1, 2, 1, ['b.mkv', 'e.mkv'], ['c.mkv'])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('event', 'info', "No episodes synced yet — fetching from TMDB for 'Frieren'", None),
  ('sync_show_episodes', 'Frieren'),
  ('rollback',),
  ('event', 'error', "Episode sync failed for 'Frieren': sync boom", None),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1}),
  ('match', 1, 'Frieren', 'b.mkv', None),
  ('event',
   'warn',
   'No match: b.mkv (S01E02)',
   {'episode': 2, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\b.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'c.mkv', None),
  ('event',
   'warn',
   "'c.mkv' resolved to the same episode (S01E01) as another file in this import — check for a "
   'season/episode numbering mismatch',
   {'episode': 1, 'episode_id': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\c.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'd.mkv', None),
  ('match', 1, 'Frieren', 'e.mkv', None),
  ('event',
   'warn',
   'No match: e.mkv (S?E?)',
   {'episode': None, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\e.mkv', 'season': None}),
  ('event',
   'warn',
   "2 unmatched, 1 resolved to a duplicate episode file(s) for 'Frieren'",
   {'episodes_already_tracked': 1, 'episodes_tracked': 1, 'episodes_unmatched': 2}),
  ('commit',)])""",
    "sync_if_needed_ok_dry_run": r"""
((1,
  0,
  1,
  0,
  1,
  2,
  1,
  'full',
  [('Frieren', 77, 'Frieren', 'found', 1, 2, 1, ['b.mkv', 'e.mkv'], ['c.mkv'])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('match', 1, 'Frieren', 'b.mkv', None),
  ('event',
   'warn',
   'No match: b.mkv (S01E02)',
   {'episode': 2, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\b.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'c.mkv', None),
  ('event',
   'warn',
   "'c.mkv' resolved to the same episode (S01E01) as another file in this import — check for a "
   'season/episode numbering mismatch',
   {'episode': 1, 'episode_id': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\c.mkv', 'season': 1}),
  ('match', 1, 'Frieren', 'd.mkv', None),
  ('match', 1, 'Frieren', 'e.mkv', None),
  ('event',
   'warn',
   'No match: e.mkv (S?E?)',
   {'episode': None, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\e.mkv', 'season': None}),
  ('event',
   'warn',
   "2 unmatched, 1 resolved to a duplicate episode file(s) for 'Frieren'",
   {'episodes_already_tracked': 1, 'episodes_tracked': 1, 'episodes_unmatched': 2})])""",
    "synthetic_file_error": r"""
(('raised', 'RuntimeError', 'insert failed'),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Found in DB: 'Frieren'", {'show_id': 1, 'tmdb_id': 77}),
  ('count_episodes',),
  ('ensure_episode_group_map', 'Frieren'),
  ('match', 1, 'Frieren', 'a.mkv', None),
  ('synthetic', 1, 1, 'a.mkv', {'parsed_episode': 1, 'parsed_season': 1})])""",
    "tmdb_details_fail": r"""
((1,
  0,
  0,
  1,
  0,
  5,
  0,
  'full',
  [('Frieren',
    None,
    None,
    'not_found',
    0,
    5,
    0,
    ['a.mkv', 'b.mkv', 'c.mkv', 'd.mkv', 'e.mkv'],
    [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Not in DB — searching TMDB for 'Frieren'", None),
  ('event', 'info', "Calling TMDB search for 'Frieren'", None),
  ('tmdb.search', 'Frieren', 'tv'),
  ('event',
   'info',
   "TMDB matched 'Frieren' (id=77)",
   {'candidates': 1, 'match': 'exact', 'tmdb_id': 77}),
  ('tmdb.get_details', 77, 'tv'),
  ('event', 'error', 'TMDB get_details failed for id=77: details 500', None),
  ('event', 'warn', "No TMDB match found for 'Frieren' — 5 file(s) unmatched", None)])""",
    "tmdb_fallback_no_exact": r"""
((1, 1, 0, 0, 0, 1, 0, 'full', [('Frieren', 5, 'Frieren', 'created', 0, 1, 0, ['a.mkv'], [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Not in DB — searching TMDB for 'Frieren'", None),
  ('event', 'info', "Calling TMDB search for 'Frieren'", None),
  ('tmdb.search', 'Frieren', 'tv'),
  ('event',
   'warn',
   "No exact TMDB match for 'Frieren' in 2 result(s) — falling back to top result 'Other One' "
   '(id=5)',
   {'candidates': 2,
    'match': 'fallback',
    'tmdb_id': 5,
    'top_candidates': ['Other One', 'Other Two']}),
  ('tmdb.get_details', 5, 'tv'),
  ('tmdb.get_external_ids', 5),
  ('tmdb.get_episode_groups', 5),
  ('add', 'Show'),
  ('flush',),
  ('commit',),
  ('event', 'info', "Created show 'Frieren' (id=None, tmdb_id=5)", {'show_id': None, 'tmdb_id': 5}),
  ('event', 'info', "Syncing episodes for 'Frieren' from TMDB", None),
  ('sync_show_episodes', 'Frieren'),
  ('count_episodes',),
  ('event', 'info', "Synced 5 episodes for 'Frieren'", None),
  ('generate_aliases', 'Frieren'),
  ('flush',),
  ('event', 'info', "Generated aliases for 'Frieren'", None),
  ('match', None, 'Frieren', 'a.mkv', None),
  ('event',
   'warn',
   'No match: a.mkv (S01E01)',
   {'episode': 1, 'path': 'Z:\\anime tv\\Frieren\\Season 01\\a.mkv', 'season': 1}),
  ('event',
   'warn',
   "1 unmatched file(s) for 'Frieren'",
   {'episodes_already_tracked': 0, 'episodes_tracked': 0, 'episodes_unmatched': 1}),
  ('commit',)])""",
    "tmdb_no_results": r"""
((1,
  0,
  0,
  1,
  0,
  5,
  0,
  'full',
  [('Frieren',
    None,
    None,
    'not_found',
    0,
    5,
    0,
    ['a.mkv', 'b.mkv', 'c.mkv', 'd.mkv', 'e.mkv'],
    [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Not in DB — searching TMDB for 'Frieren'", None),
  ('event', 'info', "Calling TMDB search for 'Frieren'", None),
  ('tmdb.search', 'Frieren', 'tv'),
  ('event', 'warn', "TMDB returned no results for 'Frieren'", None),
  ('event', 'warn', "No TMDB match found for 'Frieren' — 5 file(s) unmatched", None)])""",
    "tmdb_search_fails": r"""
((1,
  0,
  0,
  1,
  0,
  5,
  0,
  'full',
  [('Frieren',
    None,
    None,
    'not_found',
    0,
    5,
    0,
    ['a.mkv', 'b.mkv', 'c.mkv', 'd.mkv', 'e.mkv'],
    [])]),
 [('event',
   'warn',
   "LLM not configured or unavailable — filenames that regex can't parse, and shows TMDB can't "
   'match exactly, will not get an LLM fallback attempt for this run',
   None),
  ('progress', 1, 1, 'Importing Frieren'),
  ('event', 'info', "Not in DB — searching TMDB for 'Frieren'", None),
  ('event', 'info', "Calling TMDB search for 'Frieren'", None),
  ('tmdb.search', 'Frieren', 'tv'),
  ('event', 'error', "TMDB search failed for 'Frieren': search 500", None),
  ('event', 'warn', "No TMDB match found for 'Frieren' — 5 file(s) unmatched", None)])""",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(ORC11_SCENARIOS))
async def test_orc11_path_import_sequence_is_unchanged(name: str) -> None:
    """Each scenario's complete ordered log matches the pre-refactor capture."""
    assert len(ORC11_SCENARIOS) >= 20
    assert set(ORC11_GOLDEN) == set(ORC11_SCENARIOS)
    actual = await ORC11_SCENARIOS[name]()
    assert "\n" + pprint.pformat(actual, width=100) == ORC11_GOLDEN[name]
    # Guard against a vacuous golden: every scenario records at least one step.
    assert ORC11_GOLDEN[name].count("\n") > 2


# ---------------------------------------------------------------------------
# _pick_tmdb_candidate (ORC-11)
# ---------------------------------------------------------------------------


def test_pick_tmdb_candidate_prefers_normalized_exact() -> None:
    """A normalized exact title match beats a higher-ranked partial match."""
    from jidou.orchestrators.path_import_orchestrator import _pick_tmdb_candidate

    candidates = [{"id": 1, "name": "Daredevil: Born Again"}, {"id": 2, "name": "Daredevil"}]

    best, exact = _pick_tmdb_candidate("Daredevil", candidates)

    assert best["name"] == "Daredevil"
    assert exact is True


def test_pick_tmdb_candidate_ignores_punctuation_when_matching() -> None:
    """Punctuation in the TMDB title does not defeat an otherwise exact match."""
    from jidou.orchestrators.path_import_orchestrator import _pick_tmdb_candidate

    candidates = [{"id": 1, "name": "Other"}, {"id": 2, "name": "Daredevil: Born Again"}]

    best, exact = _pick_tmdb_candidate("daredevil born again", candidates)

    assert (best["id"], exact) == (2, True)


def test_pick_tmdb_candidate_falls_back_to_first_when_nothing_matches() -> None:
    """With no exact match the first (top-relevance) candidate is returned, flagged inexact."""
    from jidou.orchestrators.path_import_orchestrator import _pick_tmdb_candidate

    candidates = [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}]

    best, exact = _pick_tmdb_candidate("Gamma", candidates)

    assert best is candidates[0]
    assert exact is False


def test_pick_tmdb_candidate_tolerates_missing_name() -> None:
    """A candidate without a name never matches and does not raise."""
    from jidou.orchestrators.path_import_orchestrator import _pick_tmdb_candidate

    candidates: list[dict[str, Any]] = [{"id": 1}, {"id": 2, "name": "Target"}]

    assert _pick_tmdb_candidate("Target", candidates) == (candidates[1], True)
