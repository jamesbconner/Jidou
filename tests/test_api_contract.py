"""Contract guards for the HTTP API surface.

These tests freeze the externally observable API so internal refactors can be
verified as behavior-preserving:

* ``test_openapi_contract_unchanged`` compares the normalized OpenAPI document
  against ``tests/fixtures/openapi_snapshot.json``.
* ``test_literal_routes_are_not_shadowed`` asserts that every literal route path
  resolves to its own handler (route registration order matters in Starlette).

Regenerate the snapshot only for an *intentional* API change:
``JIDOU_UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_api_contract.py``.
"""

import copy
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, _IncludedRouter
from starlette.routing import Match

from jidou.main import app

_SNAPSHOT = Path(__file__).parent / "fixtures" / "openapi_snapshot.json"


def _normalized_openapi() -> dict[str, Any]:
    """Return the app's OpenAPI document with volatile fields removed.

    The app version is dropped because every PR bumps it, and operation
    parameters are sorted by ``(in, name)`` because moving a lookup into a
    helper must not register as a contract change.
    """
    spec: dict[str, Any] = copy.deepcopy(app.openapi())
    spec.get("info", {}).pop("version", None)
    for path_item in spec.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "parameters" in operation:
                operation["parameters"] = sorted(
                    operation["parameters"], key=lambda p: (p["in"], p["name"])
                )
    # Round-trip through JSON so tuples/lists compare equal to the stored file.
    return json.loads(json.dumps(spec, sort_keys=True))


def test_openapi_contract_unchanged() -> None:
    """The OpenAPI document matches the committed snapshot."""
    current = _normalized_openapi()
    if os.environ.get("JIDOU_UPDATE_OPENAPI_SNAPSHOT") == "1":
        _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", "utf-8")
        pytest.skip("OpenAPI snapshot regenerated")
    expected = json.loads(_SNAPSHOT.read_text("utf-8"))
    assert current == expected, (
        "OpenAPI contract changed. If intentional, regenerate with "
        "JIDOU_UPDATE_OPENAPI_SNAPSHOT=1 and justify it in the PR."
    )


@dataclass(frozen=True)
class _ServedRoute:
    """One HTTP operation the app serves, in the position the router tries it."""

    path: str  # Full mounted path, including every include_router prefix.
    methods: frozenset[str]
    endpoint: Callable[..., Any]
    matches: Callable[[dict[str, Any]], tuple[Match, dict[str, Any]]]


def _served_routes(application: FastAPI) -> list[_ServedRoute]:
    """Collect every ``APIRoute`` the app serves, in real dispatch order.

    FastAPI 0.142 no longer flattens ``include_router`` into ``app.routes``:
    included routers appear as opaque ``_IncludedRouter`` entries, so a naive
    ``isinstance(r, APIRoute)`` filter finds nothing (and a guard built on it is
    vacuous). ``_IncludedRouter.effective_route_contexts()`` yields the routes
    in match order with the prefix-resolved ``path``, which is what dispatch
    uses. This depends on a private FastAPI API; the non-empty/coverage
    assertions in the tests fail loudly if it changes shape.

    Args:
        application: The FastAPI app to inspect.

    Returns:
        Served API routes in the order the router tries them.
    """
    served: list[_ServedRoute] = []
    for route in application.routes:
        if isinstance(route, APIRoute):  # registered directly on the app
            served.append(
                _ServedRoute(route.path, frozenset(route.methods), route.endpoint, route.matches)
            )
        elif isinstance(route, _IncludedRouter):
            for ctx in route.effective_route_contexts():
                if isinstance(ctx.original_route, APIRoute) and ctx.endpoint is not None:
                    served.append(
                        _ServedRoute(ctx.path, frozenset(ctx.methods), ctx.endpoint, ctx.matches)
                    )
    return served


def _find_shadowed_literal_routes(routes: list[_ServedRoute]) -> list[str]:
    """Report literal routes whose own path+method dispatches to another endpoint.

    Starlette-style routers pick the first route that fully matches, so a
    parameterized route (``/shows/{id}``) registered before a literal one
    (``/shows/search``) swallows its requests.

    Args:
        routes: Served routes in dispatch order, from ``_served_routes``.

    Returns:
        One human-readable message per shadowed ``(method, path)``; empty if none.
    """
    problems: list[str] = []
    for route in routes:
        if "{" in route.path:
            continue
        for method in sorted(route.methods):
            scope: dict[str, Any] = {
                "type": "http",
                "path": route.path,
                "method": method,
                "root_path": "",
            }
            first = next((r for r in routes if r.matches(scope)[0] == Match.FULL), None)
            if first is None or first.endpoint is not route.endpoint:
                winner = first.path if first else "nothing"
                problems.append(f"{method} {route.path} is dispatched to {winner}")
    return problems


def test_literal_routes_are_not_shadowed() -> None:
    """Every literal route of the real app dispatches to its own endpoint."""
    routes = _served_routes(app)
    operations = sum(len(item) for item in _normalized_openapi()["paths"].values())
    # Guard against going vacuous again: we must see at least every documented operation.
    assert routes, "no APIRoute collected; route introspection is broken"
    assert sum(len(r.methods) for r in routes) >= operations
    assert _find_shadowed_literal_routes(routes) == []


def test_shadowing_guard_detects_shadowed_route() -> None:
    """The helper flags a literal route registered after a parameterized one."""
    router = APIRouter()

    @router.get("/items/{item_id}")
    def get_item(item_id: str) -> str:
        return item_id

    @router.get("/items/special")
    def get_special() -> str:
        return "special"

    throwaway = FastAPI()
    throwaway.include_router(router, prefix="/api")

    routes = _served_routes(throwaway)
    assert len(routes) == 2
    assert _find_shadowed_literal_routes(routes) == [
        "GET /api/items/special is dispatched to /api/items/{item_id}"
    ]


_API_DIR = Path(__file__).parent.parent / "src" / "jidou" / "api"

# Ratchet: lower this whenever a refactor reduces the worst offender; never raise it.
# Current worst: shows.py get_similar_shows (11), settings.py update_settings (11).
_API_MAX_COMPLEXITY = 11


def test_api_cyclomatic_complexity_ratchet() -> None:
    """No function under src/jidou/api exceeds the ratcheted McCabe complexity."""
    result = subprocess.run(  # fixed argv, no shell (S rules are not enabled; no noqa)
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            str(_API_DIR),
            "--select",
            "C901",
            "--config",
            f"lint.mccabe.max-complexity={_API_MAX_COMPLEXITY}",
            "--output-format",
            "concise",
            "--no-cache",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
