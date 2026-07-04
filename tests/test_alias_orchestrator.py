"""Tests for the alias orchestrator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.orchestrators.alias_orchestrator import (
    _build_flat_aliases,
    _extract_tmdb_aliases,
    generate_aliases,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_show(
    show_id: int = 1,
    tmdb_id: int = 100,
    title: str = "Attack on Titan",
    media_type: str = "tv",
    aliases: list[str] | None = None,
    aliases_sources: dict[str, list[str]] | None = None,
) -> MagicMock:
    s = MagicMock()
    s.id = show_id
    s.tmdb_id = tmdb_id
    s.title = title
    s.media_type = media_type
    s.aliases = aliases
    s.aliases_sources = aliases_sources
    return s


def _make_tmdb(alt_titles_response: dict) -> MagicMock:
    t = MagicMock()
    t.get_alternative_titles = AsyncMock(return_value=alt_titles_response)
    return t


def _make_llm(response_text: str = '["aot", "shingeki"]') -> MagicMock:
    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = response_text
    llm.complete = AsyncMock(return_value=response)
    return llm


# ---------------------------------------------------------------------------
# _extract_tmdb_aliases
# ---------------------------------------------------------------------------


def test_extract_includes_priority_countries() -> None:
    raw = {
        "results": [
            {"iso_3166_1": "JP", "title": "進撃の巨人", "type": ""},
            {"iso_3166_1": "US", "title": "Attack on Titan", "type": ""},
            {"iso_3166_1": "DE", "title": "Angriff auf Titan", "type": ""},
        ]
    }
    result = _extract_tmdb_aliases(raw, "Attack on Titan")
    assert "進撃の巨人" in result
    # US title matches canonical — should be excluded
    assert "attack on titan" not in result
    # DE not a priority country and not a transliteration
    assert "angriff auf titan" not in result


def test_extract_includes_transliteration_types() -> None:
    raw = {
        "results": [
            {"iso_3166_1": "XX", "title": "Shingeki no Kyojin", "type": "Romaji"},
        ]
    }
    result = _extract_tmdb_aliases(raw, "Attack on Titan")
    assert "shingeki no kyojin" in result


def test_extract_deduplicates() -> None:
    raw = {
        "results": [
            {"iso_3166_1": "US", "title": "Some Title", "type": ""},
            {"iso_3166_1": "GB", "title": "Some Title", "type": ""},
        ]
    }
    result = _extract_tmdb_aliases(raw, "Other Title")
    assert result.count("some title") == 1


def test_extract_handles_movie_titles_key() -> None:
    raw = {
        "titles": [
            {"iso_3166_1": "JP", "title": "千と千尋の神隠し", "type": ""},
        ]
    }
    result = _extract_tmdb_aliases(raw, "Spirited Away")
    assert "千と千尋の神隠し" in result


def test_extract_skips_empty_titles() -> None:
    raw = {"results": [{"iso_3166_1": "JP", "title": "", "type": ""}]}
    result = _extract_tmdb_aliases(raw, "Some Show")
    assert result == []


# ---------------------------------------------------------------------------
# _build_flat_aliases
# ---------------------------------------------------------------------------


def test_build_flat_deduplicates_across_sources() -> None:
    sources = {"tmdb": ["aot", "snk"], "llm": ["snk", "aot_s4"], "user": ["my alias"]}
    result = _build_flat_aliases(sources)
    assert result == ["aot", "snk", "aot_s4", "my alias"]


def test_build_flat_returns_none_when_empty() -> None:
    assert _build_flat_aliases({"tmdb": [], "llm": [], "user": []}) is None


# ---------------------------------------------------------------------------
# generate_aliases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_aliases_no_llm() -> None:
    show = _make_show()
    tmdb = _make_tmdb({"results": [{"iso_3166_1": "JP", "title": "進撃の巨人", "type": ""}]})

    await generate_aliases(show, tmdb, llm=None)

    assert show.aliases_sources == {"tmdb": ["進撃の巨人"], "llm": [], "user": []}
    assert show.aliases == ["進撃の巨人"]


@pytest.mark.asyncio
async def test_generate_aliases_with_llm() -> None:
    show = _make_show()
    tmdb = _make_tmdb({"results": [{"iso_3166_1": "JP", "title": "進撃の巨人", "type": ""}]})
    llm = _make_llm('["aot", "shingeki no kyojin"]')

    await generate_aliases(show, tmdb, llm=llm)

    assert show.aliases_sources["tmdb"] == ["進撃の巨人"]
    assert show.aliases_sources["llm"] == ["aot", "shingeki no kyojin"]
    assert "進撃の巨人" in (show.aliases or [])
    assert "aot" in (show.aliases or [])


@pytest.mark.asyncio
async def test_generate_aliases_preserves_user_aliases() -> None:
    show = _make_show(
        aliases_sources={"tmdb": ["old tmdb"], "llm": [], "user": ["my custom alias"]}
    )
    tmdb = _make_tmdb({"results": [{"iso_3166_1": "JP", "title": "新タイトル", "type": ""}]})

    await generate_aliases(show, tmdb, llm=None)

    # TMDB refreshed, user preserved
    assert show.aliases_sources["tmdb"] == ["新タイトル"]
    assert show.aliases_sources["user"] == ["my custom alias"]
    assert "my custom alias" in (show.aliases or [])


@pytest.mark.asyncio
async def test_generate_aliases_tmdb_failure_keeps_existing() -> None:
    show = _make_show(
        aliases=["old alias"],
        aliases_sources={"tmdb": ["old alias"], "llm": [], "user": []},
    )
    tmdb = MagicMock()
    tmdb.get_alternative_titles = AsyncMock(side_effect=RuntimeError("TMDB down"))

    await generate_aliases(show, tmdb, llm=None)

    # Empty TMDB response → tmdb source cleared, flat aliases cleared too
    assert show.aliases_sources["tmdb"] == []
    # User aliases still empty → flat result is None
    assert show.aliases is None


@pytest.mark.asyncio
async def test_generate_aliases_llm_invalid_json_falls_back_to_empty() -> None:
    show = _make_show()
    tmdb = _make_tmdb({"results": []})
    llm = _make_llm("not valid json at all")

    await generate_aliases(show, tmdb, llm=llm)

    assert show.aliases_sources["llm"] == []


@pytest.mark.asyncio
async def test_generate_aliases_llm_unavailable_skips() -> None:
    show = _make_show()
    tmdb = _make_tmdb({"results": []})
    llm = MagicMock()
    llm.is_available.return_value = False

    await generate_aliases(show, tmdb, llm=llm)

    llm.complete.assert_not_called()
    assert show.aliases_sources["llm"] == []
