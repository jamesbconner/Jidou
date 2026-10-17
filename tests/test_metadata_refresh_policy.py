"""Tests for the pure show-metadata refresh candidate policy."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from jidou.services.metadata_refresh_policy import (
    RefreshPolicy,
    RefreshReason,
    ShowRefreshFacts,
    classify,
    is_in_lookback,
    select_candidates,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


def _policy(**overrides: object) -> RefreshPolicy:
    base = {
        "now": NOW,
        "limit": 10,
        "stale_days": 30,
        "airing_days": 7,
        "ended_days": 90,
        "lookback_years": 5,
    }
    return RefreshPolicy(**{**base, **overrides})  # type: ignore[arg-type]


def _facts(show_id: int = 1, **overrides: object) -> ShowRefreshFacts:
    """A healthy, recently refreshed, airing show that matches no rule."""
    base = ShowRefreshFacts(
        show_id=show_id,
        title=f"Show {show_id}",
        media_type="tv",
        status="Returning Series",
        metadata_refreshed_at=NOW - timedelta(days=1),
        vote_count=50,
        next_air_date=TODAY + timedelta(days=3),
        last_air_date=TODAY - timedelta(days=4),
        latest_season_fully_aired=False,
        has_rss_subscription=False,
    )
    return replace(base, **overrides)


def test_healthy_recent_show_matches_nothing() -> None:
    assert classify(_facts(), _policy()) is None


def test_regression_past_next_episode_is_contradictory_and_ranks_first() -> None:
    """A show added mid-season that has since ended still lists a past 'next' episode."""
    stuck = _facts(
        99,
        status="Returning Series",
        metadata_refreshed_at=NOW - timedelta(days=40),
        next_air_date=TODAY - timedelta(days=42),
        last_air_date=TODAY - timedelta(days=49),
        latest_season_fully_aired=True,
    )
    never = [_facts(i, metadata_refreshed_at=None) for i in range(1, 16)]

    assert classify(stuck, _policy()) is RefreshReason.CONTRADICTORY
    picked = select_candidates([*never, stuck], _policy())
    assert len(picked) == 10
    assert picked[0][0].show_id == 99


def test_never_refreshed_selected() -> None:
    f = _facts(metadata_refreshed_at=None)
    assert classify(f, _policy()) is RefreshReason.NEVER_REFRESHED


@pytest.mark.parametrize(("age_days", "due"), [(6, False), (8, True)])
def test_airing_due_after_airing_interval(age_days: int, due: bool) -> None:
    f = _facts(metadata_refreshed_at=NOW - timedelta(days=age_days))
    expected = RefreshReason.AIRING_DUE if due else None
    assert classify(f, _policy()) is expected


@pytest.mark.parametrize(("age_days", "due"), [(60, False), (91, True)])
@pytest.mark.parametrize("status", ["Ended", "Cancelled", "Released"])
def test_ended_statuses_use_the_long_interval(status: str, age_days: int, due: bool) -> None:
    f = _facts(
        status=status,
        next_air_date=None,
        vote_count=10,
        metadata_refreshed_at=NOW - timedelta(days=age_days),
        last_air_date=TODAY - timedelta(days=400),
    )
    expected = RefreshReason.ENDED_RECHECK if due else None
    assert classify(f, _policy()) is expected


def test_unknown_status_uses_stale_interval() -> None:
    f = _facts(status=None, metadata_refreshed_at=NOW - timedelta(days=31))
    assert classify(f, _policy()) is RefreshReason.STALE


def test_zero_votes_selected_once_stale() -> None:
    fresh = _facts(status="Ended", next_air_date=None, vote_count=0)
    old = replace(fresh, metadata_refreshed_at=NOW - timedelta(days=31))
    assert classify(fresh, _policy()) is None
    assert classify(old, _policy()) is RefreshReason.ZERO_VOTES


def test_season_finished_since_last_refresh_selected() -> None:
    f = _facts(
        metadata_refreshed_at=NOW - timedelta(days=3),
        last_air_date=TODAY - timedelta(days=1),
        latest_season_fully_aired=True,
        next_air_date=None,
    )
    assert classify(f, _policy()) is RefreshReason.SEASON_FULLY_AIRED


def test_season_finished_before_last_refresh_is_not_reselected() -> None:
    f = _facts(
        metadata_refreshed_at=NOW - timedelta(days=3),
        last_air_date=TODAY - timedelta(days=20),
        latest_season_fully_aired=True,
        next_air_date=None,
    )
    assert classify(f, _policy()) is None


def test_lookback_excludes_last_air_older_than_five_years() -> None:
    old = _facts(last_air_date=TODAY - timedelta(days=366 * 6), metadata_refreshed_at=None)
    assert not is_in_lookback(old, _policy())
    assert select_candidates([old], _policy()) == []


def test_null_last_air_date_is_eligible() -> None:
    f = _facts(last_air_date=None, metadata_refreshed_at=None)
    assert is_in_lookback(f, _policy())
    assert len(select_candidates([f], _policy())) == 1


def test_min_recheck_guard_prevents_immediate_repick() -> None:
    """Contradictory TMDB data must not be re-picked every run."""
    f = _facts(
        metadata_refreshed_at=NOW - timedelta(hours=1),
        next_air_date=TODAY - timedelta(days=2),
    )
    assert classify(f, _policy()) is None


def test_cap_applied_after_ranking() -> None:
    contradictory = _facts(
        50, next_air_date=TODAY - timedelta(days=1), metadata_refreshed_at=NOW - timedelta(days=2)
    )
    stale = [_facts(i, metadata_refreshed_at=NOW - timedelta(days=9)) for i in range(1, 5)]
    picked = select_candidates([*stale, contradictory], _policy(limit=2))
    assert picked[0][0].show_id == 50
    assert len(picked) == 2


def test_tie_break_is_oldest_refresh_first_with_never_first() -> None:
    a = _facts(1, metadata_refreshed_at=NOW - timedelta(days=10))
    b = _facts(2, metadata_refreshed_at=NOW - timedelta(days=20))
    picked = select_candidates([a, b], _policy())
    assert [f.show_id for f, _ in picked] == [2, 1]


def test_rss_subscribed_show_ranks_first_within_a_reason() -> None:
    plain = _facts(1, metadata_refreshed_at=NOW - timedelta(days=30))
    subscribed = _facts(2, metadata_refreshed_at=NOW - timedelta(days=9), has_rss_subscription=True)
    picked = select_candidates([plain, subscribed], _policy())
    assert [f.show_id for f, _ in picked] == [2, 1]


def test_contradictory_outranks_rss_priority() -> None:
    rss_stale = _facts(1, metadata_refreshed_at=NOW - timedelta(days=30), has_rss_subscription=True)
    broken = _facts(
        2, metadata_refreshed_at=NOW - timedelta(days=2), next_air_date=TODAY - timedelta(days=5)
    )
    picked = select_candidates([rss_stale, broken], _policy())
    assert picked[0][0].show_id == 2


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _policy(now=datetime(2026, 10, 16, 12, 0))


def test_lookback_handles_leap_day() -> None:
    p = _policy(now=datetime(2028, 2, 29, tzinfo=UTC))
    assert is_in_lookback(_facts(last_air_date=date(2023, 3, 1)), p)
