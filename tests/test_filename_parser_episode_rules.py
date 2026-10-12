"""Golden tables pinning the heuristic episode rules of ``filename_parser``.

Characterization test: rows were captured from the parser's behavior, including outputs that
look wrong (e.g. ``"Show Season 2 Episode 1001.mkv"`` names the show ``"Show Season 2 Episode"``).
Refactors must keep it green or update a row deliberately. ``_QUALITY_PATTERN_ROWS`` pins which
strings the quality/resolution strip removes, so the shared-token refactor (D21) can prove it
changed nothing.
"""

from datetime import date

import pytest

from jidou.services.filename_parser import (
    _QUALITY_PAT,
    _heuristic_parse,
    heuristic_se,
    parse_release_title,
)

# Year-relative rows are computed so the tables never go stale: the year exclusion's upper
# bound is "current year + 2" at runtime.
_Y = date.today().year

# DF-6 (D20): the roadmap's 4-digit-episode table, as (filename, (show_name, season, episode)).
DF6_TABLE: list[tuple[str, tuple[str | None, int | None, int | None]]] = [
    ("Show S01E1001.mkv", ("Show", 1, 1001)),
    ("Show 1x1000.mkv", ("Show 1x1000", None, None)),
    ("Show - 1071 [1080p].mkv", ("Show", None, 1071)),
    ("One Piece 1071.mkv", ("One Piece", None, 1071)),
    ("Show 2024.mkv", ("Show 2024", None, None)),
    ("Show 1080p.mkv", ("Show", None, None)),
    ("Episode 1100.mkv", ("Episode", None, 1100)),
]

