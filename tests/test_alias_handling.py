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
