"""Guards for shared schema building blocks (``jidou.schemas._base``)."""

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from jidou import workers as workers_pkg
from jidou.models.task import TaskStatus
from jidou.schemas import rss_schema
from jidou.schemas._base import ORMModel
from jidou.schemas.rss_schema import (
    FeedAddShowRequest,
    FeedRegexTestRequest,
    RegexHintSample,
    RssFeedCreate,
    RssFeedUpdate,
    RssSubscriptionCreate,
    RssSubscriptionUpdate,
)
from jidou.schemas.settings_schema import AppSettingsPatch, AppSettingsRead
from jidou.schemas.show_schema import ShowPatch
from jidou.schemas.task_schema import TaskList, TaskTrigger, TaskType

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


_LENGTH_CAPPED_FIELDS = [
    (model, field, required)
    for model, field, required in _REGEX_FIELDS
    if model in (FeedRegexTestRequest, FeedAddShowRequest)
]


@pytest.mark.parametrize(
    ("model", "field", "required"),
    _LENGTH_CAPPED_FIELDS,
    ids=[f"{m.__name__}.{f}" for m, f, _ in _LENGTH_CAPPED_FIELDS],
)
@pytest.mark.parametrize(
    "value",
    ["a" * 513, "(" + "a" * 600],
    ids=["valid-too-long", "invalid-too-long"],
)
def test_length_cap_runs_before_regex_check(
    model: type[BaseModel], field: str, required: dict[str, Any], value: str
) -> None:
    """Over-length patterns fail on length (as before), never on regex compilation."""
    assert len(_LENGTH_CAPPED_FIELDS) == 4
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate({**required, field: value})

    first = exc_info.value.errors()[0]
    assert first["type"] == "string_too_long"
    assert first["loc"][-1] == field


def test_empty_hint_fails_on_length_not_item_count() -> None:
    """An empty hint keeps the plain-string ``string_too_short`` error type."""
    with pytest.raises(ValidationError) as exc_info:
        RegexHintSample.model_validate({"hint": ""})

    first = exc_info.value.errors()[0]
    assert first["type"] == "string_too_short"
    assert first["loc"] == ("hint",)


# --- Characterization: behaviour that the ORMModel/constants refactor must not change ---


def test_task_trigger_validation_is_stable() -> None:
    """TaskTrigger coerces dry_run, ignores extras, and requires task_type."""
    trigger = TaskTrigger.model_validate({"task_type": "scan", "dry_run": "true", "extra": 1})
    assert trigger.task_type == "scan"
    assert trigger.dry_run is True
    assert TaskTrigger(task_type="scan").dry_run is False
    assert not hasattr(trigger, "extra")
    with pytest.raises(ValidationError):
        TaskTrigger.model_validate({})
    with pytest.raises(ValidationError):
        TaskTrigger.model_validate({"task_type": "scan", "dry_run": "maybe"})


def test_show_patch_validation_is_stable() -> None:
    """ShowPatch accepts fields by name, tracks which were set, and ignores extras."""
    patch = ShowPatch.model_validate(
        {"banner_path": None, "track_missing_episodes": False, "bogus": 1}
    )
    assert patch.model_fields_set == {"banner_path", "track_missing_episodes"}
    assert patch.model_dump(exclude_unset=True) == {
        "banner_path": None,
        "track_missing_episodes": False,
    }
    assert not hasattr(patch, "bogus")
    with pytest.raises(ValidationError):
        ShowPatch.model_validate({"content_type": "not-a-content-type"})


@pytest.mark.parametrize(
    ("value", "ok"), [(0, False), (1, True), (12, True), (40, True), (41, False), ("7", True)]
)
def test_similar_titles_count_bounds_are_stable(value: object, ok: bool) -> None:
    """Both settings schemas accept 1..40 inclusive (and coerce numeric strings)."""
    read_kwargs: dict[str, Any] = {
        name: True for name in AppSettingsRead.model_fields if name != "similar_titles_count"
    }
    for build in (
        lambda: AppSettingsPatch.model_validate({"similar_titles_count": value}),
        lambda: AppSettingsRead.model_validate({**read_kwargs, "similar_titles_count": value}),
    ):
        if ok:
            assert build().similar_titles_count == int(str(value))
        else:
            with pytest.raises(ValidationError):
                build()


def test_app_settings_patch_only_set_fields_are_reported() -> None:
    """AppSettingsPatch leaves unsent fields unset so the route can skip them."""
    patch = AppSettingsPatch.model_validate({"discover_enabled": False})
    assert patch.model_dump(exclude_unset=True) == {"discover_enabled": False}


class _OrmRow:
    """Attribute-only stand-in for a SQLAlchemy BackgroundTask row."""

    id = 1
    task_type = "scan"
    status = "running"
    progress_current = 2
    progress_total = 5
    progress_message = None
    result_summary = None
    dry_run = False
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    completed_at = None


def test_orm_models_validate_from_attributes() -> None:
    """Response schemas load from plain attribute objects (from_attributes=True)."""
    task = TaskList.model_validate(_OrmRow())
    assert task.status is TaskStatus.RUNNING
    assert task.task_type == "scan"
    assert task.progress_current == 2


def test_no_schema_redeclares_from_attributes() -> None:
    """from_attributes lives only on ORMModel; schemas inherit it instead of repeating it.

    Scans the source of every schema module, so a new or reverted class that sets
    ``from_attributes`` itself (via ``ConfigDict(...)`` or a config dict) is caught
    even when its merged config would look identical at runtime.
    """
    assert ORMModel.model_config.get("from_attributes") is True
    schema_dir = Path(rss_schema.__file__).parent
    modules = sorted(
        p for p in schema_dir.glob("*.py") if p.name not in {"_base.py", "__init__.py"}
    )
    # Guard against a vacuous pass if the glob ever stops finding the schema modules.
    assert len(modules) >= 10
    offenders: list[str] = []
    for path in modules:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            is_kwarg = isinstance(node, ast.keyword) and node.arg == "from_attributes"
            is_dict_key = isinstance(node, ast.Constant) and node.value == "from_attributes"
            if is_kwarg or is_dict_key:
                offenders.append(f"{path.name}:{getattr(node, 'lineno', '?')}")
    assert offenders == []


def test_task_type_literal_matches_worker_types() -> None:
    """TaskType lists exactly the task_type strings the workers create rows under."""
    workers_dir = Path(workers_pkg.__file__).parent
    found: set[str] = set()
    for path in sorted(workers_dir.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "run_task_workflow"
            ):
                arg = node.args[1]
                assert isinstance(arg, ast.Constant), f"{path.name}: task_type is not a literal"
                found.add(str(arg.value))
    # Eleven worker entry points exist today; a scan that finds far fewer is vacuous.
    assert len(found) >= 10
    assert found == set(get_args(TaskType))
