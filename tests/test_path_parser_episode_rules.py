"""Golden table pinning the rule priority of ``path_parser._parse_episode``.

Characterization test: values were captured from current behavior, including outputs that look
wrong (e.g. ``"One Piece 212"``). Refactors must keep it green or update a row deliberately.
"""

import pytest

from jidou.services.path_parser import _parse_episode

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


@pytest.mark.parametrize(("stem", "dir_season", "expected"), GOLDEN)
def test_parse_episode_golden(
    stem: str, dir_season: int | None, expected: tuple[int | None, int | None, int | None]
) -> None:
    """Each stem resolves to the pinned (season, episode, absolute) triple."""
    assert _parse_episode(stem, dir_season=dir_season) == expected
