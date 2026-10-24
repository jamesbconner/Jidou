"""Request bodies reject unknown fields (decision D4).

Every JSON request body the API accepts is discovered from the OpenAPI
document, so a new route with a body is covered automatically: the test fails
until a minimal valid body for its schema is added to ``_MINIMAL_BODIES``.

Each route is sent its minimal valid body plus one unknown field and must
answer 422 with exactly one ``extra_forbidden`` error for that field. The DB
session is replaced by one that fails on any use, so a route that still
accepted the body (and reached its handler) shows up as a 500, not as a write.
"""

import copy
import importlib
import pkgutil
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import jidou.schemas
from jidou.database import get_session
from jidou.main import app
from jidou.schemas.rss_schema import RssFeedRead

_UNKNOWN = "df20_unknown_field"

# Minimal valid body per request-body schema (the array routes' item schema
# for list bodies). Keys must match the discovered schemas exactly.
_MINIMAL_BODIES: dict[str, dict[str, Any]] = {
    "AppSettingsPatch": {},
    "AssignImportRequest": {"filename": "Show.S01E01.mkv"},
    "BulkWatchedRequest": {},
    "FeedAddShowRequest": {"parsed_name": "Show", "show_id": 1},
    "FeedRegexSuggestRequest": {"parsed_name": "Show"},
    "FeedRegexTestRequest": {"parsed_name": "Show"},
    "FileMatchRequest": {},
    "FilePatch": {},
    "LinkFileRequest": {"path": "show/Show.S01E01.mkv"},
    "LinkMovieFileRequest": {"path": "movie/Movie.mkv"},
    "OrphanResolveRequest": {"episode_id": 1},
    "RematchRequest": {"tmdb_id": 1},
    "RssFeedCreate": {"name": "Feed", "url": "https://example.invalid/rss"},
    "RssFeedUpdate": {},
    "RssRegexSuggestRequest": {},
    "RssSubscriptionBulkPatchItem": {"id": 1, "active": True},
    "RssSubscriptionCreate": {"name": "Sub"},
    "RssSubscriptionUpdate": {},
    "ShowAliasesUpdate": {},
    "ShowSeasonAliasesUpdate": {},
    "ShowCreate": {"tmdb_id": 1, "title": "Show"},
    "ShowPatch": {},
    "ShowPaths": {},
    "TaskTrigger": {"task_type": "scan"},
    "VerifyPathsRequest": {"paths": []},
    "WatchlistCreate": {"show_id": 1},
    "WatchlistPositionItem": {"id": 1, "position": 1},
    "WatchlistUpdate": {},
}

# Multipart uploads: FastAPI builds these schemas from individual Form/File
# parameters, so there is no pydantic model to forbid extras on (ruling R2).
_NON_JSON_BODIES = {
    ("POST", "/api/import/text"),
    ("POST", "/api/import/database"),
}

# Nested request-only object schemas, reached through a property of a body
# schema: (body schema, property, minimal nested value, whether it is a list).
_NESTED_CASES: dict[tuple[str, str], tuple[dict[str, Any], bool]] = {
    ("FeedAddShowRequest", "show"): ({"tmdb_id": 1, "title": "Show"}, False),
    ("RssFeedCreate", "regex_include_samples"): ({"hint": "Show"}, True),
    ("RssFeedUpdate", "regex_include_samples"): ({"hint": "Show"}, True),
}

# Smallest number of JSON request-body routes the API has had since D4; the
# discovery must never silently shrink to nothing.
_MIN_JSON_BODY_ROUTES = 28


def _ref_name(schema: dict[str, Any]) -> str | None:
    """Return the component name a schema references, unwrapping ``anyOf`` null."""
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    for option in schema.get("anyOf", []):
        name = _ref_name(option)
        if name is not None:
            return name
    return None


