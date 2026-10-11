"""Tests for evaluating include/exclude regex filters against release titles."""

import re

import pytest

from jidou.services.rss_regex_matching import MAX_TITLE_LENGTH, evaluate_regex

TITLES = [
    "Show.Name.S02E05.1080p.WEB-DL.DDP5.1-GRP",
    "Show.Name.S02E05.720p.HDTV-GRP",
    "Show.Name.S02E05.1080p.WEB-DL.FRENCH-GRP",
    "Other.Show.S01E01.1080p.WEB-DL-GRP",
]


def test_include_selects_matching_titles_in_input_order() -> None:
    report = evaluate_regex(TITLES, include=r"Show\.Name.*1080p", exclude=None)

    assert report.matched == [TITLES[0], TITLES[2]]
    assert report.unmatched == [TITLES[1], TITLES[3]]
    assert report.total == 4


def test_exclude_drops_titles_the_include_selected() -> None:
    report = evaluate_regex(TITLES, include=r"Show\.Name.*1080p", exclude="FRENCH|GERMAN")

    assert report.matched == [TITLES[0]]
    assert TITLES[2] in report.unmatched


@pytest.mark.parametrize("include", [None, ""])
def test_empty_include_selects_nothing_like_yarss2(include: str | None) -> None:
    # YaRSS2 only marks an item as matching when an include pattern exists and
    # matches, so a subscription without one never downloads anything. An
    # exclude pattern cannot resurrect titles.
    report = evaluate_regex(TITLES, include=include, exclude="720p")

    assert report.matched == []
    assert report.unmatched == TITLES


def test_empty_exclude_excludes_nothing() -> None:
    report = evaluate_regex(TITLES, include="Show", exclude="")

    assert report.matched == TITLES
    assert report.unmatched == []


def test_ignorecase_flags_are_independent() -> None:
    insensitive = evaluate_regex(["show.name.s01e01"], include="SHOW.NAME", exclude=None)
    sensitive = evaluate_regex(
        ["show.name.s01e01"], include="SHOW.NAME", exclude=None, include_ignorecase=False
    )
    exclude_sensitive = evaluate_regex(
        ["show.name FRENCH"],
        include="show",
        exclude="french",
        exclude_ignorecase=False,
    )
    exclude_insensitive = evaluate_regex(["show.name FRENCH"], include="show", exclude="french")

    assert insensitive.matched == ["show.name.s01e01"]
    assert sensitive.matched == []
    assert exclude_sensitive.matched == ["show.name FRENCH"]
    assert exclude_insensitive.matched == []


def test_include_uses_search_semantics_not_full_match() -> None:
    report = evaluate_regex(["prefix Show.Name suffix"], include="Show.Name", exclude=None)

    assert report.matched == ["prefix Show.Name suffix"]


def test_invalid_pattern_raises_re_error() -> None:
    with pytest.raises(re.error):
        evaluate_regex(TITLES, include="(unclosed", exclude=None)


def test_very_long_titles_are_only_probed_up_to_the_cap() -> None:
    title = "a" * (MAX_TITLE_LENGTH + 50) + "NEEDLE"

    report = evaluate_regex([title], include="NEEDLE", exclude=None)

    assert report.matched == []  # the tail beyond the cap is never inspected
    assert report.unmatched == [title]  # but the original title is reported intact