# DF-6 broad sample, plus the path_parser golden stems run through this parser.
SAMPLE: list[tuple[str, tuple[str | None, int | None, int | None]]] = [
    ("Show - 5.mkv", ("Show", None, 5)),
    ("Show - 05.mkv", ("Show", None, 5)),
    ("Show - 123.mkv", ("Show", None, 123)),
    ("Show 7.mkv", ("Show", None, 7)),
    ("Show 42.mkv", ("Show", None, 42)),
    ("Show 999.mkv", ("Show", None, 999)),
    ("[Group] Show - 999 [ABCD1234].mkv", ("Show", None, 999)),
    ("[HorribleSubs] One Piece - 1001 [ABCD1234].mkv", ("One Piece", None, 1001)),
    ("Show S01E02.mkv", ("Show", 1, 2)),
    ("Show.S01E02.1080p.WEB-DL.mkv", ("Show", 1, 2)),
    ("Show S1E5.mkv", ("Show", 1, 5)),
    ("Show S10E100.mkv", ("Show", 10, 100)),
    ("Show S01E999.mkv", ("Show", 1, 999)),
    ("Show S01E2024.mkv", ("Show", 1, 2024)),
    ("Show S01E1080.mkv", ("Show", 1, 1080)),
    ("Show E05.mkv", ("Show", None, 5)),
    ("Show E1001.mkv", ("Show", None, 1001)),
    ("Show 1x05.mkv", ("Show 1x05", None, None)),
    ("Show.2x10.720p.mkv", ("Show 2x10", None, None)),
    ("Show 1x100.mkv", ("Show 1x100", None, None)),
    ("Show 12x999.mkv", ("Show 12x999", None, None)),
    ("Show 2x1080.mkv", ("Show 2x1080", None, None)),
    ("ShowName.1920x1080.mkv", ("ShowName 1920x1080", None, None)),
    ("Episode 5.mkv", ("Episode", None, 5)),
    ("Episode 123.mkv", ("Episode", None, 123)),
    ("Show Episode 2024.mkv", ("Show Episode 2024", None, None)),
    ("Show Season 2 Episode 1001.mkv", ("Show Season 2 Episode", None, 1001)),
    ("Show Ep 100.mkv", ("Show Ep", None, 100)),
    ("Show Ep 1000.mkv", ("Show Ep", None, 1000)),
    ("Show Ep.1234.mkv", ("Show Ep", None, 1234)),
    ("Show - 1000.mkv", ("Show", None, 1000)),
    ("Show - 2024.mkv", ("Show - 2024", None, None)),
    ("Show - 1080 [x].mkv", ("Show -", None, None)),
    # Owner ruling: dash markers skip years and resolutions. This parser's dash handling is the
    # guarded bare-number rule, and it has no "Ep N"/"Episode N" word rule (tracker titles aside).
    ("Show - 1071.mkv", ("Show", None, 1071)),
    ("Show - 1100.mkv", ("Show", None, 1100)),
    ("Show - 720 [x].mkv", ("Show -", None, None)),
    ("Show 1100 - Title.mkv", ("Show", None, 1100)),
    ("Show Ep 2024.mkv", ("Show Ep 2024", None, None)),
    ("Show 1x2024.mkv", ("Show 1x2024", None, None)),
    # Review fix I1: a 4-digit bare number loses to any later bare number (matches origin/main).
    ("The 4400 - 05 - Title.mkv", ("The 4400", None, 5)),
    ("Area 5150 01 Title.mkv", ("Area 5150", None, 1)),
    ("Show 1899 - 101 - Title.mkv", ("Show 1899", None, 101)),
    ("Show DD5.1x264.mkv", ("Show DD5 1x264", None, None)),
    ("Show AAC2.0x264 1080p.mkv", ("Show AAC2 0x264", None, None)),
    ("Show DDP5.1.x264.mkv", ("Show DDP5", None, 1)),
    ("1917 - 999.720p.WEB-DL.x264-GRP.mkv", ("1917", None, 999)),
    ("1917 - 01 1080.mkv", ("1917", None, 1)),
    ("2001 - A Space Odyssey.mkv", ("2001 - A Space Odyssey", None, None)),
    ("Show - 9999.mkv", ("Show", None, 9999)),
    ("Show Part 2 - 05.mkv", ("Show Part 2", None, 5)),
    ("Show 1001 - Big Title.mkv", ("Show", None, 1001)),
    ("Show 2024 - Title.mkv", ("Show 2024 - Title", None, None)),
    ("1001 - Big Special.mkv", ("1001 - Big Special", None, None)),
    ("2024 - Year in Review.mkv", ("2024 - Year in Review", None, None)),
    ("Show 1999.mkv", ("Show 1999", None, None)),
    (f"Show {_Y + 2}.mkv", (f"Show {_Y + 2}", None, None)),
    (f"Show {_Y + 3}.mkv", ("Show", None, _Y + 3)),
    ("Show 1899.mkv", ("Show", None, 1899)),
    ("Show 1900.mkv", ("Show 1900", None, None)),
    ("Show.Name.1999.DVDRip.mkv", ("Show Name 1999", None, None)),
    (f"Show.Name.{_Y + 2}.1080p.WEB-DL.mkv", (f"Show Name {_Y + 2}", None, None)),
    (f"Show.Name.{_Y + 3}.1080p.WEB-DL.mkv", ("Show Name", None, _Y + 3)),
    ("Show (2024) - 05.mkv", ("Show", None, 5)),
    ("Show 2024 05.mkv", ("Show 2024", None, 5)),
    ("Show 2024 1071 x.mkv", ("Show 2024", None, 1071)),
    ("Show 480p.mkv", ("Show", None, None)),
    ("Show 720p.mkv", ("Show", None, None)),
    ("Show 2160p.mkv", ("Show", None, None)),
    ("Show 4K.mkv", ("Show", None, None)),
    ("Show 480.mkv", ("Show", None, None)),
    ("Show 720.mkv", ("Show", None, None)),
    ("Show 2160.mkv", ("Show", None, None)),
    ("Show 4320.mkv", ("Show", None, None)),
    ("Show_720.mkv", ("Show 720", None, None)),
    ("Show_1080.mkv", ("Show 1080", None, None)),
    ("Show.1080i.mkv", ("Show", None, None)),
    ("Show 05 1080.mkv", ("Show", None, 5)),
    ("Show - 05 [x264].mkv", ("Show", None, 5)),
    ("Show.S01E02.HEVC.AAC.mkv", ("Show", 1, 2)),
    ("Show 05 HDTV x265.mkv", ("Show", None, 5)),
    ("Show.Name.BluRay.Remux.1080p.mkv", ("Show Name", None, None)),
    ("Show 05 WEB-DL.mkv", ("Show", None, 5)),
    ("Show 12 PROPER REPACK.mkv", ("Show", None, 12)),
    ("Show 1071 HDTV x265.mkv", ("Show", None, 1071)),
    ("Show - 05v2.mkv", ("Show", None, 5)),
    ("Show - 05v2 [1080p].mkv", ("Show", None, 5)),
    ("Show 1071v2.mkv", ("Show", None, 1071)),
    ("Show - 1071v2 [x].mkv", ("Show", None, 1071)),
    ("[Group] Show - 1071 [ABCD1234].mkv", ("Show", None, 1071)),
    ("Show 1071 [ABCD1234].mkv", ("Show", None, 1071)),
    ("Show S01 Complete.mkv", ("Show S01 Complete", None, None)),
    ("Show S01 1080p.mkv", ("Show S01", None, None)),
    ("Show S02 05.mkv", ("Show", 2, 5)),
    ("Show S01 2024.mkv", ("Show S01 2024", None, None)),
    ("Show S01 1001.mkv", ("Show", 1, 1001)),
    ("Show.S01.1001.mkv", ("Show", 1, 1001)),
    ("Show S01_720.mkv", ("Show S01 720", None, None)),
    ("Show 1000.mkv", ("Show", None, 1000)),
    ("Show 1100.mkv", ("Show", None, 1100)),
    ("Show 0101.mkv", ("Show", None, 101)),
    ("Show 1234.mkv", ("Show", None, 1234)),
    ("Show 9999.mkv", ("Show", None, 9999)),
    ("Show 1234 Title.mkv", ("Show", None, 1234)),
    ("Show.Name.1071.HDTV.mkv", ("Show Name", None, 1071)),
    ("Show OVA 2.mkv", ("Show OVA", None, 2)),
    ("[Group] My Hero Academia - 2nd Season - 04 [720p].mkv", ("My Hero Academia", 2, 4)),
    ("Show 2nd Season 1001.mkv", ("Show", 2, 1001)),
    ("Show S02E05.mkv", ("Show", 2, 5)),
    ("Criminal.Minds.01x01.mkv", ("Criminal Minds 01x01", None, None)),
    ("Breaking Bad Season 2 Episode 09.mkv", ("Breaking Bad Season 2 Episode", None, 9)),
    ("Episode 11 - 25 to Life.mkv", ("Episode", None, 11)),
    ("Yawara Ep. 7.mkv", ("Yawara Ep", None, 7)),
    ("[SubsPlease] Show - 06 (1080p) [ABCD1234].mkv", ("Show", None, 6)),
    ("Show 01 - The Beginning [hash].mkv", ("Show", None, 1)),
    ("32 - 100th Dirty Job Special.mkv", ("32 - 100th Dirty Job Special", None, None)),
    ("Bamboo Blade 20.mkv", ("Bamboo Blade", None, 20)),
    ("Show NCOP 01.mkv", ("Show NCOP", None, 1)),
    ("Show Season 2.mkv", ("Show Season", None, 2)),
    ("criminal.minds.201.mkv", ("criminal minds", None, 201)),
    ("criminal.minds.1001.mkv", ("criminal minds", None, 1001)),
    ("Show.Name.2024.1080p.WEB-DL.mkv", ("Show Name 2024", None, None)),
    ("Show 924.mkv", ("Show", None, 924)),
    ("Show 1024.mkv", ("Show", None, 1024)),
    ("One Piece 212.mkv", ("One Piece", None, 212)),
    ("No numbers here.mkv", ("No numbers here", None, None)),
    ("Show 1080.mkv", ("Show", None, None)),
]

