"""Tests for matching feed entry groups to subscriptions by their filter regexes."""

import logging

import pytest

from jidou.services.feed_subscription_match import SubscriptionMatcher, SubscriptionRule

TITLES = [
    "Example Show - TV Series [2026] :: Web | MKV | h264 | 1080p | Episode 4 | Freeleech",
    "Example Show - TV Series [2026] :: Web | MKV | h264 | 720p | Episode 4 | Freeleech",
]


def _rule(sub_id: int, include: str | None, **kw: object) -> SubscriptionRule:
    return SubscriptionRule(subscription_id=sub_id, show_id=None, regex_include=include, **kw)  # type: ignore[arg-type]


def test_matches_by_include_regex() -> None:
    matcher = SubscriptionMatcher([_rule(5, r"^Example.Show.*1080p.*Freeleech$")])

    assert matcher.find(TITLES) == 5


def test_no_match_returns_none() -> None:
    matcher = SubscriptionMatcher([_rule(5, r"^Different.Show")])

    assert matcher.find(TITLES) is None


def test_match_on_any_title_in_group() -> None:
    matcher = SubscriptionMatcher([_rule(5, r"720p")])

    assert matcher.find(TITLES) == 5


def test_exclude_regex_vetoes_a_title() -> None:
    matcher = SubscriptionMatcher([_rule(5, r"Example", regex_exclude=r"Freeleech")])

    assert matcher.find(TITLES) is None


def test_exclude_only_vetoes_matching_titles() -> None:
    matcher = SubscriptionMatcher([_rule(5, r"Example", regex_exclude=r"1080p")])

    assert matcher.find(TITLES) == 5  # the 720p title still passes


def test_case_sensitivity_follows_the_ignorecase_flag() -> None:
    sensitive = SubscriptionMatcher([_rule(5, r"example show", include_ignorecase=False)])
    insensitive = SubscriptionMatcher([_rule(5, r"example show", include_ignorecase=True)])

    assert sensitive.find(TITLES) is None
    assert insensitive.find(TITLES) == 5


def test_lowest_subscription_id_wins() -> None:
    matcher = SubscriptionMatcher([_rule(9, r"Example"), _rule(3, r"Example")])

    assert matcher.find(TITLES) == 3


@pytest.mark.parametrize("include", [None, ""])
def test_rule_without_include_regex_never_matches_by_regex(include: str | None) -> None:
    assert SubscriptionMatcher([_rule(5, include)]).find(TITLES) is None


def test_invalid_regex_is_skipped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    matcher = SubscriptionMatcher([_rule(4, r"(unclosed"), _rule(6, r"Example")])

    with caplog.at_level(logging.WARNING):
        assert matcher.find(TITLES) == 6
    assert any("4" in r.message for r in caplog.records)


def test_falls_back_to_show_link_when_no_regex_matches() -> None:
    rule = SubscriptionRule(subscription_id=8, show_id=42, regex_include=r"^nope$")
    matcher = SubscriptionMatcher([rule])

    assert matcher.find(TITLES, show_id=42) == 8
    assert matcher.find(TITLES, show_id=43) is None
    assert matcher.find(TITLES) is None


def test_regex_match_beats_show_link() -> None:
    linked = SubscriptionRule(subscription_id=2, show_id=42, regex_include=r"^nope$")
    by_regex = SubscriptionRule(subscription_id=9, show_id=None, regex_include=r"Example")
    matcher = SubscriptionMatcher([linked, by_regex])

    assert matcher.find(TITLES, show_id=42) == 9
