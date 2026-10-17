"""Tests for parsing and normalising a comma-separated list of UTC schedule hours."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from jidou.services.schedule_hours import (
    is_hour_due,
    normalize_schedule_hours,
    parse_schedule_hours,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4", [4]),
        ("2,14", [2, 14]),
        ("14, 2", [2, 14]),  # sorted
        (" 4 , 16 ", [4, 16]),  # whitespace tolerated
        ("4,4,16", [4, 16]),  # duplicates collapsed
        ("0,23", [0, 23]),  # bounds are inclusive
        ("04", [4]),  # leading zero
    ],
)
def test_parse_valid(raw: str, expected: list[int]) -> None:
    assert parse_schedule_hours(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", ",", "24", "-1", "4,25", "a", "4;16", "4.5", "4,,16x"],
)
def test_parse_invalid_raises_value_error(raw: str) -> None:
    with pytest.raises(ValueError, match="hour"):
        parse_schedule_hours(raw)


def test_parse_skips_empty_segments_but_needs_at_least_one_hour() -> None:
    assert parse_schedule_hours("4,,16") == [4, 16]
    with pytest.raises(ValueError, match="at least one hour"):
        parse_schedule_hours(" , ")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("4", "4"), ("16, 4", "4,16"), (" 04 ,4", "4"), ("0,23", "0,23")],
)
def test_normalize_is_canonical(raw: str, expected: str) -> None:
    assert normalize_schedule_hours(raw) == expected


def test_normalize_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_schedule_hours("25")


@pytest.mark.parametrize(
    ("hours", "hour", "due"),
    [("4", 4, True), ("4", 5, False), ("4,16", 16, True), ("4,16", 15, False), ("0", 0, True)],
)
def test_is_hour_due_matches_the_current_utc_hour(hours: str, hour: int, due: bool) -> None:
    now = datetime(2026, 10, 16, hour, 17, tzinfo=UTC)  # minutes are irrelevant
    assert is_hour_due(hours, now) is due


def test_is_hour_due_compares_in_utc_not_local_time() -> None:
    # 06:30 at UTC+2 is 04:30 UTC.
    local = datetime(2026, 10, 16, 6, 30, tzinfo=timezone(timedelta(hours=2)))
    assert is_hour_due("4", local) is True
    assert is_hour_due("6", local) is False


@pytest.mark.parametrize("bad", ["", "25", "a", "4;16"])
def test_is_hour_due_is_false_for_an_invalid_hour_list(bad: str) -> None:
    """A broken value must skip quietly each hour, not raise from the scheduler."""
    assert is_hour_due(bad, datetime(2026, 10, 16, 4, tzinfo=UTC)) is False
