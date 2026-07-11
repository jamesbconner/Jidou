"""Tests for jidou.services.filename_parser."""

from jidou.services.filename_parser import (
    _clean_filename,
    _heuristic_parse,
    heuristic_se,
)

# ---------------------------------------------------------------------------
# heuristic_se
# ---------------------------------------------------------------------------


def test_heuristic_se_sxxeyy():
    """S01E02 pattern extracts season=1 episode=2."""
    assert heuristic_se("ShowName.S01E02.1080p.mkv") == (1, 2)


def test_heuristic_se_nxm():
    """NxM pattern extracts season=2 episode=5."""
    assert heuristic_se("ShowName.2x05.1080p.mkv") == (2, 5)


def test_heuristic_se_no_match():
    """Returns None when no S/E pattern is found."""
    assert heuristic_se("Movie.Title.2024.1080p.mkv") is None


def test_heuristic_se_avoids_resolution():
    """1920x1080 resolution string is not mistaken for an episode number."""
    assert heuristic_se("ShowName.1920x1080.mkv") is None


# ---------------------------------------------------------------------------
# _clean_filename
# ---------------------------------------------------------------------------


def test_clean_filename_strips_extension_and_brackets():
    """Extension and bracket tags are removed; delimiters become spaces."""
    cleaned, crc32 = _clean_filename("[HorribleSubs] Attack on Titan - 01 [1080p].mkv")
    assert "HorribleSubs" not in cleaned
    assert "1080p" not in cleaned
    assert ".mkv" not in cleaned
    assert crc32 is None


def test_clean_filename_extracts_crc32():
    """8-char hex tag is returned as uppercase CRC32."""
    _, crc32 = _clean_filename("Show.Name.S01E01.[ABCD1234].mkv")
    assert crc32 == "ABCD1234"


def test_clean_filename_crc32_lowercase_normalised():
    """Lowercase CRC32 is uppercased."""
    _, crc32 = _clean_filename("Show.Name.S01E01.[abcd1234].mkv")
    assert crc32 == "ABCD1234"


def test_clean_filename_no_crc32_returns_none():
    _, crc32 = _clean_filename("Show.Name.S01E01.mkv")
    assert crc32 is None


# ---------------------------------------------------------------------------
# _heuristic_parse
# ---------------------------------------------------------------------------


def test_heuristic_parse_sxxeyy():
    """Standard SxxEyy notation."""
    r = _heuristic_parse("Attack.on.Titan.S01E02.1080p.mkv")
    assert r.show_name == "Attack on Titan"
    assert r.season == 1
    assert r.episode == 2
    assert r.confidence == 0.6
    assert r.llm_ok is False


def test_heuristic_parse_ordinal_season():
    """'2nd Season 04' — common anime release format."""
    r = _heuristic_parse("[Group] My Hero Academia - 2nd Season - 04 [720p].mkv")
    assert r.show_name == "My Hero Academia"
    assert r.season == 2
    assert r.episode == 4


def test_heuristic_parse_bare_episode_with_group_tag():
    """Anime release with group tag, 3-digit episode, and CRC32."""
    r = _heuristic_parse("[HorribleSubs] One Piece - 999 [ABCD1234].mkv")
    assert r.show_name == "One Piece"
    assert r.episode == 999
    assert r.crc32 == "ABCD1234"


def test_heuristic_parse_1000_plus_episode_falls_back():
    """Episode numbers > 999 are not matched — 4-digit numbers are more likely
    years/resolutions and the false-positive cost outweighs the edge case."""
    r = _heuristic_parse("[HorribleSubs] One Piece - 1001 [ABCD1234].mkv")
    assert r.season is None
    assert r.episode is None
    assert r.confidence == 0.1
    assert r.crc32 == "ABCD1234"


def test_heuristic_parse_dot_separated():
    """Dot-separated name with SxxEyy."""
    r = _heuristic_parse("The.Office.S03E07.720p.BluRay.mkv")
    assert r.show_name == "The Office"
    assert r.season == 3
    assert r.episode == 7


def test_heuristic_parse_no_match_returns_cleaned_name():
    """When no pattern matches, full cleaned name is returned at low confidence."""
    r = _heuristic_parse("[SubGroup] SomeTitleWithNoMarker [1080p].mkv")
    assert r.show_name == "SomeTitleWithNoMarker"
    assert r.season is None
    assert r.episode is None
    assert r.confidence == 0.1


def test_heuristic_parse_content_type_always_none():
    """Heuristic parse never infers content_type — that requires LLM or TMDB."""
    r = _heuristic_parse("Some.Movie.2024.1080p.mkv")
    assert r.content_type is None


def test_heuristic_parse_resolution_not_treated_as_episode():
    """720p and 480p are stripped before pattern matching — not parsed as episode."""
    r = _heuristic_parse("Show.Name.S01E05.720p.BluRay.mkv")
    assert r.episode == 5
    assert r.show_name == "Show Name"


def test_heuristic_parse_bare_resolution_not_episode():
    """Bare 3-digit resolution (e.g. 720 without 'p') is stripped, not episode."""
    r = _heuristic_parse("Show.Name.720.mkv")
    assert r.episode is None


def test_heuristic_parse_end_anchor_preferred_over_mid_string():
    """End-anchored pattern wins over mid-string: 'Part 2 - 05' → episode=5."""
    r = _heuristic_parse("Show Part 2 - 05.mkv")
    assert r.episode == 5
    assert r.show_name == "Show Part 2"


# ---------------------------------------------------------------------------
# parse_filename — LLM path (heuristic path already covered above)
# ---------------------------------------------------------------------------


