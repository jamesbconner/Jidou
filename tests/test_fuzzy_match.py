"""Tests for the shared fuzzy matcher and the alias response schema built on llm_json."""

import pytest

from jidou.orchestrators.alias_orchestrator import _ALIAS_RESPONSE_FORMAT
from jidou.services.fuzzy_match import (
    FUZZY_THRESHOLD,
    unambiguous_best_match,
    unambiguous_title_match,
)
from jidou.services.rss_stub import pick_unlinked_subscription

# Literal copy of the schema as it was hand-written before json_schema_format
# was adopted; the helper must keep producing exactly this payload.
_LEGACY_ALIAS_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "show_aliases",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "aliases": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["aliases"],
            "additionalProperties": False,
        },
    },
}


def test_threshold_value() -> None:
    assert FUZZY_THRESHOLD == 85


def test_unambiguous_best_match_clear_winner() -> None:
    candidates = ["one piece", "marvel's daredevil", "bleach"]
    assert unambiguous_best_match("Daredevil", candidates) == 1


def test_unambiguous_best_match_is_case_insensitive() -> None:
    assert unambiguous_best_match("BLEACH", ["Naruto", "Bleach"]) == 1


def test_unambiguous_best_match_tie_returns_none() -> None:
    # Both candidates contain every query token, so both score 100.
    assert unambiguous_best_match("Daredevil", ["Daredevil Born Again", "Marvel Daredevil"]) is None


def test_unambiguous_best_match_below_threshold_returns_none() -> None:
    assert unambiguous_best_match("Naruto", ["Bleach", "One Piece"]) is None


def test_unambiguous_best_match_empty_candidates() -> None:
    assert unambiguous_best_match("Naruto", []) is None


def test_unambiguous_best_match_threshold_is_inclusive_and_overridable() -> None:
    # Identical strings score exactly 100, so a threshold of 100 still accepts them.
    assert unambiguous_best_match("bleach", ["bleach"], threshold=100) == 0
    assert unambiguous_best_match("bleach", ["bleach!"], threshold=100) is None


class _Sub:
    def __init__(self, name: str) -> None:
        self.name = name


@pytest.mark.parametrize(
    ("names", "title", "expected"),
    [
        (["Daredevil Born Again", "Daredevil"], "daredevil", 1),  # exact beats fuzzy tie
        (["Marvel Daredevil", "Daredevil Born Again"], "Daredevil", None),  # tie -> None
        (["Bleach", "Naruto"], "Naruto Shippuden", 1),
        (["Bleach"], "Unrelated", None),
        ([], "Anything", None),
    ],
)
def test_pick_unlinked_subscription_characterisation(
    names: list[str], title: str, expected: int | None
) -> None:
    subs = [_Sub(n) for n in names]
    picked = pick_unlinked_subscription(subs, title)  # type: ignore[arg-type]
    assert picked is (None if expected is None else subs[expected])


def test_alias_schema_unchanged() -> None:
    assert _ALIAS_RESPONSE_FORMAT == _LEGACY_ALIAS_RESPONSE_FORMAT


@pytest.mark.parametrize(
    ("query", "candidates", "expected"),
    [
        ("Some Show", ["Other", "some show"], 1),  # one exact match
        ("Some Show", ["Some Show", "SOME SHOW"], None),  # duplicate exact -> ambiguous
        ("Some Show", ["Some Show", "Some Show", "Some Show Extra"], None),  # no fuzzy fall-through
        ("Some Show", ["Some Show Extra", "Some Show"], 1),  # exact beats higher-listed fuzzy
        ("Daredevil", ["Marvel Daredevil", "Bleach"], 0),  # no exact: fuzzy fallback
        ("Daredevil", ["Daredevil Born Again", "Marvel Daredevil"], None),  # fuzzy tie
        ("Naruto", [], None),
    ],
)
def test_unambiguous_title_match(query: str, candidates: list[str], expected: int | None) -> None:
    assert unambiguous_title_match(query, candidates) == expected
