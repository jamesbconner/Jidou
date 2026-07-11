"""Parse a possibly markdown-fenced JSON response from an LLM, and sanitize text going into one."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Some providers wrap structured output in a markdown code fence despite an
# explicit response_format / system prompt instructing them not to. The
# language tag may be absent, lowercase, uppercase, or mixed case, and the
# fence may not be the very first/last line if the model adds stray
# whitespace, so both ends are matched with MULTILINE rather than assuming
# the fence is anchored to the whole string.
_LEADING_FENCE = re.compile(r"^```[a-zA-Z0-9]*\s*", re.MULTILINE)
_TRAILING_FENCE = re.compile(r"```\s*$", re.MULTILINE)

_DEFAULT_SANITIZE_MAX_LEN = 200

# Strips control characters (including NUL) and backticks, which could
# otherwise be used to break out of a prompt's intended structure (e.g.
# closing a markdown code fence early, or injecting characters a provider's
# tokenizer treats specially).
_UNSAFE_PROMPT_CHARS = re.compile(r"[\x00-\x1f\x7f`]")


def sanitize_for_prompt(text: str, *, max_len: int = _DEFAULT_SANITIZE_MAX_LEN) -> str:
    """Return *text* safe for interpolation into an LLM prompt.

    Removes control characters and backticks, collapses internal whitespace,
    and truncates to *max_len* characters. This is prompt-injection hygiene,
    not a security boundary on its own — callers still validate/constrain
    whatever the LLM returns (response_format schemas, index bounds, etc.)
    rather than trusting the model's output directly.

    Args:
        text: Untrusted text (filename, show title, directory name, etc.)
            to interpolate into a prompt.
        max_len: Maximum length of the returned string.

    Returns:
        The sanitized, truncated text.
    """
    cleaned = _UNSAFE_PROMPT_CHARS.sub("", text)
    collapsed = " ".join(cleaned.split())
    return collapsed[:max_len]


def parse_llm_json(content: str) -> dict[str, Any] | list[Any] | None:
    """Parse an LLM response as JSON, stripping markdown code fences first.

    Deliberately minimal: this only handles fence-stripping and JSON
    decoding. Callers are responsible for validating the resulting shape
    (dict vs. list, required keys, field types) since expected shapes
    differ per caller.

    Args:
        content: Raw LLM response text (e.g. ``response.content``).

    Returns:
        The parsed JSON value, or None if *content* is not valid JSON
        after fence-stripping.
    """
    text = content.strip()
    text = _LEADING_FENCE.sub("", text)
    text = _TRAILING_FENCE.sub("", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Failed to parse LLM response as JSON: %r", text)
        return None

    if isinstance(parsed, (dict, list)):
        return parsed
    logger.debug("LLM response parsed to a non-object/array JSON scalar: %r", parsed)
    return None
