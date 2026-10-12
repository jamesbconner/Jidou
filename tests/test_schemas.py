"""Guards for shared schema building blocks (``jidou.schemas._base``)."""

import inspect
from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from jidou.schemas import rss_schema
from jidou.schemas.rss_schema import (
    FeedAddShowRequest,
    FeedRegexTestRequest,
    RegexHintSample,
    RssFeedCreate,
    RssFeedUpdate,
    RssSubscriptionCreate,
    RssSubscriptionUpdate,
)

# (model, field, other required fields) for every regex-validated input field.
_REGEX_FIELDS: list[tuple[type[BaseModel], str, dict[str, Any]]] = [
    (RegexHintSample, "hint", {}),
    (RssFeedCreate, "regex_exclude_hint", {"name": "n", "url": "http://x"}),
    (RssFeedUpdate, "regex_exclude_hint", {}),
    (RssSubscriptionCreate, "regex_include", {"name": "n"}),
    (RssSubscriptionCreate, "regex_exclude", {"name": "n"}),
    (RssSubscriptionUpdate, "regex_include", {}),
    (RssSubscriptionUpdate, "regex_exclude", {}),
    (FeedRegexTestRequest, "regex_include", {"parsed_name": "p"}),
    (FeedRegexTestRequest, "regex_exclude", {"parsed_name": "p"}),
    (FeedAddShowRequest, "regex_include", {"parsed_name": "p", "show_id": 1}),
    (FeedAddShowRequest, "regex_exclude", {"parsed_name": "p", "show_id": 1}),
]

# Response-only models keep plain ``str`` regex fields: they echo stored data.
_RESPONSE_MODELS = (
    rss_schema.RssFeedRead,
    rss_schema.RssSubscriptionRead,
    rss_schema.RssRegexSuggestion,
)


@pytest.mark.parametrize(
    ("model", "field", "required"),
    _REGEX_FIELDS,
    ids=[f"{m.__name__}.{f}" for m, f, _ in _REGEX_FIELDS],
)
def test_invalid_regex_error_shape_unchanged(
    model: type[BaseModel], field: str, required: dict[str, Any]
) -> None:
    """An uncompilable pattern is rejected with the same error shape as before."""
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate({**required, field: "("})

    first = exc_info.value.errors()[0]
    assert first["type"] == "value_error"
    assert first["loc"][-1] == field
    assert first["msg"].startswith("Value error, Invalid regular expression:")


def _has_regex_validator(info: FieldInfo) -> bool:
    """Return True if *info* carries the shared ``_validate_regex`` AfterValidator."""
    from jidou.schemas._base import _validate_regex

    def carries(metadata: tuple[object, ...] | list[object]) -> bool:
        return any(getattr(m, "func", None) is _validate_regex for m in metadata)

    if carries(info.metadata):
        return True
    # ``RegexPattern | None`` keeps the validator inside the union member, and
    # ``Annotated[RegexPattern, Field(...)]`` flattens into field metadata.
    return any(carries(getattr(arg, "__metadata__", ())) for arg in get_args(info.annotation))


def test_every_regex_field_uses_regex_pattern() -> None:
    """Every input ``regex_*``/``hint`` field in rss_schema is typed ``RegexPattern``."""
    checked = 0
    for _, model in inspect.getmembers(rss_schema, inspect.isclass):
        if not issubclass(model, BaseModel) or model.__module__ != rss_schema.__name__:
            continue
        if issubclass(model, _RESPONSE_MODELS):
            continue
        for name, info in model.model_fields.items():
            is_pattern = name == "hint" or (
                name.startswith("regex_")
                and not name.endswith("ignorecase")
                and name != "regex_include_samples"
            )
            if is_pattern:
                checked += 1
                assert _has_regex_validator(info), f"{model.__name__}.{name}"
    # Guard against silently iterating nothing.
    assert checked >= len(_REGEX_FIELDS)
