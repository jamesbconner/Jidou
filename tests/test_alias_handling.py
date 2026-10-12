"""Tests for the shared alias-handling helpers."""

import pytest

from jidou.models.show import Show
from jidou.services.alias_handling import add_alias, sanitize_alias


def _show(
    *,
    aliases: list[str] | None = None,
    sources: dict[str, list[str]] | None = None,
) -> Show:
    return Show(
        tmdb_id=1,
        title="Example Show",
        media_type="tv",
        aliases=aliases,
        aliases_sources=sources,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Attack on Titan  ", "attack on titan"), ("MiXeD", "mixed"), ("", "")],
)
def test_sanitize_alias(raw: str, expected: str) -> None:
    assert sanitize_alias(raw) == expected


def test_add_alias_populates_flat_and_user_source() -> None:
    show = _show()

    add_alias(show, "  Example Show (2019) ")

    assert show.aliases == ["example show (2019)"]
    assert show.aliases_sources == {"user": ["example show (2019)"]}


def test_add_alias_is_idempotent() -> None:
    show = _show()

    add_alias(show, "Example")
    add_alias(show, "EXAMPLE")

    assert show.aliases == ["example"]
    assert show.aliases_sources == {"user": ["example"]}


def test_add_alias_preserves_other_sources() -> None:
    show = _show(
        aliases=["tmdb name", "llm name"],
        sources={"tmdb": ["tmdb name"], "llm": ["llm name"]},
    )

    add_alias(show, "New Name")

    assert show.aliases == ["tmdb name", "llm name", "new name"]
    assert show.aliases_sources == {
        "tmdb": ["tmdb name"],
        "llm": ["llm name"],
        "user": ["new name"],
    }


def test_add_alias_seeds_user_bucket_for_legacy_show() -> None:
    """Flat aliases with no source map are kept under 'user' so a UI save keeps them."""
    show = _show(aliases=["legacy one"], sources=None)

    add_alias(show, "Fresh")

    assert show.aliases == ["legacy one", "fresh"]
    assert show.aliases_sources == {"user": ["legacy one", "fresh"]}


# --- names_agree (DF-9 / D15): the single name-agreement rule ---------------

_DAREDEVIL = "Daredevil: Born Again"


def _titled(title: str, aliases: list[str] | None = None) -> Show:
    return Show(tmdb_id=1, title=title, media_type="tv", aliases=aliases)


def test_names_agree_ignores_punctuation_in_title() -> None:
    from jidou.services.alias_handling import names_agree

    assert names_agree("Daredevil Born Again", _titled(_DAREDEVIL)) is True


def test_names_agree_never_matches_a_substring() -> None:
    from jidou.services.alias_handling import names_agree

    assert names_agree("Daredevil", _titled(_DAREDEVIL)) is False
    assert names_agree("Daredevil: Born Again Season 2", _titled(_DAREDEVIL)) is False


def test_names_agree_matches_alias() -> None:
    from jidou.services.alias_handling import names_agree

    show = _titled("Attack on Titan", ["shingeki no kyojin"])
    assert names_agree("Shingeki no Kyojin", show) is True
    assert names_agree("Bleach", show) is False


# (name, title, aliases, old parse rule, old path-import rule, new rule).
# Old results were measured against the two pre-DF-9 implementations.
_RULE_CASES = [
    # Agreed already under both old rules: unchanged.
    ("attack on titan", "Attack on Titan", None, True, True, True),
    ("  Bleach ", "Bleach", [], True, True, True),
    ("shingeki no kyojin", "Attack on Titan", ["shingeki no kyojin"], True, True, True),
    ("Daredevil", _DAREDEVIL, None, False, False, False),
    ("Bleach", "One Piece", ["op"], False, False, False),
    # Title punctuation: only the path-import rule ignored it.
    ("Daredevil Born Again", _DAREDEVIL, None, False, True, True),
    ("Re Zero", "Re:Zero", None, False, True, True),
    ("Tom & Jerry", "Tom and Jerry", None, False, False, False),
    ("Dont Look Up", "Don't Look Up", None, False, False, False),
    ("Don't Look Up", "Don't Look Up", None, True, True, True),
    # Alias punctuation: neither old rule ignored it in aliases.
    ("Re Zero", "Re Zero Starting Life", ["re:zero"], False, False, True),
    ("Re:Zero", "Re Zero Starting Life", ["re zero"], False, False, True),
    # Aliases are never matched by substring.
    ("Shingeki", "Attack on Titan", ["shingeki no kyojin"], False, False, False),
    # Unicode is kept (no folding), so accents still distinguish names.
    ("Pokémon", "Pokémon", None, True, True, True),
    ("Pokemon", "Pokémon", None, False, False, False),
    # Punctuation-only names compare on raw text; the old path rule wrongly
    # treated any two of them as equal (both normalised to the empty string).
    ("!!!", "!!!", None, True, True, True),
    ("???", "!!!", None, False, True, False),
]


@pytest.mark.parametrize(("name", "title", "aliases", "old_parse", "old_path", "new"), _RULE_CASES)
def test_names_agree_rule_table(
    name: str,
    title: str,
    aliases: list[str] | None,
    old_parse: bool,
    old_path: bool,
    new: bool,
) -> None:
    from jidou.services.alias_handling import names_agree

    assert names_agree(name, _titled(title, aliases)) is new
    # The old results document which rule changes outcome; no further oracle.
    assert isinstance(old_parse, bool) and isinstance(old_path, bool)
