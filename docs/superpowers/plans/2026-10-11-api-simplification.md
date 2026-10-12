# API Layer Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce duplication and cyclomatic complexity in `src/jidou/api/`
without changing any externally observable behavior: status codes, `detail`
strings, response bodies, OpenAPI schema and route matching all stay the
same.

**Architecture:** Add small, focused helpers at the API boundary
(`api/lookups.py`) and move domain logic out of route handlers into
services (`services/task_dispatch.py`, `services/file_relink.py`,
`services/discover_feed.py`, `services/health_probes.py`). Then split the
two oversized route modules by sub-resource. Before any of that, an OpenAPI
contract snapshot, a route-shadowing check and a complexity ratchet are put
in place, so every later task is checked against them.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 (async), Celery, pytest,
ruff, mypy (strict), uv.

**Spec:** `docs/superpowers/specs/2026-10-11-api-simplification-design.md`. Read it
first. Finding IDs (R1–R9) and hotspot names below refer to it.

> **Status note:** This plan covers the API layer only. It is meant to be
> merged with the plans from the app-wide analysis (services, orchestrators,
> workers, models, schemas, frontend) before execution. Items marked
> **Deferred** in the spec are left for that merged plan. Line numbers were
> correct on 2026-10-11 at commit `da5f022`. Find code by its quoted text,
> not by line number, because earlier tasks shift lines.

## Global Constraints

- **No behavior change.** Every HTTP status code, `detail` string, response
  JSON shape and OpenAPI document stays the same. Task 1's snapshot test
  enforces this, and a snapshot diff fails the task.
- **No backward-compatibility shims.** There are no external clients. When a
  name moves, update every importer and every `patch("…")` target in
  `tests/`. Do not re-export from the old location.
- **Commands:** use `uv` only. Never use `pip` or `python -m venv`.
- **Style:** ruff target `py313`, `line-length = 100`; mypy `strict = true`;
  Google-style docstrings on every public function and class.
- **Pre-push checks, in this order:**
  1. `uv run ruff check .`
  2. `uv run ruff format --check .`
  3. `uv run mypy src/`
  4. `uv run bandit -r src/ -l` (check `.github/workflows/ci.yml` for the
     flag CI actually uses)
  5. `uv run pytest`
- **After code changes:** run `graphify update .`.
- **Git:**
  - Never commit to `main`. Use one branch and one PR per phase, as listed
    in "PR grouping".
  - After each push, poll `gh pr checks` every 60s (at most 10 times) for
    Cursor Bugbot, then address its comments.
  - Work serially: no parallel PRs.
  - Merge with `--merge`.
  - Each PR ends with a version-bump commit following the repo convention
    (see commit `69c7290`: `pyproject.toml`, `src/jidou/__init__.py`,
    `frontend/package.json`, `uv.lock`).
- **PR and commit text:** use generic placeholder paths, not real ones, and
  never include a claude.ai session link.
- **Commit trailer:** end every commit message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Row locks must survive the lookup refactor.** `link_movie_file`
   (`shows.py`), the rss feed delete and the rss subscription delete all use
   `.with_for_update()`. Expected: the converted call still emits
   `SELECT … FOR UPDATE`. Pinned by Task 5,
   `test_get_or_404_for_update_emits_for_update`.
2. **A broken worker module.** For example, an ImportError when a Celery
   task is resolved. Expected after Task 8: the `BackgroundTask` row is
   marked FAILED and the API returns 503, never a 500 with a PENDING row
   left behind. Pinned by Task 8,
   `test_enqueue_celery_task_import_failure_marks_failed`.
3. **A new `AppSettingsPatch` field added without a mapping entry.**
   Expected: the test suite fails, rather than the PATCH silently ignoring
   the field. Pinned by Task 11, `test_patch_field_map_covers_every_field`.
4. **`patch_file` with a changed `show_id` and no `episode_id`.** Expected:
   current behavior is kept exactly. `episode_id` becomes NULL and
   `clear_if_unreferenced` is **not** called (spec §5 notes this as a
   possible bug, to be decided separately). Pinned by Task 9,
   `test_reassign_show_without_episode_does_not_clear_old_tracking`.