def _discover_body_routes() -> tuple[list[tuple[str, str, str, bool]], set[tuple[str, str]]]:
    """List JSON request-body operations and the non-JSON ones from OpenAPI.

    Returns:
        ``(json_routes, other_routes)`` where each JSON route is
        ``(method, path, schema_name, is_list_body)``.
    """
    json_routes: list[tuple[str, str, str, bool]] = []
    other_routes: set[tuple[str, str]] = set()
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            content = operation.get("requestBody", {}).get("content", {})
            if not content:
                continue
            if "application/json" not in content:
                other_routes.add((method.upper(), path))
                continue
            schema = content["application/json"]["schema"]
            is_list = schema.get("type") == "array"
            name = _ref_name(schema["items"] if is_list else schema)
            assert name is not None, f"{method.upper()} {path} has an inline body schema"
            json_routes.append((method.upper(), path, name, is_list))
    return json_routes, other_routes


_JSON_BODY_ROUTES, _OTHER_BODY_ROUTES = _discover_body_routes()


def _component_schema(name: str) -> dict[str, Any]:
    """Return one ``components.schemas`` entry of the OpenAPI document."""
    schema: dict[str, Any] = app.openapi()["components"]["schemas"][name]
    return schema


def _concrete_path(path: str) -> str:
    """Fill every ``{param}`` of an OpenAPI path with ``1``."""
    return re.sub(r"\{[^}]+\}", "1", path)


def _schema_model(name: str) -> type[BaseModel]:
    """Return the ``jidou.schemas`` model class named *name*."""
    for module_info in pkgutil.iter_modules(jidou.schemas.__path__):
        module = importlib.import_module(f"jidou.schemas.{module_info.name}")
        model = getattr(module, name, None)
        if isinstance(model, type) and issubclass(model, BaseModel):
            return model
    raise AssertionError(f"no jidou.schemas model named {name}")


class _UnusableSession:
    """DB session stand-in that fails on any use, so no handler can write."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"request handler touched the DB session ({name})")


async def _unusable_session() -> AsyncGenerator[_UnusableSession]:
    """Dependency override yielding :class:`_UnusableSession`."""
    yield _UnusableSession()


@pytest.fixture
def client() -> Any:
    """TestClient whose DB session fails on use; server errors become 500s."""
    app.dependency_overrides[get_session] = _unusable_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)


def _assert_single_extra_forbidden(response: Any, loc: list[Any]) -> None:
    """Assert *response* is a 422 holding exactly one ``extra_forbidden`` at *loc*."""
    assert response.status_code == 422, (
        f"expected 422 extra_forbidden, got {response.status_code}: {response.text[:300]}"
    )
    errors = response.json()["detail"]
    assert [(e["type"], e["loc"]) for e in errors] == [("extra_forbidden", loc)], errors


def test_discovery_is_complete() -> None:
    """Every JSON body schema has a minimal body; non-JSON bodies are the known uploads."""
    assert len(_JSON_BODY_ROUTES) >= _MIN_JSON_BODY_ROUTES
    assert {name for _, _, name, _ in _JSON_BODY_ROUTES} == set(_MINIMAL_BODIES)
    assert _OTHER_BODY_ROUTES == _NON_JSON_BODIES


@pytest.mark.parametrize(
    ("method", "path", "schema_name", "is_list"),
    _JSON_BODY_ROUTES,
    ids=[f"{m} {p}" for m, p, _, _ in _JSON_BODY_ROUTES],
)
def test_minimal_body_is_valid(method: str, path: str, schema_name: str, is_list: bool) -> None:
    """The minimal body alone passes its schema's validation (incl. model validators)."""
    _schema_model(schema_name).model_validate(_MINIMAL_BODIES[schema_name])


@pytest.mark.parametrize(
    ("method", "path", "schema_name", "is_list"),
    _JSON_BODY_ROUTES,
    ids=[f"{m} {p}" for m, p, _, _ in _JSON_BODY_ROUTES],
)
def test_request_body_rejects_unknown_field(
    client: TestClient, method: str, path: str, schema_name: str, is_list: bool
) -> None:
    """A minimal valid body plus one unknown field is a 422 ``extra_forbidden``."""
    item = {**copy.deepcopy(_MINIMAL_BODIES[schema_name]), _UNKNOWN: 1}
    body: Any = [item] if is_list else item
    response = client.request(method, _concrete_path(path), json=body)
    loc: list[Any] = ["body", 0, _UNKNOWN] if is_list else ["body", _UNKNOWN]
    _assert_single_extra_forbidden(response, loc)