# Regex grounding hint sent to the LLM.
SE_HINT_ROWS: list[tuple[str, tuple[int, int] | None]] = [
    ("Show S01E1001.mkv", (1, 1001)),
    ("Show 1x1000.mkv", (1, 1000)),
    ("Show - 1071 [1080p].mkv", None),
    ("One Piece 1071.mkv", None),
    ("Show 2024.mkv", None),
    ("Show 1080p.mkv", None),
    ("Episode 1100.mkv", None),
    ("Show S01E02.mkv", (1, 2)),
    ("Show 1x05.mkv", (1, 5)),
    ("Show 1x100.mkv", (1, 100)),
    ("Show 12x999.mkv", (12, 999)),
    ("Show S01E2024.mkv", (1, 2024)),
    ("Show 1x2024.mkv", (1, 2024)),
    ("ShowName.1920x1080.mkv", None),
    ("Show 2x1080.mkv", (2, 1080)),
    ("Show S10E100.mkv", (10, 100)),
]

# Tracker-format release titles (``Name - Kind [year] :: ... | Episode N``).
TRACKER_ROWS: list[tuple[str, tuple[str | None, int | None, int | None]]] = [
    (
        "Show Name - TV Series [2026] :: Web | MKV | h264 | 1080p | Episode 4 | Freeleech",
        ("Show Name", None, 4),
    ),
    (
        "Show Name - TV Series [2026] :: Web | MKV | h264 | 1080p | Episode 1001 | Freeleech",
        ("Show Name", None, 1001),
    ),
    (
        "Show Name - TV Series [2026] :: Web | MKV | h264 | 1080p | Episode 2024 | Freeleech",
        ("Show Name", None, 2024),
    ),
]