5. **Literal routes shadowed by parameterized routes after the file split.**
   For example, `/shows/search` vs `/shows/{show_id}`, and
   `/rss/subscriptions/bulk` vs `/rss/subscriptions/{sub_id}`. Expected:
   every literal path still resolves to its own handler. Pinned by Task 1,
   `test_literal_routes_are_not_shadowed`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tests/test_api_contract.py` | Create | OpenAPI snapshot, route-shadowing check, complexity ratchet |
| `tests/fixtures/openapi_snapshot.json` | Create (generated) | Frozen normalized OpenAPI document |
| `src/jidou/api/dependencies.py` | Modify | Gains `get_tmdb` / `_tmdb` (from `shows.py`) |
| `src/jidou/api/lookups.py` | Create | `one_or_404`, `get_or_404`, `get_show_or_404` |
| `src/jidou/services/task_dispatch.py` | Create | `CeleryTaskRef`, `TASK_REGISTRY`, `enqueue_celery_task`, `dispatch_registered_task` |
| `src/jidou/services/file_relink.py` | Create | `reassign_show`, `relink_episode`, domain exceptions |
| `src/jidou/services/discover_feed.py` | Create | `build_discover_feed` and its stages |
| `src/jidou/services/health_probes.py` | Create | `ProbeResult`, `ProbeFailedError`, `run_probe`, `ping_redis` |
| `src/jidou/api/routes/tmdb_proxy.py` | Create (Task 13) | `/shows/tmdb/*` endpoints |
| `src/jidou/api/routes/show_episodes.py` | Create (Task 13) | `/shows/{show_id}/episodes…` endpoints |
| `src/jidou/api/routes/show_local_files.py` | Create (Task 13) | scan-local / link-movie endpoints |
| `src/jidou/api/routes/rss_feeds.py`, `rss_subscriptions.py`, `rss_publish.py` | Create (Task 14) | Replace `rss.py` |
| `tests/test_api_lookups.py`, `test_task_dispatch.py`, `test_file_relink.py`, `test_discover_feed.py`, `test_health_probes.py` | Create | Unit tests for the new modules |

## PR grouping

| PR | Branch | Tasks |
|---|---|---|
| 1 | `refactor/api-baseline-guards` | 1, 2, 3 |
| 2 | `refactor/api-tmdb-dependency` | 4 |
| 3 | `refactor/api-lookup-helpers` | 5, 6, 7 |
| 4 | `refactor/api-task-dispatch` | 8 |
| 5 | `refactor/api-file-relink` | 9 |
| 6 | `refactor/api-discover-settings` | 10, 11 |
| 7 | `refactor/api-health-probes` | 12 |
| 8 | `refactor/api-split-route-modules` | 13, 14, 15 |

---

## Phase 0 — Safety net

### Task 1: OpenAPI contract snapshot and route-shadowing guard

**Files:**
- Create: `tests/test_api_contract.py`
- Create (generated): `tests/fixtures/openapi_snapshot.json`

**Interfaces:**
- Produces: `tests/test_api_contract.py::test_openapi_contract_unchanged`
  and `::test_literal_routes_are_not_shadowed`. Every later task runs them.
  Regenerate the snapshot only when `JIDOU_UPDATE_OPENAPI_SNAPSHOT=1`, and
  only in this task.

- [ ] **Step 1: Write the tests**

```python
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
```

- [ ] **Step 2: Generate the snapshot**

Run: `JIDOU_UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_api_contract.py -v`
Expected: `test_openapi_contract_unchanged` SKIPPED ("regenerated"),
`test_literal_routes_are_not_shadowed` PASSED. The file
`tests/fixtures/openapi_snapshot.json` now exists.

- [ ] **Step 3: Verify the guard detects drift**

Temporarily change one `detail`-free piece of the contract. For example, in
`src/jidou/api/routes/export_routes.py` change the router `tags=["export"]`
to `tags=["export2"]`.
Run: `uv run pytest tests/test_api_contract.py::test_openapi_contract_unchanged -v`
Expected: FAIL with "OpenAPI contract changed". Revert the tag change, then
re-run. Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_api_contract.py tests/fixtures/openapi_snapshot.json
git commit -m "test(api): freeze OpenAPI contract and guard route shadowing"
```

### Task 2: Complexity ratchet for `src/jidou/api`

**Files:**
- Modify: `tests/test_api_contract.py` (append)

**Interfaces:**
- Produces: the constant `_API_MAX_COMPLEXITY` in `tests/test_api_contract.py`.
  Tasks 9 and 10 lower it.

- [ ] **Step 1: Append the ratchet test**

```python
import subprocess  # noqa: E402  (keep with the other imports when merging)
import sys  # noqa: E402

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
```

Move the `subprocess` and `sys` imports into the import block at the top of
the file, drop the `noqa: E402` comments, and run `uv run ruff check --fix
tests/test_api_contract.py` so isort orders them.

- [ ] **Step 2: Prove the ratchet fails when set too low**

Set `_API_MAX_COMPLEXITY = 15`.
Run: `uv run pytest tests/test_api_contract.py::test_api_cyclomatic_complexity_ratchet -v`
Expected: FAIL, and the output names `patch_file`.
Set it back to `16` and re-run. Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_contract.py
git commit -m "test(api): add cyclomatic complexity ratchet for the API package"
```

### Task 3: Characterization tests for the hotspot gaps

The existing route tests already cover `patch_file` (17 tests), discover (7),
health (18) and settings GET/PATCH per field. This task fills only the gaps
that later refactors depend on.

**Files:**
- Modify: `tests/test_task_routes.py` (append)
- Modify: `tests/test_settings_routes.py` (append to `class TestUpdateSettings`)

**Interfaces:**
- Consumes: `_make_task` in `tests/test_task_routes.py`; `get_session` and
  `app` in `tests/test_settings_routes.py`.

- [ ] **Step 1: Write a dispatch test for every task type**

Append to `tests/test_task_routes.py`:

```python
@pytest.mark.parametrize(
    ("task_type", "target"),
    [
        ("download", "jidou.workers.download_tasks.download_files_task"),
        ("scan", "jidou.workers.scan_tasks.scan_remote_task"),
        ("match", "jidou.workers.match_tasks.match_files_task"),
        ("route", "jidou.workers.route_tasks.route_files_task"),
        ("sync", "jidou.workers.sync_tasks.sync_all_task"),
        ("seed", "jidou.workers.seed_tasks.seed_remote_task"),
        ("backfill_show_metadata", "jidou.workers.backfill_tasks.backfill_show_metadata_task"),
    ],
)
def test_trigger_task_dispatches_the_matching_worker(task_type: str, target: str) -> None:
    """Each supported task_type dispatches exactly its own Celery task with [dry_run]."""
    mock_task = _make_task(celery_task_id=f"{task_type}-id", task_type=task_type)

    async def fake_create(session, task_id, task_type_, **kwargs):  # type: ignore[no-untyped-def]
        return mock_task

    mock_celery = MagicMock()
    with (
        patch("jidou.services.progress.create_task_record", side_effect=fake_create),
        patch(
            "jidou.services.progress.get_active_task",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(target, mock_celery),
    ):
        resp = TestClient(app).post(
            "/api/tasks/trigger", json={"task_type": task_type, "dry_run": True}
        )

    assert resp.is_success, resp.text
    mock_celery.apply_async.assert_called_once()
    call = mock_celery.apply_async.call_args
    assert call.kwargs["args"] == [True]
    assert isinstance(call.kwargs["task_id"], str)
```

- [ ] **Step 2: Write the settings PATCH edge-case tests**

Append inside `class TestUpdateSettings` in `tests/test_settings_routes.py`:

```python
def test_patch_all_fields_upserts_each_once(self) -> None:
    """A PATCH carrying every field issues one upsert per field, then one re-fetch."""
    payload = {
        "show_adult_content": True,
        "calendar_enabled": False,
        "discover_enabled": False,
        "dashboard_page_enabled": False,
        "recent_episodes_enabled": False,
        "recent_movies_enabled": False,
        "recent_episodes_prefer_posters": True,
        "similar_titles_enabled": False,
        "similar_titles_count": 5,
        "similar_titles_include_external": False,
    }
    result_after = MagicMock()
    result_after.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[None] * len(payload) + [result_after])
    session.flush = AsyncMock()

    async def _mock_session() -> AsyncMock:
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        resp = TestClient(app).patch("/api/settings", json=payload)
        assert resp.status_code == 200
        assert session.execute.await_count == len(payload) + 1
        session.flush.assert_awaited()
    finally:
        app.dependency_overrides.clear()


def test_patch_empty_body_writes_nothing(self) -> None:
    """An empty PATCH performs no upsert and no flush; it only re-reads state."""
    result_after = MagicMock()
    result_after.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[result_after])
    session.flush = AsyncMock()

    async def _mock_session() -> AsyncMock:
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        resp = TestClient(app).patch("/api/settings", json={})
        assert resp.status_code == 200
        assert session.execute.await_count == 1
        session.flush.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run the new tests against the unchanged code**

Run: `uv run pytest tests/test_task_routes.py tests/test_settings_routes.py -v`
Expected: all PASS. These are characterization tests, so they must pass
before any refactor. If one fails, the test is wrong about current behavior.
Fix the test, not the code.

- [ ] **Step 4: Run the full suite, then commit and open PR 1**

Run: `uv run pytest`. Expected: PASS.

```bash
git add tests/test_task_routes.py tests/test_settings_routes.py
git commit -m "test(api): characterize task dispatch and settings PATCH edge cases"
```

Then bump the version, push, open PR 1, and follow the Bugbot loop (see
Global Constraints).

---

## Phase 1 — Dependency consolidation

### Task 4: Move `get_tmdb` into `api/dependencies.py`

**Files:**
- Modify: `src/jidou/api/dependencies.py`
- Modify: `src/jidou/api/routes/shows.py`: delete `_tmdb = TMDBService()`
  and `async def get_tmdb()`; import `get_tmdb` from dependencies.
- Modify: `src/jidou/api/routes/rss.py:14`: change the import source.
- Modify: `tests/test_shows_routes.py`, `tests/test_calendar_sync_missing_route.py`,
  `tests/test_rss_feed_add_show_route.py`, `tests/test_dependencies.py`

**Interfaces:**
- Produces: `jidou.api.dependencies.get_tmdb() -> TMDBService` (async) and
  the module global `jidou.api.dependencies._tmdb`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dependencies.py`:

```python
def test_get_tmdb_returns_one_shared_instance() -> None:
    """get_tmdb is provided by api.dependencies and returns the same object every call."""
    import asyncio

    from jidou.api.dependencies import get_tmdb
    from jidou.services.tmdb import TMDBService

    first = asyncio.run(get_tmdb())
    second = asyncio.run(get_tmdb())
    assert isinstance(first, TMDBService)
    assert first is second
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_dependencies.py::test_get_tmdb_returns_one_shared_instance -v`
Expected: FAIL with `ImportError: cannot import name 'get_tmdb'`.

- [ ] **Step 3: Move the provider**

In `src/jidou/api/dependencies.py`, add the import
`from jidou.services.tmdb import TMDBService` and add this after
`get_feed_fetch_service`:

```python
_tmdb = TMDBService()


async def get_tmdb() -> TMDBService:
    """Return the process-wide :class:`TMDBService`.

    One instance is shared so its response cache and rate limiter apply
    across every request and every router that needs TMDB.

    Returns:
        The shared TMDB service.
    """
    return _tmdb
```

In `src/jidou/api/routes/shows.py`, delete the `_tmdb = TMDBService()` line
and the whole `async def get_tmdb()` function. Add `get_tmdb` to the
existing `from jidou.api.dependencies import …` line. Keep the
`TMDBService` import only if it is still used for type annotations (ruff
F401 will tell you).

In `src/jidou/api/routes/rss.py`, replace
`from jidou.api.routes.shows import get_tmdb` with the same name imported
from `jidou.api.dependencies`. Merge it into the existing
`from jidou.api.dependencies import …` line.

- [ ] **Step 4: Update the tests**

Run these replacements (Git Bash):

```bash
grep -rl "from jidou.api.routes.shows import get_tmdb" tests \
  | xargs sed -i 's/from jidou.api.routes.shows import get_tmdb/from jidou.api.dependencies import get_tmdb/'
grep -rl "jidou.api.routes.shows._tmdb" tests \
  | xargs sed -i 's/jidou\.api\.routes\.shows\._tmdb/jidou.api.dependencies._tmdb/g'
grep -rn "routes.shows import.*get_tmdb\|routes\.shows\._tmdb" tests || echo "clean"
```

Expected final output: `clean`. If an import line names `get_tmdb` together
with other names, split it by hand.

- [ ] **Step 5: Verify**

Run: `uv run pytest tests/test_dependencies.py tests/test_shows_routes.py tests/test_calendar_sync_missing_route.py tests/test_rss_feed_add_show_route.py tests/test_api_contract.py -v`
Expected: all PASS, with the OpenAPI snapshot unchanged.
Run: `grep -n "api.routes" src/jidou/api/routes/*.py`
Expected: no output, meaning no route-to-route imports remain.

- [ ] **Step 6: Commit and open PR 2**

```bash
git add src/jidou/api tests
git commit -m "refactor(api): provide TMDBService from api.dependencies, drop rss→shows import"
```

Run `graphify update .`, bump the version, push, open PR 2, then follow the
Bugbot loop.

---

## Phase 2 — Lookup helpers (R1–R3)

**Design decision:** these are plain async helpers called inside the
handler, not FastAPI `Depends`. That keeps execution order identical: a
handler that validates something before its lookup still does so, and a
request with an invalid body still gets 422 before any 404. They also keep
the `execute(select(...)).scalar_one_or_none()` call shape that every
existing route test mocks, via `_session_override(single=…)`.

### Task 5: `api/lookups.py`

**Files:**
- Create: `src/jidou/api/lookups.py`
- Test: `tests/test_api_lookups.py`

**Interfaces:**
- Produces:
  - `async def one_or_404[T](session: AsyncSession, stmt: Select[tuple[T]], *, detail: str) -> T`
  - `async def get_or_404[ModelT: Base](session: AsyncSession, model: type[ModelT], *criteria: ColumnElement[bool], detail: str, for_update: bool = False) -> ModelT`
  - `async def get_show_or_404(session: AsyncSession, show_id: int, *, for_update: bool = False) -> Show`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for jidou.api.lookups."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from jidou.api.lookups import get_or_404, get_show_or_404, one_or_404
from jidou.models.show import Show


def _session_returning(value: object) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _executed_sql(session: AsyncMock) -> str:
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_one_or_404_returns_row() -> None:
    row = MagicMock()
    session = _session_returning(row)
    assert asyncio.run(one_or_404(session, select(Show), detail="x")) is row


def test_one_or_404_raises_404_with_exact_detail() -> None:
    session = _session_returning(None)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(one_or_404(session, select(Show), detail="Thing not found"))
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Thing not found"


def test_get_or_404_filters_by_criteria() -> None:
    session = _session_returning(MagicMock())
    asyncio.run(get_or_404(session, Show, Show.id == 7, detail="Show not found"))
    sql = _executed_sql(session)
    assert "FROM shows" in sql or "FROM show" in sql
    assert "WHERE" in sql
    assert "FOR UPDATE" not in sql


def test_get_or_404_for_update_emits_for_update() -> None:
    session = _session_returning(MagicMock())
    asyncio.run(get_or_404(session, Show, Show.id == 7, detail="Show not found", for_update=True))
    assert "FOR UPDATE" in _executed_sql(session)


def test_get_show_or_404_uses_canonical_detail() -> None:
    session = _session_returning(None)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_show_or_404(session, 123))
    assert exc_info.value.detail == "Show not found"


def test_get_show_or_404_returns_show() -> None:
    show = MagicMock(spec=Show)
    session = _session_returning(show)
    assert asyncio.run(get_show_or_404(session, 1)) is show
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_api_lookups.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jidou.api.lookups'`.

- [ ] **Step 3: Implement**

```python
"""Fetch-or-404 helpers for route handlers.

These replace the hand-written ``select → scalar_one_or_none → raise 404``
blocks repeated across the route modules. They are plain coroutines rather
than FastAPI dependencies so that handler execution order (and therefore
422-vs-404 precedence) is unchanged at every call site.
"""

from fastapi import HTTPException
from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.base import Base
from jidou.models.show import Show


async def one_or_404[T](session: AsyncSession, stmt: Select[tuple[T]], *, detail: str) -> T:
    """Execute *stmt* and return its single row, or raise HTTP 404.

    Use this form when the statement needs loader options, a shared base
    statement, ordering, or a row lock that :func:`get_or_404` does not express.

    Args:
        session: Active async DB session.
        stmt: A ``select`` returning at most one row.
        detail: The exact 404 ``detail`` string the endpoint has always returned.

    Returns:
        The single row.

    Raises:
        HTTPException: 404 with *detail* when no row matches.
    """
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=detail)
    return row


async def get_or_404[ModelT: Base](
    session: AsyncSession,
    model: type[ModelT],
    *criteria: ColumnElement[bool],
    detail: str,
    for_update: bool = False,
) -> ModelT:
    """Fetch one *model* row matching all *criteria*, or raise HTTP 404.

    Args:
        session: Active async DB session.
        model: ORM class to select.
        *criteria: ``WHERE`` clauses, ANDed together.
        detail: The exact 404 ``detail`` string.
        for_update: Emit ``SELECT … FOR UPDATE`` (row lock) when True.

    Returns:
        The matching ORM instance.

    Raises:
        HTTPException: 404 with *detail* when no row matches.

    Example:
        >>> ep = await get_or_404(
        ...     db, Episode, Episode.id == eid, Episode.show_id == sid,
        ...     detail="Episode not found",
        ... )
    """
    stmt = select(model).where(*criteria)
    if for_update:
        stmt = stmt.with_for_update()
    return await one_or_404(session, stmt, detail=detail)


async def get_show_or_404(session: AsyncSession, show_id: int, *, for_update: bool = False) -> Show:
    """Fetch a :class:`Show` by primary key, or raise HTTP 404 ``"Show not found"``.

    Args:
        session: Active async DB session.
        show_id: Database primary key.
        for_update: Lock the row (``SELECT … FOR UPDATE``) when True.

    Returns:
        The show.

    Raises:
        HTTPException: 404 ``"Show not found"``.
    """
    return await get_or_404(
        session, Show, Show.id == show_id, detail="Show not found", for_update=for_update
    )
```

- [ ] **Step 4: Run the tests to verify they pass, then type-check**

Run: `uv run pytest tests/test_api_lookups.py -v`. Expected: PASS.
Run: `uv run mypy src/jidou/api/lookups.py`. Expected: `Success`.
If `test_get_or_404_filters_by_criteria` fails only on the table-name
assertion, check `Show.__tablename__` and assert that exact name.

- [ ] **Step 5: Commit**

```bash
git add src/jidou/api/lookups.py tests/test_api_lookups.py
git commit -m "feat(api): add one_or_404/get_or_404/get_show_or_404 lookup helpers"
```

### Task 6: Migrate the `shows.py` lookups

**Files:**
- Modify: `src/jidou/api/routes/shows.py`

**Interfaces:**
- Consumes: `get_or_404` and `get_show_or_404` from Task 5.

**Conversion rules.** Apply them exactly. Only the lookup lines change; no
surrounding code moves.

| Before (any of these shapes) | After |
|---|---|
| `stmt = select(Show).where(Show.id == show_id)` / `show = (await db_session.execute(stmt)).scalar_one_or_none()` / `if show is None: raise HTTPException(status_code=404, detail="Show not found")` | `show = await get_show_or_404(db_session, show_id)` |
| `show = (await db_session.execute(select(Show).where(Show.id == show_id))).scalar_one_or_none()` + same `if` | `show = await get_show_or_404(db_session, show_id)` |
| `show_stmt = select(Show).where(Show.id == show_id)` / `if (await db_session.execute(show_stmt)).scalar_one_or_none() is None: raise …` | `await get_show_or_404(db_session, show_id)` |
| `show_stmt = select(Show).where(Show.id == show_id).with_for_update()` (in `link_movie_file`) | `show = await get_show_or_404(db_session, show_id, for_update=True)` |

If the converted handler later reads `stmt` or `show_stmt` again, keep the
original lines at that site. Ruff F821 or F841 will flag it. Record any
such skipped site in the PR description.

- [ ] **Step 1: Rewrite the two private helpers**

Replace the bodies of `_get_episode_or_404` and `_get_show_episodes_or_404`.
Keep their docstrings.

```python
async def _get_episode_or_404(db_session: AsyncSession, show_id: int, episode_id: int) -> Episode:
    # (docstring unchanged)
    await get_show_or_404(db_session, show_id)
    return await get_or_404(
        db_session,
        Episode,
        Episode.id == episode_id,
        Episode.show_id == show_id,
        detail="Episode not found",
    )
```

```python
async def _get_show_episodes_or_404(
    db_session: AsyncSession, show_id: int, season_number: int | None
) -> list[Episode]:
    # (docstring unchanged)
    await get_show_or_404(db_session, show_id)
    ep_stmt = select(Episode).where(Episode.show_id == show_id)
    if season_number is not None:
        ep_stmt = ep_stmt.where(Episode.season_number == season_number)
    ep_stmt = ep_stmt.order_by(Episode.season_number, Episode.episode_number)
    return list((await db_session.execute(ep_stmt)).scalars().all())
```

Add `from jidou.api.lookups import get_or_404, get_show_or_404` to the
imports.

- [ ] **Step 2: Convert the remaining handler sites**

Find them with: `grep -n '"Show not found"' src/jidou/api/routes/shows.py`.
Before this task there are 25 hits, including the two helpers. Convert each
one using the rules table.
Then run: `grep -c '"Show not found"' src/jidou/api/routes/shows.py`.
Expected: `0`, or the number of sites you recorded as skipped.

- [ ] **Step 3: Lint and test**

Run: `uv run ruff check src/jidou/api/routes/shows.py --fix` (this removes
any now-unused imports).
Run: `uv run pytest tests/test_shows_routes.py tests/test_shows_rss_stub_routes.py tests/test_calendar_routes.py tests/test_calendar_sync_missing_route.py tests/test_api_contract.py -q`
Expected: PASS, with the OpenAPI snapshot unchanged.

- [ ] **Step 4: Commit**

```bash
git add src/jidou/api/routes/shows.py
git commit -m "refactor(api): use lookup helpers for show/episode 404s in shows routes"
```

### Task 7: Migrate lookups in `rss.py`, `files.py`, `orphans.py` and `watchlist.py`

**Files:**
- Modify: `src/jidou/api/routes/rss.py`, `files.py`, `orphans.py`, `watchlist.py`

**Interfaces:**
- Consumes: `one_or_404`, `get_or_404` and `get_show_or_404` from Task 5.

Use this exact site list, found by the quoted `detail`. Every `detail` string
stays byte-for-byte the same.

| File | `detail` | Form to use |
|---|---|---|
| `rss.py` | `"Show not found"` ×2 (body `payload.show_id`, inside an `if`) | `await get_show_or_404(db_session, payload.show_id)`, kept inside the same `if` |
| `rss.py` | `"RSS feed not found"`: the body of `_get_feed_or_404` | `return await get_or_404(db_session, RssFeed, RssFeed.id == feed_id, detail="RSS feed not found")` |
| `rss.py` | `"RSS feed not found"`: inline lookups by `feed_id` (PATCH feed, entries) | `feed = await _get_feed_or_404(db_session, feed_id)` |
| `rss.py` | `"RSS feed not found"`: feed delete, `.with_for_update()` | `feed = await get_or_404(db_session, RssFeed, RssFeed.id == feed_id, detail="RSS feed not found", for_update=True)` |
| `rss.py` | `"RSS feed not found"`: body `payload.feed_id` / `body.feed_id` existence checks (×3) | `await _get_feed_or_404(db_session, payload.feed_id)` (or `body.feed_id`); keep `feed = ` if the variable is used afterwards |
| `rss.py` | `"RSS subscription not found"` with `_sub_stmt().where(...)` (×3) | `sub = await one_or_404(db_session, _sub_stmt().where(RssSubscription.id == sub_id), detail="RSS subscription not found")` |
| `rss.py` | `"RSS subscription not found"`: subscription delete, `.with_for_update()` | `sub = await get_or_404(db_session, RssSubscription, RssSubscription.id == sub_id, detail="RSS subscription not found", for_update=True)` |
| `rss.py` | `"RSS subscription not found"`: preview, with `.options(selectinload(RssSubscription.feed))` | `sub = await one_or_404(db_session, stmt, detail="RSS subscription not found")`, keeping the existing `stmt =` line |
| `rss.py` | `"No config snapshot found — run an import first"` (×2) | `snapshot = await one_or_404(db_session, snapshot_stmt, detail="No config snapshot found — run an import first")` |
| `files.py` | `"File not found"` ×5 | Plain shape: `file = await get_or_404(db_session, DownloadedFile, DownloadedFile.id == file_id, detail="File not found")`. The `get_file` site has `.options(...)`, so use `one_or_404(db_session, stmt, detail="File not found")` |
| `orphans.py` | `"Show not found"` | `show = await get_show_or_404(db_session, show_id)` |
| `orphans.py` | `"Orphan record not found"` ×2 | `record = await get_or_404(db_session, OrphanedTrackingRecord, OrphanedTrackingRecord.id == orphan_id, detail="Orphan record not found")` |
| `orphans.py` | `"Episode not found"` | `ep = await get_or_404(db_session, Episode, Episode.id == payload.episode_id, detail="Episode not found")` |
| `watchlist.py` | `"Show not found"` (body) | `await get_show_or_404(db_session, payload.show_id)` |
| `watchlist.py` | `"Watchlist entry not found"` ×3 | Sites with `.options(...)`: `one_or_404(db_session, stmt, detail=…)`. Plain site: `get_or_404(db_session, WatchlistEntry, WatchlistEntry.id == entry_id, detail=…)` |

**Out of scope:** leave these unchanged. They are not single-row lookups:
- the multi-line `orphans.py` `file is None` 404 (it has a custom detail)
- `watchlist.py` bulk `missing` 404
- `rss.py` `_feed_group_or_http_error`

- [ ] **Step 1: Convert `watchlist.py` and `orphans.py`, then test**

Run: `uv run ruff check src/jidou/api/routes --fix && uv run pytest tests/test_watchlist_routes.py tests/test_orphan_routes.py -q`
Expected: PASS.

- [ ] **Step 2: Convert `files.py`, then test**

Run: `uv run pytest tests/test_files_routes.py -q`
Expected: PASS.

- [ ] **Step 3: Convert `rss.py`, then test**

Run: `uv run pytest tests/ -q -k "rss"`
Expected: PASS.

- [ ] **Step 4: Run the full verification**

Run: `uv run pytest tests/test_api_contract.py -v && uv run pytest -q && uv run mypy src/`
Expected: all PASS, with the snapshot unchanged.
Run: `grep -c "status_code=404" src/jidou/api/routes/{rss,files,orphans,watchlist}.py`
Expected: only the out-of-scope sites remain (rss 1, files 0, orphans 1,
watchlist 1).

- [ ] **Step 5: Commit and open PR 3**

```bash
git add src/jidou/api/routes
git commit -m "refactor(api): use lookup helpers in rss, files, orphans and watchlist routes"
```

Run `graphify update .`, bump the version, push, open PR 3, then follow the
Bugbot loop.

---

## Phase 3 — Domain services

### Task 8: Task dispatch service (R4 and the `trigger_task` registry)

**Files:**
- Create: `src/jidou/services/task_dispatch.py`
- Test: `tests/test_task_dispatch.py`
- Modify: `src/jidou/api/routes/tasks.py` (`trigger_task`),
  `src/jidou/api/routes/import_routes.py` (`import_text`, `import_database`),
  `src/jidou/api/routes/rss.py` (`trigger_rss_import`, `trigger_rss_publish`)
- Modify: tests that patch `jidou.api.routes.rss.enqueue_task`
  (`grep -rn "routes.rss.enqueue_task" tests`)

**Interfaces:**
- Consumes: `jidou.services.progress.enqueue_task`, `get_active_task` and
  `TaskDispatchError`. Always call them through the module
  (`progress.enqueue_task`) so the existing
  `patch("jidou.services.progress.…")` targets keep working.
- Produces:
  - `CeleryTaskRef(module: str, attr: str)` with `.resolve() -> Any`
  - `RegisteredTask(ref: CeleryTaskRef, reuse_active: bool = False)`
  - `TASK_REGISTRY: Final[dict[str, RegisteredTask]]`
  - `class UnknownTaskTypeError(ValueError)`
  - `async def enqueue_celery_task(session: AsyncSession, task_type: str, ref: CeleryTaskRef, *, args: Sequence[Any], dry_run: bool) -> BackgroundTask`
  - `async def dispatch_registered_task(session: AsyncSession, task_type: str, *, dry_run: bool) -> BackgroundTask`

**Intentional behavior change (the only one in this plan):** today,
`trigger_task` imports all seven worker modules before dispatching, so a
broken worker module produces a 500 and no task row. After this task, the
import happens inside the dispatch callable, as `rss.py` already does: the
row is marked FAILED and the API returns 503. This matches the existing
`rss.py` comment ("keeps a failure here … inside enqueue_task's failure
handling"). Call it out in the PR description.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for jidou.services.task_dispatch."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.progress import TaskDispatchError
from jidou.services.task_dispatch import (
    TASK_REGISTRY,
    CeleryTaskRef,
    UnknownTaskTypeError,
    dispatch_registered_task,
    enqueue_celery_task,
)


def test_registry_lists_exactly_the_supported_task_types() -> None:
    assert set(TASK_REGISTRY) == {
        "download",
        "scan",
        "match",
        "route",
        "sync",
        "seed",
        "backfill_show_metadata",
    }


def test_only_route_reuses_an_active_task() -> None:
    assert {k for k, v in TASK_REGISTRY.items() if v.reuse_active} == {"route"}


def test_every_registry_ref_resolves_to_an_object_with_apply_async() -> None:
    for task_type, registered in TASK_REGISTRY.items():
        assert hasattr(registered.ref.resolve(), "apply_async"), task_type


def test_unknown_task_type_raises() -> None:
    with pytest.raises(UnknownTaskTypeError, match="Unknown task type: nope"):
        asyncio.run(dispatch_registered_task(AsyncMock(), "nope", dry_run=False))


def test_route_returns_active_task_without_enqueueing() -> None:
    active = MagicMock()
    with (
        patch(
            "jidou.services.progress.get_active_task",
            new_callable=AsyncMock,
            return_value=active,
        ),
        patch("jidou.services.progress.enqueue_task", new_callable=AsyncMock) as enqueue,
    ):
        result = asyncio.run(dispatch_registered_task(AsyncMock(), "route", dry_run=False))
    assert result is active
    enqueue.assert_not_awaited()


def test_enqueue_celery_task_resolves_lazily_and_passes_args() -> None:
    """The task object is looked up at dispatch time, so module-level patches apply."""
    created = MagicMock()
    mock_celery = MagicMock()

    async def fake_create(session, task_id, task_type, **kwargs):  # type: ignore[no-untyped-def]
        return created

    with (
        patch("jidou.services.progress.create_task_record", side_effect=fake_create),
        patch("jidou.workers.scan_tasks.scan_remote_task", mock_celery),
    ):
        result = asyncio.run(
            enqueue_celery_task(
                AsyncMock(),
                "scan",
                CeleryTaskRef("jidou.workers.scan_tasks", "scan_remote_task"),
                args=[True],
                dry_run=True,
            )
        )
    assert result is created
    call = mock_celery.apply_async.call_args
    assert call.kwargs["args"] == [True]
    assert isinstance(call.kwargs["task_id"], str)


def test_enqueue_celery_task_import_failure_marks_failed() -> None:
    """A broken worker module is a dispatch failure: row FAILED + TaskDispatchError."""

    async def fake_create(session, task_id, task_type, **kwargs):  # type: ignore[no-untyped-def]
        return MagicMock()

    with (
        patch("jidou.services.progress.create_task_record", side_effect=fake_create),
        patch("jidou.services.progress.update_task_status", new_callable=AsyncMock) as upd,
        pytest.raises(TaskDispatchError),
    ):
        asyncio.run(
            enqueue_celery_task(
                AsyncMock(),
                "scan",
                CeleryTaskRef("jidou.workers.does_not_exist", "nope"),
                args=[],
                dry_run=False,
            )
        )
    upd.assert_awaited_once()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_task_dispatch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jidou.services.task_dispatch'`.

- [ ] **Step 3: Implement**

```python
"""Dispatch Celery-backed background tasks behind a pre-created BackgroundTask row.

Centralizes the "pre-generate task id → create row → apply_async → mark FAILED
on broker error" sequence that every task-triggering route used to repeat, and
the registry of task types that ``POST /api/tasks/trigger`` accepts.
"""

import importlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.task import BackgroundTask
from jidou.services import progress

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CeleryTaskRef:
    """Lazy reference to a Celery task by module path and attribute name.

    Resolution happens inside the dispatch callable, so importing this module
    never imports the Celery app (avoiding circular imports), and an
    ImportError in a worker module goes through ``enqueue_task``'s failure
    handling (row marked FAILED, ``TaskDispatchError`` raised).

    Attributes:
        module: Dotted module path, e.g. ``"jidou.workers.scan_tasks"``.
        attr: Task attribute name within that module.
    """

    module: str
    attr: str

    def resolve(self) -> Any:
        """Import the module and return the task object.

        Returns:
            The Celery task (anything exposing ``apply_async``).
        """
        return getattr(importlib.import_module(self.module), self.attr)


@dataclass(frozen=True, slots=True)
class RegisteredTask:
    """A task type accepted by ``POST /api/tasks/trigger``.

    Attributes:
        ref: The Celery task to dispatch with ``args=[dry_run]``.
        reuse_active: Return the currently PENDING/RUNNING task of this type
            instead of dispatching a second, overlapping run.
    """

    ref: CeleryTaskRef
    reuse_active: bool = False


TASK_REGISTRY: Final[dict[str, RegisteredTask]] = {
    "download": RegisteredTask(
        CeleryTaskRef("jidou.workers.download_tasks", "download_files_task")
    ),
    "scan": RegisteredTask(CeleryTaskRef("jidou.workers.scan_tasks", "scan_remote_task")),
    "match": RegisteredTask(CeleryTaskRef("jidou.workers.match_tasks", "match_files_task")),
    # RouteOrchestrator selects all MATCHED/ROUTING files upfront and commits each
    # file's transition individually, without per-row claiming, so two overlapping
    # route runs can both route the same file (duplicate copies at the destination).
    # RematchModal triggers a route after every fix, so overlaps are common; reuse
    # the active run, which already covers every currently-MATCHED file.
    "route": RegisteredTask(
        CeleryTaskRef("jidou.workers.route_tasks", "route_files_task"), reuse_active=True
    ),
    "sync": RegisteredTask(CeleryTaskRef("jidou.workers.sync_tasks", "sync_all_task")),
    "seed": RegisteredTask(CeleryTaskRef("jidou.workers.seed_tasks", "seed_remote_task")),
    "backfill_show_metadata": RegisteredTask(
        CeleryTaskRef("jidou.workers.backfill_tasks", "backfill_show_metadata_task")
    ),
}


class UnknownTaskTypeError(ValueError):
    """Raised when a task type is not present in :data:`TASK_REGISTRY`."""


async def enqueue_celery_task(
    session: AsyncSession,
    task_type: str,
    ref: CeleryTaskRef,
    *,
    args: Sequence[Any],
    dry_run: bool,
) -> BackgroundTask:
    """Create the BackgroundTask row, then dispatch *ref* with a pre-generated id.

    Args:
        session: Active async DB session.
        task_type: Type label stored on the row (e.g. ``"rss_import"``).
        ref: The Celery task to dispatch.
        args: Positional arguments for ``apply_async``.
        dry_run: Stored on the row.

    Returns:
        The created BackgroundTask row.

    Raises:
        TaskDispatchError: If resolving or dispatching the task failed; the
            row has already been marked FAILED.
    """
    task_id = str(uuid.uuid4())
    task_args = list(args)

    def _dispatch() -> None:
        ref.resolve().apply_async(args=task_args, task_id=task_id)

    task = await progress.enqueue_task(session, task_id, task_type, _dispatch, dry_run=dry_run)
    logger.info("Enqueued task type=%s id=%s dry_run=%s", task_type, task_id, dry_run)
    return task


async def dispatch_registered_task(
    session: AsyncSession, task_type: str, *, dry_run: bool
) -> BackgroundTask:
    """Dispatch a task type from :data:`TASK_REGISTRY` with ``args=[dry_run]``.

    Args:
        session: Active async DB session.
        task_type: A key of :data:`TASK_REGISTRY`.
        dry_run: Passed to the task and stored on the row.

    Returns:
        The new BackgroundTask row, or the already-active row for task types
        with ``reuse_active``.

    Raises:
        UnknownTaskTypeError: *task_type* is not registered.
        TaskDispatchError: The broker dispatch failed.
    """
    registered = TASK_REGISTRY.get(task_type)
    if registered is None:
        raise UnknownTaskTypeError(f"Unknown task type: {task_type}")
    if registered.reuse_active:
        active = await progress.get_active_task(session, task_type)
        if active is not None:
            logger.info("Reusing active task type=%s id=%s", task_type, active.celery_task_id)
            return active
    return await enqueue_celery_task(
        session, task_type, registered.ref, args=[dry_run], dry_run=dry_run
    )
```

- [ ] **Step 4: Run the unit tests**

Run: `uv run pytest tests/test_task_dispatch.py -v`. Expected: PASS.

- [ ] **Step 5: Rewrite `trigger_task`**

Keep the decorator and docstring. Replace the body from
`if payload.task_type not in {` through the end of the function with:

```python
try:
    return await dispatch_registered_task(db_session, payload.task_type, dry_run=payload.dry_run)
except UnknownTaskTypeError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
except TaskDispatchError as exc:
    raise HTTPException(status_code=503, detail="Failed to dispatch task to broker") from exc
```

Add top-level imports:
`from jidou.services.progress import TaskDispatchError` and
`from jidou.services.task_dispatch import UnknownTaskTypeError, dispatch_registered_task`.
Remove the `uuid` import if it is now unused. Leave the other handlers in
`tasks.py` alone.

- [ ] **Step 6: Rewrite the import and rss dispatch sites**

`import_routes.py` `import_text`: replace from
`from jidou.workers.import_tasks import path_import_task` through the
`except` block with:

```python
    try:
        return await enqueue_celery_task(
            db_session,
            "import",
            CeleryTaskRef("jidou.workers.import_tasks", "path_import_task"),
            args=[file_content, content_type, dry_run, mode],
            dry_run=dry_run,
        )
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc
```

`import_routes.py` `import_database`: replace from
`from jidou.workers.db_import_tasks import db_import_task` through the
`except` block with:

```python
    try:
        return await enqueue_celery_task(
            db_session,
            "db_import",
            CeleryTaskRef("jidou.workers.db_import_tasks", "db_import_task"),
            args=[file_content],
            dry_run=False,
        )
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc
```

`rss.py` `trigger_rss_import` and `trigger_rss_publish`: replace from
`task_id = str(uuid.uuid4())` through `return new_task` with the following.
Use `"rss_publish"` / `"rss_publish_task"` in the publish handler.

```python
    try:
        return await enqueue_celery_task(
            db_session,
            "rss_import",
            CeleryTaskRef("jidou.workers.rss_tasks", "rss_import_task"),
            args=[dry_run],
            dry_run=dry_run,
        )
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc
```

The per-route `logger.info("Enqueued RSS … task")` lines are replaced by
the `logger.info` inside `enqueue_celery_task`. Run
`uv run ruff check src/jidou/api --fix` to drop the unused `uuid` and
`enqueue_task` imports.

- [ ] **Step 7: Update the moved patch targets and run the tests**

Run: `grep -rln "jidou.api.routes.rss.enqueue_task" tests | xargs sed -i 's/jidou\.api\.routes\.rss\.enqueue_task/jidou.services.progress.enqueue_task/g'`
Run: `uv run pytest tests/test_task_routes.py tests/test_api_import_routes.py tests/test_rss_routes.py tests/test_task_dispatch.py tests/test_api_contract.py -v`
Expected: PASS. In particular, Task 3's parametrized dispatch test and both
route-reuse tests pass unchanged.

- [ ] **Step 8: Run the full verification, then commit and open PR 4**

Run: `uv run pytest -q && uv run mypy src/ && uv run bandit -r src/ -l`
Expected: PASS. Bandit is not expected to flag `importlib.import_module`.
If it does, add a `# nosec <rule-id>` comment on that line, with a
justification: every module string is a compile-time constant from
`TASK_REGISTRY` or a route literal, never user input.

```bash
git add src/jidou/services/task_dispatch.py tests/test_task_dispatch.py src/jidou/api tests
git commit -m "refactor(api): centralize Celery task dispatch in services.task_dispatch"
```

Run `graphify update .`, bump the version, push, open PR 4, then follow the
Bugbot loop.

### Task 9: `file_relink` service; `patch_file` becomes thin (R6/R9)

**Files:**
- Create: `src/jidou/services/file_relink.py`
- Test: `tests/test_file_relink.py`
- Modify: `src/jidou/api/routes/files.py` (`patch_file`, plus a new private
  helper `_flush_patch`)
- Modify: `tests/test_api_contract.py` (`_API_MAX_COMPLEXITY` 16 → 14)

**Interfaces:**
- Consumes: `jidou.services.episode_tracking.clear_if_unreferenced`,
  `dismiss_orphans_for_file` and `mark_episode_tracked`.
- Produces:
  - `class FileRelinkError(Exception)`, plus
    `EpisodeShowMismatchError(FileRelinkError)` and
    `EpisodeAlreadyTrackedError(FileRelinkError)`
  - `async def reassign_show(session: AsyncSession, file: DownloadedFile, new_show_id: int | None, *, keep_episode: bool, keep_error: bool) -> None`
  - `async def relink_episode(session: AsyncSession, file: DownloadedFile, new_episode_id: int | None) -> None`

These must reproduce today's `patch_file` exactly, including ordering. The
"already tracked" comparison uses `new_episode_id`, never `ep.id`, because
the route tests use MagicMock episodes whose `id` is not set.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for jidou.services.file_relink."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.file_relink import (
    EpisodeAlreadyTrackedError,
    EpisodeShowMismatchError,
    reassign_show,
    relink_episode,
)

_MOD = "jidou.services.file_relink"


def _file(*, show_id: int | None = 1, episode_id: int | None = 10) -> MagicMock:
    f = MagicMock()
    f.id = 99
    f.show_id = show_id
    f.episode_id = episode_id
    f.matched_by = "llm"
    f.error_message = "old error"
    f.local_path = "/x/show.s01e02.mkv"
    f.original_filename = "show.s01e02.mkv"
    return f


def _episode(*, show_id: int = 1, tracked: bool = False) -> MagicMock:
    ep = MagicMock()
    ep.show_id = show_id
    ep.file_tracked = tracked
    ep.season_number = 1
    ep.episode_number = 2
    return ep


def _session_with_episode(ep: MagicMock | None) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = ep
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def test_reassign_show_same_value_is_a_noop() -> None:
    f = _file(show_id=1)
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock) as dismiss:
        asyncio.run(reassign_show(AsyncMock(), f, 1, keep_episode=False, keep_error=False))
    assert (f.episode_id, f.matched_by, f.error_message) == (10, "llm", "old error")
    dismiss.assert_not_awaited()


def test_reassign_show_change_clears_episode_matcher_and_error() -> None:
    f = _file(show_id=1)
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock) as dismiss:
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=False, keep_error=False))
    assert f.show_id == 2
    assert f.episode_id is None
    assert f.matched_by is None
    assert f.error_message is None
    dismiss.assert_awaited_once()


def test_reassign_show_keeps_explicit_episode_and_error() -> None:
    f = _file(show_id=1)
    with patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock):
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=True, keep_error=True))
    assert f.episode_id == 10
    assert f.error_message == "old error"
    assert f.matched_by is None


def test_reassign_show_without_episode_does_not_clear_old_tracking() -> None:
    """Pins current behavior (spec §5): show change alone never calls clear_if_unreferenced."""
    f = _file(show_id=1, episode_id=10)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock) as clear,
    ):
        asyncio.run(reassign_show(AsyncMock(), f, 2, keep_episode=False, keep_error=False))
    clear.assert_not_awaited()


def test_relink_episode_to_none_clears_parsed_fields_and_old_tracking() -> None:
    f = _file(episode_id=10)
    with patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock) as clear:
        asyncio.run(relink_episode(AsyncMock(), f, None))
    assert f.episode_id is None
    assert f.parsed_season is None
    assert f.parsed_episode is None
    clear.assert_awaited_once()
    assert clear.await_args.args[1:] == (10, None)


def test_relink_episode_marks_target_tracked_and_copies_numbers() -> None:
    f = _file(episode_id=10)
    ep = _episode()
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock),
        patch(f"{_MOD}.mark_episode_tracked") as mark,
    ):
        asyncio.run(relink_episode(_session_with_episode(ep), f, 11))
    mark.assert_called_once_with(ep, "/x/show.s01e02.mkv", "match")
    assert (f.episode_id, f.parsed_season, f.parsed_episode) == (11, 1, 2)


def test_relink_episode_wrong_show_raises() -> None:
    f = _file(show_id=1)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        pytest.raises(EpisodeShowMismatchError, match="Episode does not belong to the file's show"),
    ):
        asyncio.run(relink_episode(_session_with_episode(_episode(show_id=2)), f, 11))


def test_relink_episode_already_tracked_by_other_file_raises() -> None:
    f = _file(episode_id=10)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        pytest.raises(EpisodeAlreadyTrackedError, match="already tracked by another file"),
    ):
        asyncio.run(relink_episode(_session_with_episode(_episode(tracked=True)), f, 11))


def test_relink_same_tracked_episode_is_allowed() -> None:
    f = _file(episode_id=11)
    with (
        patch(f"{_MOD}.dismiss_orphans_for_file", new_callable=AsyncMock),
        patch(f"{_MOD}.clear_if_unreferenced", new_callable=AsyncMock),
        patch(f"{_MOD}.mark_episode_tracked"),
    ):
        asyncio.run(relink_episode(_session_with_episode(_episode(tracked=True)), f, 11))
    assert f.episode_id == 11
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_file_relink.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the service**

```python
"""Operator-driven reassignment of a DownloadedFile's show and episode links.

Extracted from ``PATCH /api/files/{id}`` so the linking invariants (episode
must belong to the file's show; an episode is tracked by at most one file;
stale tracking is cleared only when unreferenced) live in one tested place.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.services.episode_tracking import (
    clear_if_unreferenced,
    dismiss_orphans_for_file,
    mark_episode_tracked,
)


class FileRelinkError(Exception):
    """Base class for rejected file relink operations."""


class EpisodeShowMismatchError(FileRelinkError):
    """The target episode belongs to a different show than the file."""


class EpisodeAlreadyTrackedError(FileRelinkError):
    """The target episode is already tracked by another file."""


async def reassign_show(
    session: AsyncSession,
    file: DownloadedFile,
    new_show_id: int | None,
    *,
    keep_episode: bool,
    keep_error: bool,
) -> None:
    """Point *file* at *new_show_id*, clearing state that belonged to the old show.

    No-op when the show is unchanged. On change: the matcher is cleared, orphan
    records for the file are dismissed (resolving them later would corrupt
    ``show_id``), and the episode link / error message are cleared unless the
    caller is setting them explicitly in the same operation.

    Args:
        session: Active async DB session.
        file: File to mutate in place.
        new_show_id: Target show id (may be None).
        keep_episode: True when the caller also sets ``episode_id`` explicitly.
        keep_error: True when the caller also sets ``error_message`` explicitly.
    """
    if file.show_id == new_show_id:
        return
    file.show_id = new_show_id
    if not keep_episode:
        file.episode_id = None
    file.matched_by = None
    if not keep_error:
        file.error_message = None
    await dismiss_orphans_for_file(session, file.id)


async def relink_episode(
    session: AsyncSession, file: DownloadedFile, new_episode_id: int | None
) -> None:
    """Link *file* to *new_episode_id* (or unlink it) and maintain tracking state.

    Args:
        session: Active async DB session.
        file: File to mutate in place.
        new_episode_id: Target episode id, or None to unlink.

    Raises:
        EpisodeShowMismatchError: The episode belongs to another show.
        EpisodeAlreadyTrackedError: The episode is tracked by a different file.
    """
    old_episode_id = file.episode_id
    file.episode_id = new_episode_id
    if new_episode_id is None:
        file.parsed_season = None
        file.parsed_episode = None
    else:
        # Any orphan record waiting for this file to be re-linked is now resolved.
        await dismiss_orphans_for_file(session, file.id)
        ep = (
            await session.execute(select(Episode).where(Episode.id == new_episode_id))
        ).scalar_one_or_none()
        if ep is not None:
            _ensure_linkable(file, ep, old_episode_id, new_episode_id)
            mark_episode_tracked(ep, file.local_path or file.original_filename, "match")
            file.parsed_season = ep.season_number
            file.parsed_episode = ep.episode_number
    # Clear the previous episode's tracking only when no other file still points to it.
    await clear_if_unreferenced(session, old_episode_id, new_episode_id)


def _ensure_linkable(
    file: DownloadedFile, ep: Episode, old_episode_id: int | None, new_episode_id: int
) -> None:
    """Raise if *ep* may not be linked to *file*.

    Raises:
        EpisodeShowMismatchError: The episode belongs to another show.
        EpisodeAlreadyTrackedError: The episode is tracked by a different file.
    """
    if file.show_id is not None and ep.show_id != file.show_id:
        raise EpisodeShowMismatchError("Episode does not belong to the file's show")
    if ep.file_tracked and old_episode_id != new_episode_id:
        raise EpisodeAlreadyTrackedError("Episode is already tracked by another file")
```

Run: `uv run pytest tests/test_file_relink.py -v`. Expected: PASS.

- [ ] **Step 4: Make `patch_file` thin**

In `src/jidou/api/routes/files.py`, add this module-level helper above
`patch_file`:

```python
_PG_UNIQUE_VIOLATION = "23505"
_PG_FOREIGN_KEY_VIOLATION = "23503"


async def _flush_patch(db_session: AsyncSession) -> None:
    """Flush a file PATCH, mapping constraint violations to client errors.

    Raises:
        HTTPException: 409 on a duplicate ``remote_path``; 422 on a dangling
            ``show_id``/``episode_id`` foreign key.
        IntegrityError: Any other integrity failure, re-raised after rollback.
    """
    try:
        await db_session.flush()
    except IntegrityError as exc:
        await db_session.rollback()
        pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
        if pgcode == _PG_UNIQUE_VIOLATION:
            raise HTTPException(
                status_code=409, detail="A file with that remote_path already exists"
            ) from None
        if pgcode == _PG_FOREIGN_KEY_VIOLATION:
            raise HTTPException(
                status_code=422, detail="Referenced show_id or episode_id does not exist"
            ) from None
        raise
```

Replace `patch_file`'s body, from the line after the docstring to the line
before `refreshed = (`, with the following. The lookup line is already
`get_or_404` from Task 7.

```python
    file = await get_or_404(
        db_session, DownloadedFile, DownloadedFile.id == file_id, detail="File not found"
    )
    fields = payload.model_fields_set
    try:
        if "show_id" in fields:
            await reassign_show(
                db_session,
                file,
                payload.show_id,
                keep_episode="episode_id" in fields,
                keep_error="error_message" in fields,
            )
        if "episode_id" in fields:
            await relink_episode(db_session, file, payload.episode_id)
    except EpisodeShowMismatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except EpisodeAlreadyTrackedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if "status" in fields and payload.status is not None:
        file.status = FileStatus(payload.status)
    if "error_message" in fields:
        file.error_message = payload.error_message
    await _flush_patch(db_session)
```

Leave the `refreshed = …` block, the `logger.info` and the `return`
unchanged. Add the import
`from jidou.services.file_relink import EpisodeAlreadyTrackedError, EpisodeShowMismatchError, reassign_show, relink_episode`.
Then run `uv run ruff check src/jidou/api/routes/files.py --fix`. The
`episode_tracking` imports stay only if `manual_match_file` still uses them.

- [ ] **Step 5: Run the route tests and lower the ratchet**

Run: `uv run pytest tests/test_files_routes.py -v`
Expected: all 17 `test_patch_file_*` tests PASS unchanged. A route test
that patched a name inside `jidou.api.routes.files` which moved (for
example `jidou.api.routes.files.dismiss_orphans_for_file`) must be
re-pointed to `jidou.services.file_relink.<name>`. Find such targets with
`grep -n "routes.files\." tests/test_files_routes.py`.
In `tests/test_api_contract.py`, set `_API_MAX_COMPLEXITY = 14` and change
its comment to `# Current worst: shows.py discover_shows (14).`
Run: `uv run pytest tests/test_api_contract.py -v`. Expected: PASS.

- [ ] **Step 6: Commit and open PR 5**

```bash
git add src/jidou/services/file_relink.py tests/test_file_relink.py src/jidou/api/routes/files.py tests
git commit -m "refactor(api): move file relink invariants into services.file_relink"
```

Run `graphify update .`, bump the version, push, open PR 5, then follow the
Bugbot loop.

### Task 10: Discover feed service

**Files:**
- Create: `src/jidou/services/discover_feed.py`
- Test: `tests/test_discover_feed.py`
- Modify: `src/jidou/api/routes/shows.py`: move `_DISCOVER_SEED_LIMIT`,
  `_DISCOVER_PER_SHOW_LIMIT`, `_DISCOVER_CACHE_TTL` (with their comment
  block) and `_to_discover_result` into the service, and make
  `discover_shows` delegate.
- Modify: `tests/test_api_contract.py` (`_API_MAX_COMPLEXITY` 14 → 11)

**Interfaces:**
- Produces:
  `async def build_discover_feed(session: AsyncSession, tmdb: TMDBService, limit: int) -> list[DiscoverResult]`,
  plus `to_discover_result(raw: dict[str, Any], media_type: str, seeded_from: list[str]) -> DiscoverResult`
  (made public because it moved).

Before moving anything, run `grep -n "_to_discover_result\|_DISCOVER_" src/jidou/api/routes/shows.py`.
Expected: references only inside `discover_shows` and the definitions. If
`get_similar_shows` also uses `_to_discover_result`, import the public
`to_discover_result` from the service there.

- [ ] **Step 1: Write the failing stage tests**

```python
"""Unit tests for jidou.services.discover_feed."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from jidou.services.discover_feed import collect_seeded, fill_from_trending


def _seed(show_id: int, tmdb_id: int, title: str, media_type: str = "tv") -> MagicMock:
    entry = MagicMock()
    entry.show.id = show_id
    entry.show.tmdb_id = tmdb_id
    entry.show.title = title
    entry.show.media_type = media_type
    return entry


def test_collect_seeded_merges_seeded_from_and_skips_existing() -> None:
    tmdb = AsyncMock()
    tmdb.get_recommendations = AsyncMock(
        side_effect=[
            {"results": [{"id": 1}, {"id": 2}]},
            {"results": [{"id": 1}, {"id": 3}]},
        ]
    )
    seeded = asyncio.run(
        collect_seeded(tmdb, [_seed(10, 100, "A"), _seed(11, 101, "B")], existing={(3, "tv")})
    )
    assert set(seeded) == {(1, "tv"), (2, "tv")}
    assert seeded[(1, "tv")].seeded_from == ["A", "B"]


def test_collect_seeded_skips_non_tv_movie_and_failed_lookups() -> None:
    import httpx

    tmdb = AsyncMock()
    tmdb.get_recommendations = AsyncMock(
        side_effect=httpx.HTTPStatusError("boom", request=MagicMock(), response=MagicMock())
    )
    seeds = [_seed(10, 100, "A", media_type="person"), _seed(11, 101, "B")]
    assert asyncio.run(collect_seeded(tmdb, seeds, existing=set())) == {}
    tmdb.get_recommendations.assert_awaited_once()


def test_fill_from_trending_stops_at_limit_and_dedupes() -> None:
    tmdb = AsyncMock()
    tmdb.get_trending = AsyncMock(
        return_value={
            "results": [
                {"id": 1, "media_type": "tv"},
                {"id": 2, "media_type": "person"},
                {"id": 3, "media_type": "movie"},
                {"id": 4, "media_type": "tv"},
            ]
        }
    )
    results = asyncio.run(fill_from_trending(tmdb, [], {}, existing={(1, "tv")}, limit=1))
    assert [(r.id, r.media_type) for r in results] == [(3, "movie")]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_discover_feed.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the service**

Move the three `_DISCOVER_*` constants (and their explanatory comment
block) and `_to_discover_result` from `shows.py`, renamed to
`to_discover_result` with its docstring unchanged. Then add:

```python
"""Personalized discovery feed: watchlist-seeded TMDB recommendations + trending fill."""

import logging
from collections.abc import Sequence
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.models.show import Show
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus
from jidou.schemas.discover_schema import DiscoverResult
from jidou.services.cache import cache
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

_MEDIA_TYPES = frozenset({"movie", "tv"})
type _Key = tuple[int, str]

# (moved) _DISCOVER_SEED_LIMIT, _DISCOVER_PER_SHOW_LIMIT, _DISCOVER_CACHE_TTL + comments
# (moved) def to_discover_result(...)


async def build_discover_feed(
    session: AsyncSession, tmdb: TMDBService, limit: int
) -> list[DiscoverResult]:
    """Return the discovery feed, served from a 24h cache keyed by the seed set.

    Args:
        session: Active async DB session.
        tmdb: TMDB service.
        limit: Maximum results.

    Returns:
        Seeded results first (most seeds, then rating), then trending fill.
    """
    seed_entries = await _load_seed_entries(session)
    cache_key = cache.make_key(
        "discover:"
        + ",".join(sorted(f"{e.show.tmdb_id}:{e.show.media_type}" for e in seed_entries))
    )
    cached = await cache.get(cache_key)
    if cached is not None:
        return [DiscoverResult(**item) for item in cached][:limit]

    existing: set[_Key] = {
        (t, m) for t, m in (await session.execute(select(Show.tmdb_id, Show.media_type))).all()
    }
    seeded = await collect_seeded(tmdb, seed_entries, existing)
    results = sorted(seeded.values(), key=lambda r: (-len(r.seeded_from), -(r.vote_average or 0)))
    if len(results) < limit:
        results = await fill_from_trending(tmdb, results, seeded, existing, limit=limit)

    results = results[:limit]
    await cache.set(
        cache_key, [r.model_dump() for r in results], label="discover", ttl=_DISCOVER_CACHE_TTL
    )
    return results


async def _load_seed_entries(session: AsyncSession) -> Sequence[WatchlistEntry]:
    """Return the most recently updated watching/completed watchlist entries."""
    stmt = (
        select(WatchlistEntry)
        .where(WatchlistEntry.status.in_([WatchlistStatus.WATCHING, WatchlistStatus.COMPLETED]))
        .options(selectinload(WatchlistEntry.show))
        .order_by(WatchlistEntry.updated_at.desc())
        .limit(_DISCOVER_SEED_LIMIT)
    )
    return (await session.execute(stmt)).scalars().all()


async def collect_seeded(
    tmdb: TMDBService, seed_entries: Sequence[WatchlistEntry], existing: set[_Key]
) -> dict[_Key, DiscoverResult]:
    """Gather TMDB recommendations for each seed, merging ``seeded_from`` on repeats.

    Args:
        tmdb: TMDB service.
        seed_entries: Watchlist entries whose shows seed the feed.
        existing: ``(tmdb_id, media_type)`` keys already in the library.

    Returns:
        Results keyed by ``(tmdb_id, media_type)``.
    """
    seeded: dict[_Key, DiscoverResult] = {}
    for entry in seed_entries:
        show = entry.show
        if show.media_type not in _MEDIA_TYPES:
            continue
        try:
            data = await tmdb.get_recommendations(show.tmdb_id, show.media_type)
        except (ValueError, httpx.HTTPStatusError):
            logger.warning("Discover: recommendations failed for show_id=%d", show.id)
            continue
        for raw in data.get("results", [])[:_DISCOVER_PER_SHOW_LIMIT]:
            key = (raw["id"], show.media_type)
            if key in existing:
                continue
            if key in seeded:
                seeded[key].seeded_from.append(show.title)
            else:
                seeded[key] = to_discover_result(raw, show.media_type, [show.title])
    return seeded


async def fill_from_trending(
    tmdb: TMDBService,
    results: list[DiscoverResult],
    seeded: dict[_Key, DiscoverResult],
    existing: set[_Key],
    *,
    limit: int,
) -> list[DiscoverResult]:
    """Append weekly-trending items not already present until *limit* is reached.

    Args:
        tmdb: TMDB service.
        results: Seeded results so far (extended in place and returned).
        seeded: Keys already used (extended in place).
        existing: Library keys to exclude.
        limit: Target result count.

    Returns:
        *results*, extended.
    """
    try:
        trending = await tmdb.get_trending(media_type="multi", time_window="week")
    except (ValueError, httpx.HTTPStatusError):
        logger.warning("Discover: trending fallback failed")
        return results
    for raw in trending.get("results", []):
        media_type = raw.get("media_type")
        if media_type not in _MEDIA_TYPES:
            continue
        key = (raw["id"], media_type)
        if key in existing or key in seeded:
            continue
        seeded[key] = to_discover_result(raw, media_type, [])
        results.append(seeded[key])
        if len(results) >= limit:
            break
    return results
```

Order the module as: imports, logger, constants (`_MEDIA_TYPES`, `_Key`,
the moved `_DISCOVER_*`), `to_discover_result`, then the functions above.
Run `uv run ruff check --fix` on both new files so isort settles the import order.

- [ ] **Step 4: Delegate from the route**

Replace `discover_shows`'s body, after the docstring, with:

```python
    return await build_discover_feed(db_session, tmdb, limit)
```

Then import `build_discover_feed` and run
`uv run ruff check src/jidou/api/routes/shows.py --fix`.

- [ ] **Step 5: Verify and lower the ratchet**

Run: `uv run pytest tests/test_discover_feed.py tests/test_shows_routes.py -k "discover" -v`
Expected: PASS, including the 7 existing route-level `test_discover_*`
tests. They use `patch.object(cache, …)` on the shared `cache` object, so
they are unaffected by the move.
In `tests/test_api_contract.py`, set `_API_MAX_COMPLEXITY = 11` with the
comment `# Current worst: shows.py get_similar_shows (11), settings.py update_settings (11).`
Run: `uv run pytest tests/test_api_contract.py -v`. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/jidou/services/discover_feed.py tests/test_discover_feed.py src/jidou/api/routes/shows.py tests/test_api_contract.py
git commit -m "refactor(api): extract discover feed pipeline into services.discover_feed"
```

### Task 11: Table-driven settings PATCH

**Files:**
- Modify: `src/jidou/api/routes/settings.py`
- Modify: `tests/test_settings_routes.py` (append)

**Interfaces:**
- Produces: `_PATCH_FIELD_TO_KEY: Final[dict[str, str]]` in
  `jidou.api.routes.settings`.

- [ ] **Step 1: Write the failing completeness test**

Append to `tests/test_settings_routes.py`, at module level:

```python
def test_patch_field_map_covers_every_field() -> None:
    """Every AppSettingsPatch field maps to a settings key (a new field can't be silently dropped)."""
    from jidou.api.routes.settings import _PATCH_FIELD_TO_KEY
    from jidou.schemas.settings_schema import AppSettingsPatch

    assert set(_PATCH_FIELD_TO_KEY) == set(AppSettingsPatch.model_fields)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_settings_routes.py::test_patch_field_map_covers_every_field -v`
Expected: FAIL with `ImportError: cannot import name '_PATCH_FIELD_TO_KEY'`.

- [ ] **Step 3: Implement**

Add this after the imports in `settings.py` (add `from typing import Final`):

```python
# PATCH body field → persisted settings key. Iterated in this order.
_PATCH_FIELD_TO_KEY: Final[dict[str, str]] = {
    "show_adult_content": SHOW_ADULT_CONTENT,
    "calendar_enabled": CALENDAR_ENABLED,
    "discover_enabled": DISCOVER_ENABLED,
    "dashboard_page_enabled": DASHBOARD_PAGE_ENABLED,
    "recent_episodes_enabled": RECENT_EPISODES_ENABLED,
    "recent_movies_enabled": RECENT_MOVIES_ENABLED,
    "recent_episodes_prefer_posters": RECENT_EPISODES_PREFER_POSTERS,
    "similar_titles_enabled": SIMILAR_TITLES_ENABLED,
    "similar_titles_count": SIMILAR_TITLES_COUNT,
    "similar_titles_include_external": SIMILAR_TITLES_INCLUDE_EXTERNAL,
}
```

Replace the ten `if "<field>" in payload.model_fields_set:` blocks in
`update_settings` with:

```python
    changed = [f for f in _PATCH_FIELD_TO_KEY if f in payload.model_fields_set]
    for field in changed:
        await set_setting(db_session, _PATCH_FIELD_TO_KEY[field], getattr(payload, field))
    if changed:
        await db_session.flush()
```

Leave the `values = await get_all_settings(...)` and `return` lines as
they are.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_settings_routes.py tests/test_api_contract.py -v`
Expected: all PASS, including Task 3's `test_patch_all_fields_upserts_each_once`
and `test_patch_empty_body_writes_nothing`. If a pre-existing test asserts
an exact `flush` count greater than 1, update it to `assert_awaited_once()`.
Only the flush count changes (N flushes become 1): `set_setting` is an
upsert on distinct keys, so batching the flush does not change what gets
persisted. Note this in the PR.

- [ ] **Step 5: Commit and open PR 6**

```bash
git add src/jidou/api/routes/settings.py tests/test_settings_routes.py
git commit -m "refactor(api): make settings PATCH table-driven with a completeness test"
```

Run `graphify update .`, bump the version, push, open PR 6, then follow the
Bugbot loop.

### Task 12: Shared health probes (R5)

**Files:**
- Create: `src/jidou/services/health_probes.py`
- Test: `tests/test_health_probes.py`
- Modify: `src/jidou/api/routes/admin.py` (`system_health`, plus new
  private helpers `_read_alembic_version` and `_config_checks`)
- Modify: `src/jidou/api/health.py` (`health_check`)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True, slots=True) class ProbeResult(ok: bool, latency_ms: float, error: str | None = None, details: dict[str, Any] = {})`
    with `.as_dict() -> dict[str, Any]`
  - `class ProbeFailedError(Exception)`
  - `async def run_probe(check: Callable[[], Awaitable[dict[str, Any] | None]]) -> ProbeResult`
  - `async def ping_redis(url: str) -> None`

**Constraints:**
- Both response shapes stay exactly as they are.
- Each endpoint keeps its own Redis rule (spec §5).
- `admin.py` must keep reading `settings` and `celery_app` from its own
  module namespace, because 16 tests patch `jidou.api.routes.admin.settings`
  and `jidou.api.routes.admin.celery_app`.
- `ping_redis` must call `aioredis.from_url` at call time, because
  `conftest.py` patches `redis.asyncio.from_url`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for jidou.services.health_probes."""

import asyncio
from unittest.mock import AsyncMock, patch

from jidou.services.health_probes import ProbeFailedError, ProbeResult, ping_redis, run_probe


def test_run_probe_success_includes_details_and_latency() -> None:
    async def check() -> dict[str, object]:
        return {"workers": ["w1"]}

    result = asyncio.run(run_probe(check))
    assert result.ok is True
    assert result.latency_ms >= 0
    assert result.as_dict() == {"ok": True, "latency_ms": result.latency_ms, "workers": ["w1"]}


def test_run_probe_none_details_is_empty() -> None:
    async def check() -> None:
        return None

    assert asyncio.run(run_probe(check)).as_dict().keys() == {"ok", "latency_ms"}


def test_run_probe_exception_becomes_error_result() -> None:
    async def check() -> None:
        raise RuntimeError("db down")

    result = asyncio.run(run_probe(check))
    assert result.as_dict() == {"ok": False, "latency_ms": result.latency_ms, "error": "db down"}


def test_probe_failed_error_message_is_reported() -> None:
    async def check() -> None:
        raise ProbeFailedError("No Celery workers responded to ping")

    assert asyncio.run(run_probe(check)).error == "No Celery workers responded to ping"


def test_ping_redis_pings_and_always_closes() -> None:
    client = AsyncMock()
    client.ping = AsyncMock(side_effect=ConnectionError("refused"))
    with patch("redis.asyncio.from_url", return_value=client):
        result = asyncio.run(run_probe(lambda: ping_redis("redis://x")))
    assert result.ok is False
    client.aclose.assert_awaited_once()


def test_probe_result_is_frozen() -> None:
    r = ProbeResult(ok=True, latency_ms=1.0)
    try:
        r.ok = False  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ProbeResult must be immutable")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_health_probes.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
"""Timed, exception-safe dependency probes shared by the health endpoints."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis


class ProbeFailedError(Exception):
    """Raised by a probe check to report failure with a specific message."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of one dependency probe.

    Attributes:
        ok: Whether the dependency is usable.
        latency_ms: Wall time of the check, rounded to 0.1 ms.
        error: Failure message when ``ok`` is False.
        details: Extra fields merged into the serialized result on success.
    """

    ok: bool
    latency_ms: float
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialize as ``{"ok", "latency_ms", **details, ["error"]}``.

        Returns:
            JSON-ready dictionary.
        """
        out: dict[str, Any] = {"ok": self.ok, "latency_ms": self.latency_ms, **self.details}
        if self.error is not None:
            out["error"] = self.error
        return out


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 1)


async def run_probe(check: Callable[[], Awaitable[dict[str, Any] | None]]) -> ProbeResult:
    """Run *check*, timing it and converting any exception into a failed result.

    A health probe must report, never raise: every exception is captured as
    ``ProbeResult(ok=False, error=str(exc))``.

    Args:
        check: Zero-arg coroutine factory; may return extra detail fields.

    Returns:
        The probe result.
    """
    t0 = time.monotonic()
    try:
        details = await check()
    except Exception as exc:
        return ProbeResult(ok=False, latency_ms=_elapsed_ms(t0), error=str(exc))
    return ProbeResult(ok=True, latency_ms=_elapsed_ms(t0), details=details or {})


async def ping_redis(url: str) -> None:
    """PING the Redis server at *url*, always closing the client.

    Args:
        url: Redis connection URL.

    Raises:
        Exception: Whatever the client raises on connect or ping.
    """
    client = aioredis.from_url(url)
    try:
        await client.ping()
    finally:
        await client.aclose()
```

Run: `uv run pytest tests/test_health_probes.py -v`. Expected: PASS.

- [ ] **Step 4: Rewrite `admin.system_health`**

Add module-level helpers to `admin.py`, right above `system_health`. Copy
the TMDB, SFTP and LLM block verbatim from the current function:

```python
async def _read_alembic_version(db_session: AsyncSession) -> str | None:
    """Return the applied alembic revision, or None if it can't be read."""
    try:
        result = await db_session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("Could not read alembic_version: %s", exc)
        await db_session.rollback()
        return None


def _config_checks() -> dict[str, dict[str, Any]]:
    """Presence-only checks for TMDB, SFTP and LLM configuration (no network calls)."""
    results: dict[str, dict[str, Any]] = {
        "tmdb": {"ok": bool(settings.tmdb_api_key), "configured": bool(settings.tmdb_api_key)},
        "sftp": {"ok": bool(settings.sftp_host), "configured": bool(settings.sftp_host)},
    }
    if not settings.tmdb_api_key:
        results["tmdb"]["error"] = "TMDB_API_KEY not set"
    if not settings.sftp_host:
        results["sftp"]["error"] = "SFTP_HOST not set"
    llm_configured = settings.llm_provider.lower() != "none" and bool(settings.llm_model)
    results["llm"] = {"ok": True, "configured": llm_configured}
    if llm_configured:
        results["llm"]["provider"] = settings.llm_provider
        results["llm"]["model"] = settings.llm_model
    else:
        results["llm"]["error"] = (
            "LLM_MODEL not set" if settings.llm_provider.lower() != "none" else "not configured"
        )
    return results
```

Replace `system_health`'s body, after the docstring, with:

```python
async def check_database() -> dict[str, Any]:
    await db_session.execute(text("SELECT 1"))
    # Surface the applied migration revision so a stale schema after a deploy
    # is visible here instead of only showing up as a downstream 500.
    return {"alembic_version": await _read_alembic_version(db_session)}


async def check_celery() -> dict[str, Any]:
    # A reachable broker doesn't prove a worker is consuming; ping workers directly.
    pong = await asyncio.to_thread(celery_app.control.inspect(timeout=2.0).ping)
    if not pong:
        raise ProbeFailedError("No Celery workers responded to ping")
    return {"workers": list(pong.keys())}


redis_url = settings.redis_url
results: dict[str, Any] = {
    "database": (await run_probe(check_database)).as_dict(),
    # Redis is optional here: unconfigured must not drag overall health to false.
    "redis": (
        (await run_probe(lambda: ping_redis(redis_url))).as_dict()
        if redis_url
        else {"ok": True, "configured": False}
    ),
    "celery": (await run_probe(check_celery)).as_dict(),
    **_config_checks(),
}
overall = all(v.get("ok") for v in results.values())
return {"healthy": overall, "version": __version__, "services": results}
```

Import `ProbeFailedError`, `ping_redis` and `run_probe` from
`jidou.services.health_probes`. Remove the `time` import if unused.

- [ ] **Step 5: Rewrite `health.health_check`**

Replace the Postgres and Redis blocks, from `services: dict…` through the
Redis `except` block, with the following. Keep the TMDB, SFTP, `body` and
`JSONResponse` parts unchanged.

```python
services: dict[str, dict[str, Any]] = {}


async def check_postgres() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


probes = {
    "postgres": await run_probe(check_postgres),
    # Redis is required for this probe (Docker HEALTHCHECK): failure → 503.
    "redis": await run_probe(lambda: ping_redis(settings.redis_url)),
}
for name, result in probes.items():
    if result.ok:
        services[name] = {"status": "healthy"}
    else:
        logger.error("%s health check failed: %s", name, result.error)
        services[name] = {"status": "unhealthy", "error": result.error or ""}
overall_healthy = all(r.ok for r in probes.values())
```

Remove the now-unused `import redis.asyncio as aioredis`. The separate
"Redis client creation failed" log line merges into the generic one. Note
this in the PR.

- [ ] **Step 6: Verify**

Run: `grep -n "patch(" tests/test_health.py | grep -v "redis.asyncio.from_url"`
For any target that patched `jidou.api.health.aioredis…`, re-point it to
`redis.asyncio.from_url`.
Run: `uv run pytest tests/test_health.py tests/test_admin_routes.py tests/test_health_probes.py tests/test_api_contract.py -v`
Expected: PASS. The 18 health tests are unchanged except for re-pointed
patch targets.

- [ ] **Step 7: Commit and open PR 7**

```bash
git add src/jidou/services/health_probes.py tests/test_health_probes.py src/jidou/api tests
git commit -m "refactor(api): share timed dependency probes between health endpoints"
```

Run `graphify update .`, bump the version, push, open PR 7, then follow the
Bugbot loop.

---

## Phase 4 — Split the oversized route modules

**Rules for both tasks:**
- Move whole functions **verbatim**: decorator, signature, docstring, body.
  Do not edit them.
- Each new module declares
  `router = APIRouter(prefix="<same prefix>", tags=["<same tag>"])`, so
  OpenAPI tags and paths do not change.
- Endpoint function names stay as they are, because operation IDs (and so
  `frontend/src/types/api-generated.ts`) derive from them.
- Within a module, keep the original relative order of endpoints.
- A private helper moves with its only user. If two new modules need it,
  put it in a new `_<area>_common.py` module in `routes/` and import it
  from both.
- After moving, every `patch("jidou.api.routes.shows.<name>")` or
  `patch("jidou.api.routes.rss.<name>")` in `tests/` must point at the
  module that now imports `<name>`. List them with
  `grep -rhoE "jidou\.api\.routes\.(shows|rss)\.[A-Za-z_]+" tests | sort | uniq -c`.

### Task 13: Split `shows.py`

**Files:**
- Create: `src/jidou/api/routes/tmdb_proxy.py` (prefix `/shows`, tag `shows`)
- Create: `src/jidou/api/routes/show_episodes.py` (prefix `/shows`, tag `shows`)
- Create: `src/jidou/api/routes/show_local_files.py` (prefix `/shows`, tag `shows`)
- Modify: `src/jidou/api/routes/shows.py` (what remains), `src/jidou/main.py`
- Modify: test files whose patch targets move

**Endpoint assignment (by path, under `/shows`):**

| Module | Endpoints |
|---|---|
| `tmdb_proxy.py` | `GET /tmdb/trending`, `GET /tmdb/search`, `GET /tmdb/{tmdb_id:int}`, `GET /tmdb/discover` |
| `shows.py` (remains) | `GET /search`, `GET ""`, `GET /calendar`, `POST /calendar/sync-missing`, `POST ""`, `GET /{show_id}`, `GET /{show_id}/similar`, `GET /{show_id}/images/posters`, `GET /{show_id}/images/backdrops`, `PUT /{show_id}/paths`, `PUT /{show_id}/aliases`, `POST /{show_id}/aliases/regenerate`, `DELETE /{show_id}`, `PATCH /{show_id}`, `POST /{show_id}/rematch`, `POST /{show_id}/sync-episodes`, `GET /{show_id}/episode-groups`, `POST /{show_id}/episode-groups/{group_id}/apply`, `POST /{show_id}/rss-stub` |
| `show_episodes.py` | `GET /{show_id}/episodes`, `POST`/`DELETE /{show_id}/episodes/{episode_id}/watched`, `POST`/`DELETE /{show_id}/episodes/watched`, `POST /{show_id}/episodes/{episode_id}/begin-rematch`, `DELETE /{show_id}/episodes/{episode_id}/tracking`, `POST /{show_id}/episodes/{episode_id}/assign-import`, `POST /{show_id}/episodes/{episode_id}/link-file`, plus helpers `_get_episode_or_404`, `_get_show_episodes_or_404`, `_detach_episode_tracking`, `_resync_synthetic_file_episode` |
| `show_local_files.py` | `POST /{show_id}/scan-local-files`, `POST /{show_id}/scan-local-movie-file`, `POST /{show_id}/link-movie-file` |

- [ ] **Step 1: Create the three modules and move the endpoints**

Move each group in the table verbatim, together with the imports each
group needs. Then run:
`uv run ruff check src/jidou/api/routes --fix && uv run ruff format src/jidou/api/routes`

- [ ] **Step 2: Register the routers in this exact order in `main.py`**

Replace the single `shows.router` line with:

```python
    app.include_router(tmdb_proxy.router, prefix="/api", dependencies=_auth)
    app.include_router(shows.router, prefix="/api", dependencies=_auth)
    app.include_router(show_episodes.router, prefix="/api", dependencies=_auth)
    app.include_router(show_local_files.router, prefix="/api", dependencies=_auth)
```

`tmdb_proxy` must come first. Today the `/tmdb/*` literals are registered
before `/{show_id}`, and `/tmdb/{tmdb_id:int}` has to stay ahead of the
parameterized show routes. Add the three module names to the existing
`from jidou.api.routes import …` statement in `main.py`.

- [ ] **Step 3: Re-point the moved patch targets**

For each name reported by the grep in the Phase 4 rules, find its new
owner with `grep -ln "<name>" src/jidou/api/routes/*.py`, then update the
test strings. In particular, `match_entry_to_episode` (8 uses) moves with
whichever endpoint calls it.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_api_contract.py -v`
Expected: PASS. This proves the OpenAPI document is unchanged and no
literal route is shadowed.
Run: `uv run pytest -q && uv run mypy src/`. Expected: PASS.
Run: `wc -l src/jidou/api/routes/{shows,tmdb_proxy,show_episodes,show_local_files}.py`.
Expected: no file above about 1,100 lines.

- [ ] **Step 5: Commit**

```bash
git add src/jidou/api/routes src/jidou/main.py tests
git commit -m "refactor(api): split shows routes into tmdb_proxy, show_episodes and show_local_files"
```

### Task 14: Split `rss.py`

**Files:**
- Create: `src/jidou/api/routes/rss_feeds.py`, `rss_subscriptions.py`,
  `rss_publish.py` (each with prefix `/rss`, tag `rss`)
- Delete: `src/jidou/api/routes/rss.py`
- Modify: `src/jidou/main.py`, plus tests patching
  `jidou.api.routes.rss.*` (`settings` ×6, `find_show_by_name` ×4,
  `FeedOnboardingOrchestrator` ×1)

**Endpoint assignment (by path, under `/rss`):**

| Module | Endpoints, in this order |
|---|---|
| `rss_feeds.py` | `GET /feeds`, `POST /feeds`, `PATCH /feeds/{feed_id}`, `DELETE /feeds/{feed_id}`, `GET /feeds/{feed_id}/entries`, `POST /feeds/{feed_id}/suggest-regex`, `POST /feeds/{feed_id}/test-regex`, `POST /feeds/{feed_id}/add-show`, plus `_get_feed_or_404`, `_feed_group_or_http_error` |
| `rss_subscriptions.py` | `GET /subscriptions`, `POST /subscriptions`, `GET /subscriptions/recommendations`, `PATCH /subscriptions/bulk`, `GET /subscriptions/{sub_id}`, `PATCH /subscriptions/{sub_id}`, `DELETE /subscriptions/{sub_id}`, `POST /subscriptions/{sub_id}/suggest-regex`, `GET /subscriptions/{sub_id}/preview`, plus `_sub_stmt` |
| `rss_publish.py` | `GET /download`, `GET /diff`, `GET /snapshots`, `GET /snapshots/{snapshot_id}`, `POST /import`, `POST /publish` |

`/subscriptions/recommendations` and `/subscriptions/bulk` must stay above
`/subscriptions/{sub_id}`. Task 1's shadowing test enforces this.
`_match_report_read` goes to whichever module uses it. If both feeds and
subscriptions use it, put it in `routes/_rss_common.py`. `rss_subscriptions.py`
needs `_get_feed_or_404` for its body `feed_id` checks: import it from
`rss_feeds` (a route module importing a private helper from a sibling
route module is acceptable within one resource area), or move it to
`_rss_common.py`. Prefer `_rss_common.py`.

- [ ] **Step 1: Create the modules, move the endpoints and delete `rss.py`**

Run: `uv run ruff check src/jidou/api/routes --fix && uv run ruff format src/jidou/api/routes`

- [ ] **Step 2: Register the routers in `main.py`**

Replace the `rss.router` line with:

```python
    app.include_router(rss_feeds.router, prefix="/api", dependencies=_auth)
    app.include_router(rss_subscriptions.router, prefix="/api", dependencies=_auth)
    app.include_router(rss_publish.router, prefix="/api", dependencies=_auth)
```

- [ ] **Step 3: Re-point the patch targets**

Update the `jidou.api.routes.rss.<name>` strings to the new owning
modules. `settings` is imported by every module that reads it, so patch
the module the test's endpoint now lives in.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_api_contract.py -v && uv run pytest -q && uv run mypy src/`
Expected: PASS, with the OpenAPI document unchanged.

- [ ] **Step 5: Commit**

```bash
git add -A src/jidou/api/routes src/jidou/main.py tests
git commit -m "refactor(api): split rss routes into feeds, subscriptions and publish modules"
```

### Task 15: Final verification and docs check

**Files:**
- Modify: `CHANGELOG.md`, only if the repo records internal refactors there
  (check the recent entries first)

- [ ] **Step 1: Run the full CI-equivalent pass**

Run, in order:
1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run mypy src/`
4. `uv run bandit -r src/ -l`
5. `uv run pytest --cov=src`

Expected: all pass, and coverage for `src/jidou/api` is no lower than the
Phase 0 baseline. Record the baseline in PR 1's description.

- [ ] **Step 2: Confirm the structural outcomes**

| Command | Expected |
|---|---|
| `grep -rn "from jidou.api.routes" src/jidou/api/routes` | no output (no route-to-route imports) |
| `grep -c '"Show not found"' src/jidou/api/routes/*.py` | only `lookups.py` defines it; routes show `0` |
| `uv run ruff check src/jidou/api --select C901 --config lint.mccabe.max-complexity=11` | pass |

- [ ] **Step 3: Check the docs**

Dispatch the `docs-consistency-reviewer` agent with: "API routes moved
between modules (shows → tmdb_proxy / show_episodes / show_local_files;
rss → rss_feeds / rss_subscriptions / rss_publish) with no path or
behavior change; health endpoints now share services.health_probes. Check
docs/*.md, DESIGN.md and CHANGELOG.md for stale module references."
Fix any stale references it reports.

- [ ] **Step 4: Update graphify, commit, and open PR 8**

```bash
graphify update .
git add -A
git commit -m "docs: update module references after API route split"
```

Bump the version, push, open PR 8, then follow the Bugbot loop.

---

## Deferred to the merged app-wide plan

Not in this plan. Each needs code that this analysis did not fully read:

- **R8:** `LocalFileScanService`, unifying `scan-local-files` and
  `scan-local-movie-file`.
- **The rest of R9:** link/unlink invariants in `orphans.py` (restore from
  orphan snapshot) and `shows.py` (`assign-import` swap/displace,
  `link-file`, `link-movie-file`). These have swap and restore semantics
  that `file_relink` does not model yet.
- **`get_similar_shows`** (complexity 11): extract the merge/rank into a
  pure function. After that, lower the ratchet to 10.
- **`StatsQueryService`:** the 18 read queries in `admin.py` and the
  dashboard queries.
- **Spec §5 decisions:** the Redis-required divergence between the two
  health endpoints, the possibly stale tracking left by a show-only
  `patch_file`, and unifying the 503 `detail` strings.
