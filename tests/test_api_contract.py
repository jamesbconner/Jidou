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
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
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


def test_literal_routes_are_not_shadowed() -> None:
    """Every literal (parameter-free) route is the first full match for its own path."""
    api_routes = [r for r in app.routes if isinstance(r, APIRoute)]
    for route in api_routes:
        if "{" in route.path:
            continue
        for method in route.methods:
            scope = {"type": "http", "path": route.path, "method": method, "root_path": ""}
            first = next(r for r in api_routes if r.matches(scope)[0] == Match.FULL)
            assert first is route, f"{method} {route.path} is shadowed by {first.path}"


_API_DIR = Path(__file__).parent.parent / "src" / "jidou" / "api"

# Ratchet: lower this whenever a refactor reduces the worst offender; never raise it.
# Current worst: files.py patch_file (16).
_API_MAX_COMPLEXITY = 16


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