# (input, input with every quality/resolution token stripped).
_QUALITY_PATTERN_ROWS: list[tuple[str, str]] = [
    ("480", ""),
    ("480p", ""),
    ("576i", ""),
    ("720P", ""),
    ("1080p", ""),
    ("1080i", ""),
    ("2160p", ""),
    ("4320p", ""),
    ("_720", "_720"),
    ("x1080", "x1080"),
    ("1080p5", "5"),
    ("10800", "0"),
    ("11080", "11080"),
    ("720x", "x"),
    ("a.1080p.b", "a..b"),
    ("[2160p]", "[]"),
    ("-480-", "--"),
    ("4K", ""),
    ("4k", ""),
    ("UHD", ""),
    ("FHD", ""),
    ("HD", ""),
    ("SD", ""),
    ("BluRay", ""),
    ("bluray", ""),
    ("BDRip", ""),
    ("BRRip", ""),
    ("DVDRip", ""),
    ("WEBRip", ""),
    ("WEB-DL", ""),
    ("web-dl", ""),
    ("WEB DL", "WEB DL"),
    ("WEBDL", "WEBDL"),
    ("HDTV", ""),
    ("HD-TV", "-TV"),
    ("x264", ""),
    ("X265", ""),
    ("HEVC", ""),
    ("HEVC10", "HEVC10"),
    ("AVC", ""),
    ("AAC", ""),
    ("AC3", ""),
    ("DTS", ""),
    ("FLAC", ""),
    ("MP3", ""),
    ("Remux", ""),
    ("REPACK", ""),
    ("proper", ""),
    ("PROPERS", "PROPERS"),
    ("_HEVC", "_HEVC"),
    ("4KUHD", "4KUHD"),
    ("x264-GRP", "-GRP"),
    ("1080p.x264", "."),
    ("720p-HDTV", "-"),
    ("Show.Name.S01E02.1080p.WEB-DL.x264", "Show.Name.S01E02..."),
    ("Show 999", "Show 999"),
    ("Show 2024", "Show 2024"),
    ("123p", "123p"),
]


@pytest.mark.parametrize(("filename", "expected"), DF6_TABLE + SAMPLE)
def test_heuristic_parse_golden(
    filename: str, expected: tuple[str | None, int | None, int | None]
) -> None:
    """Each filename resolves to the pinned (show_name, season, episode)."""
    r = _heuristic_parse(filename)
    assert (r.show_name, r.season, r.episode) == expected


@pytest.mark.parametrize(("filename", "expected"), SE_HINT_ROWS)
def test_heuristic_se_golden(filename: str, expected: tuple[int, int] | None) -> None:
    """Each filename yields the pinned (season, episode) regex hint."""
    assert heuristic_se(filename) == expected


@pytest.mark.parametrize(("title", "expected"), TRACKER_ROWS)
def test_tracker_title_golden(
    title: str, expected: tuple[str | None, int | None, int | None]
) -> None:
    """Each tracker title resolves to the pinned (show_name, season, episode)."""
    r = parse_release_title(title)
    assert (r.show_name, r.season, r.episode) == expected


@pytest.mark.parametrize(("text", "stripped"), _QUALITY_PATTERN_ROWS)
def test_quality_pattern_strips_pinned_tokens(text: str, stripped: str) -> None:
    """The quality/resolution strip removes exactly the pinned substrings."""
    assert _QUALITY_PAT.sub("", text) == stripped


def test_golden_tables_are_not_empty() -> None:
    """Guard against a vacuous parametrization."""
    assert len(DF6_TABLE) == 7
    assert len(SAMPLE) >= 100
    assert len(SE_HINT_ROWS) >= 10
    assert len(TRACKER_ROWS) == 3
    assert len(_QUALITY_PATTERN_ROWS) >= 50


class _FrozenDate(date):
    """``date`` whose ``today()`` is pinned to 2040-06-01."""

    @classmethod
    def today(cls) -> "_FrozenDate":
        return cls(2040, 6, 1)


def test_year_exclusion_follows_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bare-number year bound is read from the clock at call time, not frozen at import."""
    monkeypatch.setattr("jidou.services.file_filters.date", _FrozenDate)
    # 2042 is "current year + 2" in the frozen clock: excluded. 2043 is not.
    assert _heuristic_parse("Show 2042.mkv").episode is None
    assert _heuristic_parse("Show 2043.mkv").episode == 2043
