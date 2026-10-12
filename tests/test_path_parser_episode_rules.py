"""Golden table pinning the rule priority of ``path_parser._parse_episode``.

Characterization test: values were captured from current behavior, including outputs that look
wrong (e.g. ``"One Piece 212"``). Refactors must keep it green or update a row deliberately.
"""

from datetime import date

import pytest

from jidou.services.path_parser import _COMPACT_QUALITY, _parse_episode

# Year-relative rows are computed so the tables never go stale: the year exclusion's upper
# bound is "current year + 2" at runtime.
_Y = date.today().year
# Current year + 3 is the first year past the exclusion, so the compact guess splits it.
_AFTER_EXCLUSION_COMPACT = ((_Y + 3) // 100, (_Y + 3) % 100, _Y + 3)

GOLDEN: list[tuple[str, int | None, tuple[int | None, int | None, int | None]]] = [
    ("Show S02E05", None, (2, 5, None)),
    ("Criminal.Minds.01x01", None, (1, 1, None)),
    ("Breaking Bad Season 2 Episode 09", None, (2, 9, None)),
    ("Episode 11 - 25 to Life", None, (None, 11, None)),
    ("Yawara Ep. 7", None, (None, 7, None)),
    ("[SubsPlease] Show - 06 (1080p) [ABCD1234]", None, (None, 6, None)),
    ("Show 01 - The Beginning [hash]", None, (None, 1, None)),
    ("32 - 100th Dirty Job Special", None, (None, 32, None)),
    ("Bamboo Blade 20", None, (None, 20, None)),
    ("Show NCOP 01", None, (None, None, None)),
    ("Show Season 2", None, (None, None, None)),
    ("criminal.minds.201", None, (2, 1, 201)),
    ("criminal.minds.1001", None, (10, 1, 1001)),
    ("Show.Name.2024.1080p.WEB-DL", None, (None, None, None)),
    ("Show 924", 10, (None, None, None)),
    ("Show 1024", 10, (10, 24, 1024)),
    ("One Piece 212", None, (2, 12, 212)),
    ("No numbers here", None, (None, None, None)),
    ("Show 1080", None, (None, None, None)),
]


# DF-6 (D20): the roadmap's 4-digit-episode table, one row per input.
DF6_TABLE: list[tuple[str, int | None, tuple[int | None, int | None, int | None]]] = [
    ("Show S01E1001", None, (1, 1001, None)),
    ("Show 1x1000", None, (1, 1000, None)),
    ("Show - 1071 [1080p]", None, (None, 1071, None)),
    ("One Piece 1071", None, (10, 71, 1071)),
    ("Show 2024", None, (None, None, None)),
    ("Show 1080p", None, (None, None, None)),
    ("Episode 1100", None, (None, 1100, None)),
]

# DF-6 broad sample: every explicit marker, bare numbers, years, resolutions, quality words,
# versions, CRC hashes, season packs and the compact SEEE/SSEEE guess.
SAMPLE: list[tuple[str, int | None, tuple[int | None, int | None, int | None]]] = [
    ("Show - 5", None, (None, 5, None)),
    ("Show - 05", None, (None, 5, None)),
    ("Show - 123", None, (None, 123, None)),
    ("Show 7", None, (None, 7, None)),
    ("Show 42", None, (None, 42, None)),
    ("Show 999", None, (9, 99, 999)),
    ("[Group] Show - 999 [ABCD1234]", None, (None, 999, None)),
    ("[HorribleSubs] One Piece - 1001 [ABCD1234]", None, (None, 1001, None)),
    ("Show S01E02", None, (1, 2, None)),
    ("Show.S01E02.1080p.WEB-DL", None, (1, 2, None)),
    ("Show S1E5", None, (1, 5, None)),
    ("Show S10E100", None, (10, 100, None)),
    ("Show S01E999", None, (1, 999, None)),
    ("Show S01E2024", None, (1, 2024, None)),
    ("Show S01E1080", None, (1, 1080, None)),
    ("Show E05", None, (None, None, None)),
    ("Show E1001", None, (None, None, None)),
    ("Show 1x05", None, (1, 5, None)),
    ("Show.2x10.720p", None, (2, 10, None)),
    ("Show 1x100", None, (1, 100, None)),
    ("Show 12x999", None, (12, 999, None)),
    ("Show 2x1080", None, (2, 1080, None)),
    ("ShowName.1920x1080", None, (None, None, None)),
    ("Episode 5", None, (None, 5, None)),
    ("Episode 123", None, (None, 123, None)),
    ("Show Episode 2024", None, (None, 2024, None)),
    ("Show Season 2 Episode 1001", None, (2, 1001, None)),
    ("Show Ep 100", None, (None, 100, None)),
    ("Show Ep 1000", None, (None, 1000, None)),
    ("Show Ep.1234", None, (None, 1234, None)),
    ("Show - 1000", None, (None, 1000, None)),
    ("Show - 2024", None, (None, None, None)),
    ("Show - 1080 [x]", None, (None, None, None)),
    # Owner ruling: dash markers skip years and resolutions; word and SxxE/NxN markers do not.
    ("Show - 1071", None, (None, 1071, None)),
    ("Show - 1100", None, (None, 1100, None)),
    ("Show - 720 [x]", None, (None, None, None)),
    ("Show 1100 - Title", None, (None, 1100, None)),
    ("Show 720 - Title", None, (None, None, None)),
    ("720 - Title", None, (None, None, None)),
    ("Show - 2024 - 05", None, (None, 5, None)),
    ("Show Ep 2024", None, (None, 2024, None)),
    ("Show 1x2024", None, (1, 2024, None)),
    ("Show - 9999", None, (None, 9999, None)),
    ("Show Part 2 - 05", None, (None, 5, None)),
    ("Show 1001 - Big Title", None, (None, 1001, None)),
    ("Show 2024 - Title", None, (None, None, None)),
    ("1001 - Big Special", None, (None, 1001, None)),
    ("2024 - Year in Review", None, (None, None, None)),
    ("Show 1999", None, (None, None, None)),
    (f"Show {_Y + 2}", None, (None, None, None)),
    (f"Show {_Y + 3}", None, _AFTER_EXCLUSION_COMPACT),
    ("Show 1899", None, (18, 99, 1899)),
    ("Show 1900", None, (None, None, None)),
    ("Show.Name.1999.DVDRip", None, (None, None, None)),
    (f"Show.Name.{_Y + 2}.1080p.WEB-DL", None, (None, None, None)),
    (f"Show.Name.{_Y + 3}.1080p.WEB-DL", None, _AFTER_EXCLUSION_COMPACT),
    ("Show (2024) - 05", None, (None, 5, None)),
    ("Show 2024 05", None, (None, 5, None)),
    ("Show 2024 1071 x", None, (10, 71, 1071)),
    ("Show 480p", None, (None, None, None)),
    ("Show 720p", None, (None, None, None)),
    ("Show 2160p", None, (None, None, None)),
    ("Show 4K", None, (None, None, None)),
    ("Show 480", None, (None, None, None)),
    ("Show 720", None, (None, None, None)),
    ("Show 2160", None, (None, None, None)),
    ("Show 4320", None, (None, None, None)),
    ("Show_720", None, (None, None, None)),
    ("Show_1080", None, (None, None, None)),
    ("Show.1080i", None, (None, None, None)),
    ("Show 05 1080", None, (None, None, None)),
    ("Show - 05 [x264]", None, (None, 5, None)),
    ("Show.S01E02.HEVC.AAC", None, (1, 2, None)),
    ("Show 05 HDTV x265", None, (None, None, None)),
    ("Show.Name.BluRay.Remux.1080p", None, (None, None, None)),
    ("Show 05 WEB-DL", None, (None, None, None)),
    ("Show 12 PROPER REPACK", None, (None, None, None)),
    ("Show 1071 HDTV x265", None, (10, 71, 1071)),
    ("Show - 05v2", None, (None, None, None)),
    ("Show - 05v2 [1080p]", None, (None, None, None)),
    ("Show 1071v2", None, (None, None, None)),
    ("Show - 1071v2 [x]", None, (None, None, None)),
    ("[Group] Show - 1071 [ABCD1234]", None, (None, 1071, None)),
    ("Show 1071 [ABCD1234]", None, (10, 71, 1071)),
    ("Show S01 Complete", None, (None, None, None)),
    ("Show S01 1080p", None, (None, None, None)),
    ("Show S02 05", None, (None, 5, None)),
    ("Show S01 2024", None, (None, None, None)),
    ("Show S01 1001", None, (10, 1, 1001)),
    ("Show.S01.1001", None, (10, 1, 1001)),
    ("Show S01_720", None, (None, None, None)),
    ("Show 1000", None, (None, None, None)),
    ("Show 1100", None, (None, None, None)),
    ("Show 0101", None, (1, 1, 101)),
    ("Show 1234", None, (12, 34, 1234)),
    ("Show 9999", None, (99, 99, 9999)),
    ("Show 1234 Title", None, (12, 34, 1234)),
    ("Show.Name.1071.HDTV", None, (10, 71, 1071)),
    ("Show OVA 2", None, (None, None, None)),
    ("[Group] My Hero Academia - 2nd Season - 04 [720p]", None, (None, 4, None)),
    ("Show 2nd Season 1001", None, (10, 1, 1001)),
    ("Show 1071", 10, (10, 71, 1071)),
    ("One Piece 1071", 10, (10, 71, 1071)),
    ("Show 1x1000", 10, (1, 1000, None)),
    ("Show - 1071 [1080p]", 10, (None, 1071, None)),
]


@pytest.mark.parametrize(("stem", "dir_season", "expected"), GOLDEN)
def test_parse_episode_golden(
    stem: str, dir_season: int | None, expected: tuple[int | None, int | None, int | None]
) -> None:
    """Each stem resolves to the pinned (season, episode, absolute) triple."""
    assert _parse_episode(stem, dir_season=dir_season) == expected


@pytest.mark.parametrize(("stem", "dir_season", "expected"), DF6_TABLE + SAMPLE)
def test_parse_episode_df6_rows(
    stem: str, dir_season: int | None, expected: tuple[int | None, int | None, int | None]
) -> None:
    """Each DF-6 table and sample stem resolves to the pinned (season, episode, absolute)."""
    assert _parse_episode(stem, dir_season=dir_season) == expected


def test_df6_tables_are_not_empty() -> None:
    """Guard against a vacuous parametrization."""
    assert len(DF6_TABLE) == 7
    assert len(SAMPLE) >= 90


def test_compact_quality_tokens_are_pinned() -> None:
    """The compact guess skips exactly these resolution tokens (D21 must not change the set)."""
    assert frozenset({"480", "576", "720", "1080", "2160", "4320"}) == _COMPACT_QUALITY


class _FrozenDate(date):
    """``date`` whose ``today()`` is pinned to 2040-06-01."""

    @classmethod
    def today(cls) -> "_FrozenDate":
        return cls(2040, 6, 1)


def test_compact_year_exclusion_follows_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The compact guess reads the year bound from the clock at call time."""
    monkeypatch.setattr("jidou.services.file_filters.date", _FrozenDate)
    assert _parse_episode("Show 2042") == (None, None, None)
    assert _parse_episode("Show 2043") == (20, 43, 2043)
