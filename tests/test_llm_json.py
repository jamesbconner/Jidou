"""Tests for jidou.services.llm_json."""

from jidou.services.llm_json import parse_llm_json


def test_parse_llm_json_plain_dict() -> None:
    """Unfenced JSON parses directly."""
    assert parse_llm_json('{"a": 1}') == {"a": 1}


def test_parse_llm_json_plain_list() -> None:
    """A JSON array root parses directly, not just objects."""
    assert parse_llm_json("[1, 2, 3]") == [1, 2, 3]


def test_parse_llm_json_lowercase_fence() -> None:
    """A lowercase ```json fence is stripped from both ends."""
    text = '```json\n{"a": 1}\n```'
    assert parse_llm_json(text) == {"a": 1}


def test_parse_llm_json_uppercase_fence() -> None:
    """An uppercase ```JSON fence is stripped case-insensitively."""
    text = '```JSON\n{"a": 1}\n```'
    assert parse_llm_json(text) == {"a": 1}


def test_parse_llm_json_bare_fence_no_language_tag() -> None:
    """A bare ``` fence with no language tag is still stripped."""
    text = '```\n{"a": 1}\n```'
    assert parse_llm_json(text) == {"a": 1}


def test_parse_llm_json_no_fence() -> None:
    """Content with no code fence at all is parsed as-is."""
    assert parse_llm_json('  {"a": 1}  ') == {"a": 1}


def test_parse_llm_json_invalid_json_returns_none() -> None:
    """Non-JSON content returns None rather than raising."""
    assert parse_llm_json("not json at all") is None


def test_parse_llm_json_invalid_json_inside_fence_returns_none() -> None:
    """Malformed JSON inside a valid fence still returns None."""
    assert parse_llm_json("```json\n{not valid json}\n```") is None


def test_parse_llm_json_empty_string_returns_none() -> None:
    """An empty response returns None rather than raising."""
    assert parse_llm_json("") is None


def test_parse_llm_json_scalar_root_returns_none() -> None:
    """A bare JSON scalar (string/number/bool) at the root returns None.

    No caller expects anything but a dict or list at the root, so this is
    treated the same as any other unparseable response.
    """
    assert parse_llm_json('"just a string"') is None
    assert parse_llm_json("42") is None
    assert parse_llm_json("true") is None
    assert parse_llm_json("null") is None


def test_parse_llm_json_nested_structure_preserved() -> None:
    """Nested objects/arrays inside the parsed value survive intact."""
    text = '{"items": [{"id": 1}, {"id": 2}], "meta": {"count": 2}}'
    assert parse_llm_json(text) == {"items": [{"id": 1}, {"id": 2}], "meta": {"count": 2}}