async def test_parse_filename_no_llm_uses_heuristic():
    """Without an LLM, parse_filename falls back to the heuristic parser."""
    from jidou.services.filename_parser import parse_filename

    result = await parse_filename("Attack.on.Titan.S01E02.1080p.mkv", llm=None)
    assert result.show_name == "Attack on Titan"
    assert result.season == 1
    assert result.episode == 2
    assert result.llm_ok is False


async def test_parse_filename_llm_unavailable_uses_heuristic():
    """An LLM that reports unavailable also falls back to the heuristic parser."""
    from unittest.mock import MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = False

    result = await parse_filename("Attack.on.Titan.S01E02.1080p.mkv", llm=llm)
    assert result.llm_ok is False
    llm.complete.assert_not_called()


async def test_parse_filename_llm_success():
    """A successful LLM call returns a fully-populated result with llm_ok=True."""
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = (
        '{"show_name": "Attack on Titan", "season": 1, "episode": 2, '
        '"crc32": null, "content_type": "anime", "confidence": 0.95, '
        '"reasoning": "Clear S01E02 marker."}'
    )
    llm.complete = AsyncMock(return_value=response)

    result = await parse_filename("Attack.on.Titan.S01E02.1080p.mkv", llm=llm)
    assert result.show_name == "Attack on Titan"
    assert result.season == 1
    assert result.episode == 2
    assert result.content_type == "anime"
    assert result.confidence == 0.95
    assert result.llm_ok is True


async def test_parse_filename_llm_sanitizes_filename_in_prompt():
    """A filename with control characters/backticks is sanitized before prompting."""
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = (
        '{"show_name": "Show", "season": 1, "episode": 2, '
        '"crc32": null, "content_type": "tv", "confidence": 0.9, '
        '"reasoning": "ok"}'
    )
    llm.complete = AsyncMock(return_value=response)

    crafted = "Weird`\ninjected\r\x00Name.mkv"
    await parse_filename(crafted, llm=llm)

    prompt = llm.complete.call_args.kwargs["prompt"]
    assert "`" not in prompt
    assert "\n" not in prompt
    assert "\r" not in prompt
    assert "\x00" not in prompt


async def test_parse_filename_llm_none_response_falls_back():
    """llm.complete() returning None falls back to the heuristic parser."""
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)

    result = await parse_filename("Attack.on.Titan.S01E02.1080p.mkv", llm=llm)
    assert result.llm_ok is False
    assert result.show_name == "Attack on Titan"


async def test_parse_filename_llm_invalid_json_falls_back():
    """Malformed JSON from the LLM falls back to the heuristic parser."""
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = "not json at all"
    llm.complete = AsyncMock(return_value=response)

    result = await parse_filename("Attack.on.Titan.S01E02.1080p.mkv", llm=llm)
    assert result.llm_ok is False


async def test_parse_filename_llm_markdown_fence_stripped():
    """JSON wrapped in a markdown code fence is still parsed correctly."""
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = (
        '```json\n{"show_name": "Show", "season": 2, "episode": 3, '
        '"crc32": null, "content_type": "tv", "confidence": 0.9, '
        '"reasoning": "test"}\n```'
    )
    llm.complete = AsyncMock(return_value=response)

    result = await parse_filename("Show.S02E03.mkv", llm=llm)
    assert result.season == 2
    assert result.episode == 3


async def test_parse_filename_llm_non_dict_json_falls_back():
    """A JSON array (or other non-object root) from the LLM falls back to heuristic."""
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = '["not", "an", "object"]'
    llm.complete = AsyncMock(return_value=response)

    result = await parse_filename("Attack.on.Titan.S01E02.1080p.mkv", llm=llm)
    assert result.llm_ok is False
    assert result.season == 1
    assert result.episode == 2


async def test_parse_filename_llm_non_integer_season_falls_back():
    """A non-integer season/episode value from the LLM falls back to heuristic."""
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = (
        '{"show_name": "Attack on Titan", "season": "one", "episode": 2, '
        '"crc32": null, "content_type": "anime", "confidence": 0.95}'
    )
    llm.complete = AsyncMock(return_value=response)

    result = await parse_filename("Attack.on.Titan.S01E02.1080p.mkv", llm=llm)
    assert result.llm_ok is False
    assert result.season == 1
    assert result.episode == 2


async def test_parse_filename_llm_non_numeric_confidence_falls_back():
    """A non-numeric confidence value from the LLM falls back to heuristic.

    Regression test: confidence was previously converted with a bare
    float(...) call outside any guard, so a non-numeric value (more likely
    from providers that don't honor the structured-output schema, e.g.
    Anthropic) would raise uncaught instead of degrading gracefully.
    """
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = (
        '{"show_name": "Attack on Titan", "season": 1, "episode": 2, '
        '"crc32": null, "content_type": "anime", "confidence": "high"}'
    )
    llm.complete = AsyncMock(return_value=response)

    result = await parse_filename("Attack.on.Titan.S01E02.1080p.mkv", llm=llm)
    assert result.llm_ok is False
    assert result.season == 1
    assert result.episode == 2


async def test_parse_filename_sends_regex_hint():
    """The regex anchor is included in the LLM prompt when present."""
    from unittest.mock import AsyncMock, MagicMock

    from jidou.services.filename_parser import parse_filename

    llm = MagicMock()
    llm.is_available.return_value = True
    response = MagicMock()
    response.content = (
        '{"show_name": "Show", "season": 2, "episode": 5, "crc32": null, '
        '"content_type": "tv", "confidence": 0.9, "reasoning": "test"}'
    )
    llm.complete = AsyncMock(return_value=response)

    await parse_filename("Show.Name.S02E05.mkv", llm=llm)

    call_args = llm.complete.call_args
    prompt = call_args.kwargs.get("prompt") or call_args.args[0]
    assert "season=2" in prompt
    assert "episode=5" in prompt
