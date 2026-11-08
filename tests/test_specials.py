"""Tests for the per-show specials opt-in predicate."""

import pytest

from jidou.models.show import Show
from jidou.services.specials import wants_specials


@pytest.mark.parametrize(
    ("sync_specials", "season_aliases", "expected"),
    [
        (False, None, False),
        (False, {}, False),
        (True, None, True),
        (False, {"omake shorts": 0}, True),
        (False, {"example arc-hen": 2}, False),
        (False, {"example arc-hen": 2, "omake shorts": 0}, True),
    ],
)
def test_wants_specials(
    sync_specials: bool, season_aliases: dict[str, int] | None, expected: bool
) -> None:
    """A show opts in via the toggle or any season alias that maps to season 0."""
    show = Show(title="Example Show", sync_specials=sync_specials, season_aliases=season_aliases)
    assert wants_specials(show) is expected
