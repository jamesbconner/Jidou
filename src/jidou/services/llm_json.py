"""Parse a possibly markdown-fenced JSON response from an LLM."""

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
