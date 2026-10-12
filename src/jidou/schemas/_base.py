"""Shared annotated types for Pydantic schemas."""

import re
from typing import Annotated

from pydantic import AfterValidator


def _validate_regex(value: str) -> str:
    """Compile *value* as a Python regex, raising ValueError if invalid.

    Args:
        value: Candidate regular expression.

    Returns:
        The unchanged pattern when it compiles.

    Raises:
        ValueError: If *value* is not a valid Python regular expression.
    """
    try:
        re.compile(value)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression: {exc}") from exc
    return value


# An AfterValidator runs after Field constraints (min/max length), so length
# errors still win over regex errors, and it adds nothing to the JSON schema.
RegexPattern = Annotated[str, AfterValidator(_validate_regex)]
