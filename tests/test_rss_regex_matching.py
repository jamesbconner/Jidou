"""Tests for evaluating include/exclude regex filters against release titles."""

import re

import pytest

from jidou.services.rss_regex_matching import (
    MAX_TITLE_LENGTH,
    CompiledFilter,
    compile_pattern,
    evaluate_regex,
)

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


# --- Characterization tests (pin pre-CompiledFilter behaviour) --------------


def test_invalid_exclude_raises_even_when_include_is_empty() -> None:
    # Both patterns are compiled up front, so a bad exclude fails the whole call.
    with pytest.raises(re.error):
        evaluate_regex(TITLES, include=None, exclude="(unclosed")


def test_invalid_include_raises_before_exclude_is_considered() -> None:
    with pytest.raises(re.error):
        evaluate_regex(TITLES, include="[bad", exclude="(also bad")


def test_empty_titles_still_validate_patterns() -> None:
    assert evaluate_regex([], include="x", exclude=None).total == 0
    with pytest.raises(re.error):
        evaluate_regex([], include="(unclosed", exclude=None)


def test_exclude_beyond_the_cap_is_not_seen() -> None:
    title = "keep " + "a" * MAX_TITLE_LENGTH + "FRENCH"

    report = evaluate_regex([title], include="keep", exclude="FRENCH")

    assert report.matched == [title]


def test_both_flags_off_are_case_sensitive() -> None:
    report = evaluate_regex(
        ["Show FRENCH", "show french"],
        include="Show",
        exclude="FRENCH",
        include_ignorecase=False,
        exclude_ignorecase=False,
    )

    assert report.matched == []
    assert report.unmatched == ["Show FRENCH", "show french"]


def test_compile_pattern_empty_and_flags() -> None:
    assert compile_pattern(None, True) is None
    assert compile_pattern("", False) is None
    assert compile_pattern("a", True) is not None
    assert compile_pattern("a", True).flags & re.IGNORECASE  # type: ignore[union-attr]
    assert not compile_pattern("a", False).flags & re.IGNORECASE  # type: ignore[union-attr]
    with pytest.raises(re.error):
        compile_pattern("(unclosed", True)


def test_compiled_filter_accepts() -> None:
    assert not CompiledFilter(include=None, exclude=re.compile("x")).accepts("x")
    assert CompiledFilter(include=re.compile("show"), exclude=None).accepts("a show b")
    both = CompiledFilter(include=re.compile("show"), exclude=re.compile("french"))
    assert not both.accepts("show french")
    assert both.accepts("show english")
    # Case-folding off: "SHOW" must not satisfy "show".
    assert not CompiledFilter(include=compile_pattern("show", False), exclude=None).accepts("SHOW")
