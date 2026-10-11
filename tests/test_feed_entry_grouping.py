"""Tests for grouping feed entries by parsed show name."""

import pytest

from jidou.services.feed_entry_grouping import MAX_SAMPLE_TITLES, group_entries
from jidou.services.feed_fetch import FeedEntry
from jidou.services.filename_parser import parse_release_title


def _e(title: str) -> FeedEntry:
    return FeedEntry(title=title, guid=None, published=None)


def test_groups_entries_of_same_show_and_tracks_season_episode_span() -> None:
    entries = [
        _e("Show.Name.S02E05.1080p.WEB-DL-GRP"),
        _e("Show.Name.S02E07.1080p.WEB-DL-GRP"),
        _e("Show.Name.S01E12.720p.HDTV-GRP"),
    ]

    groups = group_entries(entries)

    assert len(groups) == 1
    g = groups[0]
    assert g.parsed_name == "Show Name"
    assert g.entry_count == 3
    assert (g.season_min, g.season_max) == (1, 2)
    assert (g.episode_min, g.episode_max) == (5, 12)
    assert len(g.titles) == 3


def test_grouping_is_case_and_whitespace_insensitive() -> None:
    groups = group_entries([_e("show name - 01"), _e("SHOW  NAME - 02")])

    assert len(groups) == 1
    assert groups[0].entry_count == 2


def test_different_shows_are_ordered_by_count_then_name() -> None:
    entries = [_e("Zeta - 01"), _e("Alpha - 01"), _e("Alpha - 02"), _e("Beta - 01")]

    groups = group_entries(entries)

    assert [g.parsed_name for g in groups] == ["Alpha", "Beta", "Zeta"]


def test_sample_titles_are_capped_but_titles_are_complete() -> None:
    entries = [_e(f"Show - {i:02d}") for i in range(1, 8)]

    (g,) = group_entries(entries)

    assert len(g.sample_titles) == MAX_SAMPLE_TITLES
    assert len(g.titles) == 7


def test_unparseable_titles_share_a_single_unnamed_group() -> None:
    groups = group_entries([_e("[1080p]"), _e("(WEB-DL)")])

    unnamed = [g for g in groups if g.parsed_name is None]
    assert len(unnamed) == 1
    assert unnamed[0].entry_count == 2


def test_empty_input() -> None:
    assert group_entries([]) == []


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Fate/stay night - 05", "Fate/stay night"),
        ("Fate\\Zero - 01", "Fate\\Zero"),
        ("[Grp] Fate/stay night - 05 (1080p).mkv", "Fate/stay night"),
    ],
)
def test_parse_release_title_preserves_path_separators_in_the_name(
    title: str, expected: str
) -> None:
    assert parse_release_title(title).show_name == expected


def test_slash_titled_show_keeps_its_exact_name_so_library_lookup_can_match() -> None:
    (g,) = group_entries([_e("Fate/stay night - 05"), _e("Fate/Stay Night - 06")])

    assert g.parsed_name == "Fate/stay night"
    assert g.entry_count == 2


_TRACKER_TITLE = (
    "{name} - TV Series [2026] :: Web | MKV | h264 | 1080p | AAC 2.0 | "
    "Softsubs (Group) | Episode {ep} | Freeleech"
)


@pytest.mark.parametrize(
    ("title", "name", "episode"),
    [
        (_TRACKER_TITLE.format(name="Example Show", ep=7), "Example Show", 7),
        (_TRACKER_TITLE.format(name="#Hashtag Show", ep=12), "#Hashtag Show", 12),
        (_TRACKER_TITLE.format(name="Show [Re] Name", ep=1), "Show [Re] Name", 1),
        (
            "Example Show - ONA :: Web | MKV | h265 | 1080p | Episode 3 | Freeleech",
            "Example Show",
            3,
        ),
        ("Other Show - TV Series :: Web | MKV | h265", "Other Show", None),
    ],
)
def test_tracker_formatted_title_yields_show_name_and_episode(
    title: str, name: str, episode: int | None
) -> None:
    parsed = parse_release_title(title)

    assert parsed.show_name == name
    assert parsed.episode == episode


def test_tracker_formatted_titles_of_one_show_share_a_group() -> None:
    entries = [
        _e(_TRACKER_TITLE.format(name="Example Show", ep=7).replace("1080p", "720p")),
        _e(_TRACKER_TITLE.format(name="Example Show", ep=7)),
        _e(_TRACKER_TITLE.format(name="Example Show", ep=8)),
    ]

    (g,) = group_entries(entries)

    assert g.parsed_name == "Example Show"
    assert g.entry_count == 3
    assert (g.episode_min, g.episode_max) == (7, 8)
