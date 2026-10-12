"""Shared base class and annotated types for Pydantic schemas."""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# TMDB media types the API accepts on request bodies; anything else is a 422.
MediaType = Literal["tv", "movie"]


class ORMModel(BaseModel):
    """Base for schemas that may be built from SQLAlchemy rows or other attribute objects.

    ``from_attributes=True`` lets ``model_validate(row)`` read attributes instead of
    requiring a ``dict``. It is a validation-time setting only, so it never appears in
    the generated JSON schema.
    """

    model_config = ConfigDict(from_attributes=True)


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


MAX_REGEX_PATTERN_LENGTH = 512

# Length cap first, then compile: Annotated metadata runs in order, so this keeps
# over-length input failing with ``string_too_long`` rather than a regex error.
# (``Annotated[RegexPattern, Field(max_length=...)]`` would run the cap last.)
BoundedRegexPattern = Annotated[
    str, Field(max_length=MAX_REGEX_PATTERN_LENGTH), AfterValidator(_validate_regex)
]

# Non-empty variant for required hints; same ordering rule as above.
NonEmptyRegexPattern = Annotated[str, Field(min_length=1), AfterValidator(_validate_regex)]