def test_nested_cases_cover_every_nested_object_schema() -> None:
    """Every object schema nested in a request body has a nested case."""
    found: set[tuple[str, str]] = set()
    for name in {schema_name for _, _, schema_name, _ in _JSON_BODY_ROUTES}:
        for prop, prop_schema in _component_schema(name).get("properties", {}).items():
            items = prop_schema
            for option in prop_schema.get("anyOf", [prop_schema]):
                if option.get("type") == "array":
                    items = option["items"]
            nested = _ref_name(items)
            if nested is not None and _component_schema(nested).get("type") == "object":
                found.add((name, prop))
    assert found, "no nested request objects discovered"
    assert found == set(_NESTED_CASES)


@pytest.mark.parametrize(
    ("schema_name", "prop"), list(_NESTED_CASES), ids=[f"{s}.{p}" for s, p in _NESTED_CASES]
)
def test_nested_request_object_rejects_unknown_field(
    client: TestClient, schema_name: str, prop: str
) -> None:
    """An unknown field inside a nested request object is also rejected."""
    nested_minimal, is_list = _NESTED_CASES[(schema_name, prop)]
    nested = {**copy.deepcopy(nested_minimal), _UNKNOWN: 1}
    body = {**copy.deepcopy(_MINIMAL_BODIES[schema_name]), prop: [nested] if is_list else nested}
    if schema_name == "FeedAddShowRequest":
        body.pop("show_id")  # exactly one of show_id / show
    method, path = next((m, p) for m, p, s, _ in _JSON_BODY_ROUTES if s == schema_name)
    response = client.request(method, _concrete_path(path), json=body)
    loc: list[Any] = ["body", prop, 0, _UNKNOWN] if is_list else ["body", prop, _UNKNOWN]
    _assert_single_extra_forbidden(response, loc)


def _collect_refs(node: Any, found: set[str]) -> None:
    """Add every component name referenced anywhere under *node* to *found*."""
    if isinstance(node, dict):
        if "$ref" in node:
            found.add(str(node["$ref"]).rsplit("/", 1)[-1])
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_refs(value, found)


def _response_schema_names() -> set[str]:
    """Names of every component schema reachable from an operation's responses."""
    pending: set[str] = set()
    for operations in app.openapi()["paths"].values():
        for operation in operations.values():
            _collect_refs(operation.get("responses", {}), pending)
    reached: set[str] = set()
    while pending:
        name = pending.pop()
        reached.add(name)
        nested: set[str] = set()
        _collect_refs(_component_schema(name), nested)
        pending |= nested - reached
    return reached


def test_response_schemas_do_not_forbid_extras() -> None:
    """D4 covers request bodies only: no response schema gets ``additionalProperties: false``."""
    names = _response_schema_names()
    assert len(names) >= 40
    forbidding = sorted(
        n for n in names if _component_schema(n).get("additionalProperties") is False
    )
    assert forbidding == []


def test_feed_read_still_accepts_stored_sample_with_extra_key() -> None:
    """``RssFeedRead`` is built from stored JSONB; an extra stored key must not fail it."""
    now = datetime.now(UTC)
    feed = RssFeedRead.model_validate(
        {
            "id": 1,
            "remote_key": None,
            "name": "Feed",
            "url": "https://example.invalid/rss",
            "default_download_location": None,
            "default_move_completed": None,
            "active": True,
            "regex_include_samples": [{"sample_name": "S", "hint": "S", "legacy": 1}],
            "regex_exclude_hint": None,
            "extra_config": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert feed.regex_include_samples is not None
    assert feed.regex_include_samples[0].hint == "S"
