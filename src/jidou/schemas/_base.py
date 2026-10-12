"""Shared base class and annotated types for Pydantic schemas."""

import re
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

# TMDB media types the API accepts on request bodies; anything else is a 422.
MediaType = Literal["tv", "movie"]


class ORMModel(BaseModel):
    """Base for schemas that may be built from SQLAlchemy rows or other attribute objects.

    ``from_attributes=True`` lets ``model_validate(row)`` read attributes instead of
    requiring a ``dict``. It is a validation-time setting only, so it never appears in
    the generated JSON schema.
    """

    model_config = ConfigDict(from_attributes=True)


class _TmdbObject(BaseModel):
    """Base for a raw TMDB JSON object stored verbatim and echoed back by the API.

    Subclasses declare the keys the app knows about, so they are validated and
    appear in the OpenAPI document, while ``extra="allow"`` keeps every other
    TMDB key. Every declared field is optional: stored objects come from TMDB,
    DB imports and ``POST /shows`` payloads, so no key is guaranteed.

    Serialization returns the object exactly as it was received -- same keys,
    same order, same values. A plain pydantic dump would instead add
    ``"key": null`` for each absent declared field and move declared fields
    ahead of extras, changing bytes the API has always returned. Treat
    instances as read-only: the received mapping, not the attributes, is what
    gets serialized.
    """

    model_config = ConfigDict(extra="allow")

    # The mapping this instance was validated from; None when built without one
    # (e.g. ``model_construct``), in which case the normal dump is used.
    _received: dict[str, Any] | None = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def _remember_received(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
        """Validate *data* and keep a shallow copy of it for serialization."""
        instance = handler(data)
        if isinstance(data, dict):
            instance._received = dict(data)
        return instance

    # No return annotation on purpose: pydantic would turn it into the
    # serialization JSON schema (a bare ``object``) and the OpenAPI document
    # would lose the declared fields. Without it, the model's own schema is used.
    @model_serializer(mode="wrap")
    def _serialize_as_received(self, handler: SerializerFunctionWrapHandler):  # type: ignore[no-untyped-def]
        """Return the received mapping unchanged, or the normal dump if there is none."""
        if self._received is None:
            return handler(self)
        return self._received


class TmdbGenre(_TmdbObject):
    """A TMDB genre object, e.g. ``{"id": 16, "name": "Animation"}``."""

    id: int | None = None
    name: str | None = None


class TmdbNetwork(_TmdbObject):
    """A TMDB network object (TV broadcaster or streaming service)."""

    id: int | None = None
    name: str | None = None
    logo_path: str | None = None
    origin_country: str | None = None


class TmdbEpisodeRef(_TmdbObject):
    """A TMDB ``last_episode_to_air`` / ``next_episode_to_air`` episode summary."""

    id: int | None = None
    name: str | None = None
    overview: str | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    air_date: str | None = None
    episode_number: int | None = None
    episode_type: str | None = None
    production_code: str | None = None
    runtime: int | None = None
    season_number: int | None = None
    show_id: int | None = None
    still_path: str | None = None


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
