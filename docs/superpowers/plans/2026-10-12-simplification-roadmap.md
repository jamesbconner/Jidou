# Jidou Simplification Roadmap (merged)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. This roadmap does **not** repeat task steps. Each roadmap item points at a PR in one of the seven layer plans, which holds the exact files, interfaces, tests and commands. Execute the items in the order of §4, running independent items in parallel sub-agents per §4A, after applying the reconciliations in §3 to the layer plans.

**Goal:** Carry out the seven per-layer simplification plans as one ordered
program of 77 PRs: the 54 layer PRs, 3 cross-layer items and 20 decision follow-ups. The program resolves the overlaps between the plans,
keeps every layer's behavior guards in force, and asks for an explicit
decision wherever a plan would otherwise change behavior.

**Architecture:**
- **Wave 0** installs every layer's safety net before any refactor: the
  complexity ratchets, the OpenAPI snapshot, the `alembic check` gate,
  golden tests, and characterization tests.
- **Wave 1** builds the shared foundations that later PRs import: typed
  task status, single-flight, `EventSink`, the task harness entrypoint,
  and the frontend hooks boundary.
- **Waves 2–3** run the layer refactors in dependency order. The API
  route-module split (API-8) is the hinge between them.
- **Wave 4** finishes each layer.
- **Wave 5** applies the approved behavior changes from the decision
  register (§7) as small, separately reviewable PRs, then verifies the
  whole repository (XL-3).

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2 / Alembic / Celery /
Pydantic v2 / pytest / ruff / mypy (strict) / uv; React 19 / TypeScript 6 /
TanStack Query 5 / Vite 8 / Vitest / ESLint 9.

**Sources** (the specs carry the analysis; the plans carry the tasks):

| Layer | Spec | Plan | PRs | Prefix |
|---|---|---|---|---|
| API | `specs/2026-10-11-api-simplification-design.md` | `plans/2026-10-11-api-simplification.md` | 8 | `API-n` |
| Services | `specs/2026-10-11-services-simplification-design.md` | `plans/2026-10-11-services-simplification.md` | 9 | `SVC-n` |
| Orchestrators | `specs/2026-10-11-orchestrators-simplification-design.md` | `plans/2026-10-11-orchestrators-simplification.md` | 12 | `ORC-n` |
| Workers | `specs/2026-10-11-workers-simplification-design.md` | `plans/2026-10-11-workers-simplification.md` | 6 | `WRK-n` |
| Models | `specs/2026-10-11-models-simplification-design.md` | `plans/2026-10-11-models-simplification.md` | 6 | `MDL-n` |
| Schemas | `specs/2026-10-11-schemas-simplification-design.md` | `plans/2026-10-11-schemas-simplification.md` | 5 | `SCH-n` |
| Frontend | `specs/2026-10-11-frontend-simplification-design.md` | `plans/2026-10-11-frontend-simplification.md` | 8 | `FE-n` |
| Cross-layer | this document, §5 | this document, §5 | 3 | `XL-n` |

`<PREFIX>-n` always means **PR n** in that layer plan's "PR grouping"
table, not task n. Every path above is relative to `docs/superpowers/`.

---

## 1. Global Constraints (apply to every PR)

These combine the constraints of all seven plans with the repository's
own process rules, which the API plan and the earlier
`2026-10-09-rss-regex-samples` plan already follow. Where the plans
disagree, this section wins.

- **No behavior change** unless the PR is listed in §6 (approved behavior
  changes), or carries an approved decision from §7.
- **The guards are the contract.** Once Wave 0 has merged, every PR must
  keep all of these green:
  - the six complexity ratchets (§8), which only ever go down;
  - the API's OpenAPI snapshot (`tests/test_api_contract.py`);
  - `alembic check` in CI;
  - the services and orchestrators layering guards, the workers include
    and visibility-timeout guards, and the models schema guards;
  - the existing backend and frontend test suites, with no edits to
    existing assertions except where a layer plan explicitly allows
    one.
- **No backward-compatibility shims.** When a name moves, update every
  importer and every `patch("…")` target. Do not re-export from the old
  location.
- **Pre-push checks.** Backend: `uv run ruff check .` →
  `uv run ruff format --check .` → `uv run mypy src/` →
  `uv run bandit -r src/ -l` → `uv run pytest`, plus `alembic check` when
  `models/` or `alembic/` changed. Frontend (when `frontend/` changed):
  `npm run lint` → `npx tsc -b` → `npm test` → `npm run build`, on
  Node ≥ 24.
- **After code changes:** run `graphify update .`.
- **Git and PRs:**
  - Never commit to `main`.
  - One branch and one PR per roadmap item, using the branch names in
    the layer plans.
  - Merge with `--merge`.
  - **Parallel execution (D2, decided):** independent items run
    concurrently in sub-agents, following the rules in §4A. Merges into
    `main` are still one at a time.
  - After each push, poll `gh pr checks` every 60 s (at most 10 times)
    for Cursor Bugbot, and address its comments before the PR is merged.
  - **Version bumps (D1, decided):** item PRs do **not** bump the
    version. Ignore the "ends with a version-bump commit" line in every
    layer plan (reconciliation R10). One release PR per wave bumps it
    (§4A).
- **PR and commit text:**
  - Use generic placeholder paths and titles, never real library paths.
  - Never include a claude.ai session link.
  - End every commit with
    `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## 2. Program map

```
Wave 0  Guards ............ API-1  MDL-1  SVC-1  ORC-1  WRK-1  FE-1
Wave 1  Foundations ....... MDL-2  ORC-2  WRK-2  SVC-2  SVC-3  API-2  API-3  SCH-1  FE-2
Wave 2  Layer refactors ... API-4  XL-1  API-5  API-6  API-7  SVC-4  SVC-5  SVC-6  MDL-3  MDL-4  MDL-5
                            WRK-3  WRK-4  ORC-4  ORC-5  ORC-6  ORC-9  ORC-10  SCH-2  SCH-3  FE-3..FE-6
Wave 3  Route split + deps  API-8  SVC-7  SVC-8  SVC-9  ORC-3  ORC-7  ORC-8  XL-2  ORC-11  WRK-5  SCH-4
Wave 4  Closeout .......... ORC-12  WRK-6  MDL-6  FE-7  FE-8  SCH-5
Wave 5  Decisions ......... DF-1 … DF-20 (approved behavior changes, §5A), then XL-3
```

Why this order:

- **Guards go first.** Nothing is refactored before its guard exists.
- **`MDL-2` leads Wave 1.** The typed `TaskStatus` and the shared
  status sets are imported by the API, services, workers and schemas
  PRs that follow, so they need one home first (§3, R1).
- **`ORC-2` comes before `WRK-2`.** That lets the worker harness alias
  the shared `OnEvent` / `OnProgress` types straight away (§3, R4).
- **`MDL-4` comes before `WRK-4`.** The backup restore then takes its
  `Show` column list from the models instead of a 40-name hand-written
  list (§3, R2).
- **`API-8` opens Wave 3.** `SVC-7`, `SVC-8`, `ORC-8`, `ORC-11` and
  `XL-2` all edit the split route modules or build on code they move.

## 3. Reconciliations (edits to the layer plans before executing them)

Each reconciliation overrides the named layer-plan task. Apply it while
executing that task; the layer plan files themselves are not rewritten.

| # | Overlap | Resolution | Affects |
|---|---|---|---|
| R1 | Task-status sets have three proposed homes: services Task 14 (`progress.TERMINAL_STATUSES`), workers Task 6 (W8 imports it), and models Task 3 (`models/task.py`) | **The single home is `models/task.py: ACTIVE_TASK_STATUSES, TERMINAL_TASK_STATUSES` (MDL-2).** Services Task 14 drops its `TERMINAL_STATUSES` bullet and imports from models. Workers Task 6 imports from models. MDL-2 no longer waits for SVC-9 or WRK-5; it runs first. The frontend's `TERMINAL_TASK_STATUSES` (FE-2) stays a separate TypeScript constant. | MDL-2, SVC-9, WRK-5 |
| R2 | The `Show` column list is re-stated in models Task 5 (`show_columns()`) and in workers Task 5 (`_SHOW_COLUMNS`) | Workers Task 5 builds `_SHOW_COLUMNS` from `show_columns("tmdb", "user", "derived", …)` plus the existing per-column defaults and converters. MDL-4 merges first. | MDL-4 → WRK-4 |
| R3 | `services/progress.py` is pulled three ways: API Task 8 creates `services/task_dispatch.py`, the services plan defers moving `enqueue_task` / `TaskDispatchError` / `get_active_task`, and workers Task 2 moves `mark_task_timed_out` | **XL-1** (§5) moves `enqueue_task`, `TaskDispatchError` and `get_active_task` into `services/task_dispatch.py`, right after API-4. Workers Task 2 still moves `mark_task_timed_out` into `workers/_harness.py`. After both, `progress.py` holds only progress emission and the task-record state machine. | API-4, XL-1, WRK-2 |
| R4 | There are two callback-type vocabularies: `services/callbacks.OnEvent/OnProgress` (orchestrators Task 2) and `_harness.ProgressFn/EventFn` (workers) | Workers Task 2 adds `ProgressFn = OnProgress` and `EventFn = OnEvent` as aliases imported from `services/callbacks`. ORC-2 merges first. | ORC-2 → WRK-2 |
| R5 | `RegexSuggestionError(status_code, …)` (services deferred item L3) duplicates what orchestrators Task 9's `OrchestratorError` handler does | **XL-2** (§5) changes it to raise `InvalidRequestError` (422, "not configured") and `UpstreamError` (503 must stay 503, so XL-2 adds `ServiceUnavailableError` → 503 to the handler table), and deletes the route-level re-raise. | ORC-8 → XL-2 |
| R6 | Two plans touch `AppSettingsPatch`: API Task 11 (table-driven PATCH) and schemas Task 4 (shared bounds) | Either order works. API-6 merges first because it is in Wave 2 with an earlier position. | API-6, SCH-2 |
| R7 | Frontend types can be regenerated by several PRs | Only SCH-3, SCH-4 and SCH-5 regenerate `api-generated.ts`. FE-8 runs after them and deletes the overrides they make redundant (see D16). | SCH-3/4/5 → FE-8 |
| R8 | The process rules (Bugbot, placeholder paths, no session links) appear only in the API plan | §1 applies them to every layer plan. | all |
| R9 | `alias_orchestrator` adopts `json_schema_format` (orchestrators Task 14) but not `request_json_object`, because it accepts a bare list | Confirmed; no change. Services Task 5 must leave `llm_json.json_schema_format` public. | SVC-3, ORC-12 |
| R10 | Every layer plan says "each PR ends with a version-bump commit" | **Overridden by D1:** no item PR bumps the version. The release PR at the end of each wave (§4A) does it. This also removes the guaranteed merge conflict that parallel PRs would otherwise have on `pyproject.toml`, `src/jidou/__init__.py`, `frontend/package.json` and `uv.lock`. | all |

## 4. Execution order (77 items)

The **Needs** column lists hard prerequisites; everything earlier in the
table also comes first. **Kind** is: `guard` (adds tests and gates
only), `refactor` (no behavior change), `contract` (OpenAPI changes, no
JSON value changes), or `behavior` (approved; listed in §6).

### Wave 0 — Guards

| # | Item | What it delivers | Needs | Kind |
|---|---|---|---|---|
| 1 | API-1 | OpenAPI snapshot, route-shadowing guard, API ratchet (16), hotspot characterization tests | — | guard |
| 2 | MDL-1 | Declares the hand-written indexes; `alembic check` CI gate | — | guard |
| 3 | SVC-1 | Services ratchet (17), layering guard, `_parse_episode` golden table | — | guard |
| 4 | ORC-1 | Orchestrators ratchet (28), FastAPI and private-import guards, event-failure pins | — | guard |
| 5 | WRK-1 | Workers ratchet (16), include-list guard, visibility-timeout invariant, golden summaries | — | guard |
| 6 | FE-1 | ESLint complexity ratchet (92); `ensureOk` client test | — | guard |

### Wave 1 — Foundations

| # | Item | What it delivers | Needs | Kind |
|---|---|---|---|---|
| 7 | MDL-2 | `str_enum`; typed `BackgroundTask.status`; **the** status sets (R1) | MDL-1 | refactor |
| 8 | ORC-2 | `EventSink`; `services/callbacks.OnEvent/OnProgress` | ORC-1 | refactor |
| 9 | WRK-2 | `run_harnessed`; `task_sessionmaker`; callback aliases (R4) | WRK-1, ORC-2 | refactor |
| 10 | SVC-2 | `ElectedSingleFlight` for TMDB and LLM; provider dispatch | SVC-1 | refactor |
| 11 | SVC-3 | Structured LLM calls; episode lookup consolidation (**S7 fix**) | SVC-2 | behavior (B1) |
| 12 | API-2 | `get_tmdb` moved into `dependencies.py` | API-1 | refactor |
| 13 | API-3 | `api/lookups.py` and the lookup migrations | API-1 | refactor |
| 14 | SCH-1 | Dead schemas deleted; `RegexPattern` type | API-1 | refactor |
| 15 | FE-2 | `useConfig`, `useTaskUntilDone`, invalidation helpers, hooks boundary lint | FE-1 | behavior (B2) |

### Wave 2 — Layer refactors

| # | Item | What it delivers | Needs | Kind |
|---|---|---|---|---|
| 16 | API-4 | Task dispatch service and `TASK_REGISTRY` | API-1 | refactor |
| 17 | XL-1 | Dissolve the dispatch half of `progress.py` (R3) | API-4, WRK-2 | refactor |
| 18 | API-5 | `file_relink` service; `patch_file` made thin | API-1 | refactor |
| 19 | API-6 | Discover feed service; table-driven settings PATCH | API-1 | refactor |
| 20 | API-7 | Shared health probes | API-1 | refactor |
| 21 | SVC-4 | `path_parser` rule table and walker | SVC-1 | refactor |
| 22 | SVC-5 | SFTP entry classifier | SVC-1 | refactor |
| 23 | SVC-6 | `redis_session`; pubsub dependency injection | SVC-1 | refactor |
| 24 | MDL-3 | Typed vocabularies (`ContentType`, `TrackedSource`, `SnapshotType`), after the data check | MDL-2 | refactor (precondition P1) |
| 25 | MDL-4 | `Show` column provenance | MDL-1 | refactor |
| 26 | MDL-5 | Episode lookup indexes (migration) | MDL-1 | behavior (B3) |
| 27 | WRK-3 | `create_sftp_service`; `summarize` | WRK-2 | refactor |
| 28 | WRK-4 | Table-driven backup restore (R2) | WRK-2, MDL-4 | refactor |
| 29 | ORC-4 | Scan/seed discovery shared | ORC-2 | refactor |
| 30 | ORC-5 | Route and parse as per-item commands | ORC-2 | refactor |
| 31 | ORC-6 | Download decomposition | ORC-2 | refactor |
| 32 | ORC-9 | TMDB episode upsert batching | ORC-2 | refactor |
| 33 | ORC-10 | RSS import/publish split | ORC-2 | refactor |
| 34 | SCH-2 | `ORMModel`; shared bounds; task-type guard; status coercion removed | SCH-1, MDL-2 | refactor |
| 35 | SCH-3 | Distinct `FileShowBrief` / `WatchlistShowBrief` names; types regenerated | SCH-1 | contract |
| 36–39 | FE-3, FE-4, FE-5, FE-6 | Splits of `Settings`, `ShowDetail`, `Shows`, `ResolveFileModal` | FE-2 | refactor |

### Wave 3 — The route split and what depends on it

| # | Item | What it delivers | Needs | Kind |
|---|---|---|---|---|
| 40 | API-8 | `shows.py` / `rss.py` split into sub-resource modules; API ratchet → 11 | API-2…7 | refactor |
| 41 | SVC-7 | `get_or_create_show_from_tmdb` moved into orchestrators | SVC-1, API-8 | refactor |
| 42 | SVC-8 | Shared YaRSS2 filter; synthetic-import helpers; `basename_any` | API-8 | refactor |
| 43 | SVC-9 | TMDB surface; small dedupes (R1 applied) | SVC-2, MDL-2 | refactor |
| 44 | ORC-3 | Show-provisioning primitives | ORC-2, SVC-7 | refactor |
| 45 | ORC-7 | Sync phases; `link_file_to_episode` | ORC-5 | refactor |
| 46 | ORC-8 | Domain errors with one HTTP handler; TMDB injected into manual match | ORC-3, API-8 | refactor (status codes and bodies unchanged) |
| 47 | XL-2 | `RegexSuggestionError` moved onto the domain errors (R5) | ORC-8, SVC-8 | refactor |
| 48 | ORC-11 | Path import decomposition | ORC-3, SVC-8 | refactor |
| 49 | WRK-5 | Scheduled-task table; harness `_finish`; unused loggers and default arguments removed (the trending task is **kept**, see jamesbconner/Jidou#655) | WRK-2, MDL-2 | refactor |
| 50 | SCH-4 | Response vocabularies typed as enums; types regenerated | SCH-1, MDL-3 | contract |

### Wave 4 — Closeout

| # | Item | What it delivers | Needs | Kind |
|---|---|---|---|---|
| 51 | ORC-12 | Lazy imports removed; fuzzy matcher; alias schema; ratchet → 10 | all ORC, SVC-3, SVC-8 | refactor |
| 52 | WRK-6 | Redis try-lock; `library_root`; long-task limits; ratchet → 8 | all WRK, SVC-6 | refactor |
| 53 | MDL-6 | Registration imports; redundant `nullable` removed | MDL-1 | refactor |
| 54 | FE-7 | Remaining hotspots; ratchet → 25 | FE-3…6 | refactor |
| 55 | FE-8 | Dead types; `ContentType` alias; overrides removed per R7 | FE-7, SCH-1, SCH-3, SCH-4 | refactor |
| 56 | SCH-5 | Request vocabularies typed as enums (**D11 approved**) | SCH-1 | behavior (B4) |

### Wave 5 — Approved decisions, then closeout

Each DF item is specified in §5A. Waves 0–4 stay behavior-preserving;
every approved behavior change lands here, on top of the guards and
refactors it depends on.

| # | Item | Decision | What it changes | Needs | Kind |
|---|---|---|---|---|---|
| 57 | DF-1 | D7 | One 503 dispatch message: `"Task broker unavailable"` | API-4 | behavior |
| 58 | DF-2 | D12 | `patch_file` clears tracking left on the old episode | API-5 | behavior |
| 59 | DF-3 | D9 | `/api/admin/health` treats Redis as required, like `/api/health` | API-7 | behavior |
| 60 | DF-4 | D25 | Explicit eager loading for `FileRead`, then `lazy="raise"` | API-8 | refactor, then behavior |
| 61 | DF-5 | D19 | Bulk import accepts `.iso` / `.av1` / `.ogm` | SVC-4 | behavior |
| 62 | DF-6 | D20 + D21 | 4-digit episode numbers everywhere; one shared resolution/quality token list | SVC-4, DF-5 | behavior |
| 63 | DF-7 | D13 | Event-logging failures never abort work | ORC-12 | behavior |
| 64 | DF-8 | D14 | Show-creation race recovery by `tmdb_id`, plus `ensure_episode_group_map` | ORC-3, ORC-11 | behavior |
| 65 | DF-9 | D15 | One name-agreement rule | ORC-11 | behavior |
| 66 | DF-10 | D16 | One `local_path` auto-population helper | ORC-11 | behavior |
| 67 | DF-11 | D17 | `sync(show_id=…)` warns about a missing show | ORC-7 | behavior |
| 68 | DF-12 | D18 | Duplicate exact titles are ambiguous in both fuzzy matchers | ORC-12 | behavior |
| 69 | DF-13 | D33 | Duplicate files for one episode are flagged (migration) | ORC-5, MDL-5 | behavior + contract |
| 70 | DF-14 | D29 | The API's SFTP connection test uses `create_sftp_service` | WRK-3 | refactor |
| 71 | DF-15 | D30 | Harness `set_progress_total` callback | WRK-6 | refactor |
| 72 | DF-16 | D6 | A dedicated show-creation input model | SVC-7, ORC-3 | refactor |
| 73 | DF-17 | D5 | Typed TMDB sub-objects; matching `api.ts` overrides removed | SCH-4, FE-8 | contract |
| 74 | DF-18 | D10 | `GET /shows/index` for pickers and the library index | API-8, FE-7 | behavior + contract |
| 75 | DF-19 | D8 | CI fails on frontend type drift | SCH-3 | guard |
| 76 | DF-20 | D4 | `extra="forbid"` on request bodies | DF-16, DF-17, DF-18 | behavior |
| 77 | XL-3 | — | Repository-wide verification and documentation (§5), including D32's Node note | everything above | guard |

## 4A. Parallel execution with sub-agents (D2)

**Method:** the main session acts as the **coordinator**. For each item
it dispatches one sub-agent that runs
`superpowers:subagent-driven-development` on that item's layer-plan
section: a fresh implementer, then a fresh reviewer. Independent items
are dispatched together (`superpowers:dispatching-parallel-agents`).

**What each sub-agent gets:**
- its own git worktree (`isolation: "worktree"`), branched from the
  current `main`;
- this roadmap's §1 (Global Constraints);
- the reconciliations from §3 that name its item;
- its layer plan's Global Constraints and the item's tasks.

It must not read or change another item's branch.

### Rules for running items at the same time

Two items may run concurrently only if **all** of these hold:

1. **Prerequisites are merged.** Every item in the "Needs" column is
   already merged into `main`. Being merely "in progress" is not enough.
2. **Different layers.** Items from the same layer run one after
   another, in §4 order. Same-layer items lower the same ratchet
   constant and usually edit the same modules. The **frontend lane**
   (FE-1 … FE-7) counts as one layer.
3. **No shared files.** The "Files:" lists in the two items' layer-plan
   tasks don't overlap, and neither item touches a **hot file** the
   other touches. Hot files:
   - `src/jidou/services/progress.py`
   - `src/jidou/workers/_harness.py`
   - `src/jidou/main.py`
   - `src/jidou/api/routes/shows.py`, `rss.py` (and their split modules
     after API-8)
   - `tests/conftest.py`
   - `tests/fixtures/openapi_snapshot.json`
   - `frontend/src/types/api-generated.ts`, `frontend/src/types/api.ts`
   - `alembic/versions/`, so that two migrations never create two heads
4. **At most 4 sub-agents at once.** This keeps CI, Bugbot and review
   load manageable. The cap can be raised once the first two waves have
   gone through cleanly.

### Default lanes per wave

These follow from the rules above. Within a lane, items run in order;
lanes run in parallel.

| Wave | Lanes |
|---|---|
| 0 | One lane each, all concurrent: API-1 · MDL-1 · SVC-1 · ORC-1 · WRK-1 · FE-1 (run in batches of 4) |
| 1 | MDL-2 → WRK-2 (WRK-2 also needs ORC-2; MDL-2 and WRK-2 share `_harness.py`) · ORC-2 · SVC-2 → SVC-3 · API-2 → API-3 · SCH-1 · FE-2 |
| 2 | API-4 → XL-1 → API-5 → API-6 → API-7 · SVC-4 → SVC-5 → SVC-6 (SVC-6 never alongside XL-1: both touch `progress.py`) · MDL-3 → MDL-4 → MDL-5 · WRK-3 → WRK-4 (after MDL-4) · ORC-4 → ORC-5 → ORC-6 → ORC-9 → ORC-10 · SCH-2 → SCH-3 · FE-3 → FE-4 → FE-5 → FE-6 |
| 3 | API-8 first, alone among the backend lanes (it moves the route modules everyone else in this wave edits). Then: SVC-7 → SVC-8 → SVC-9 · ORC-3 → ORC-7 → ORC-8 → XL-2 → ORC-11 · WRK-5 · SCH-4 |
| 4 | ORC-12 · WRK-6 · MDL-6 · FE-7 → FE-8 (FE-8 after SCH-3/SCH-4) · SCH-5 |
| 5 | DF-1 → DF-2 → DF-3 → DF-4 (API) · DF-5 → DF-6 (services) · DF-7 → DF-8 → DF-9 → DF-10 → DF-11 → DF-12 → DF-13 (orchestrators; DF-13 also holds the `alembic/versions/` hot file) · DF-14 → DF-15 (workers) · DF-16 → DF-17 → DF-18 → DF-19 → DF-20 (contract lane: schemas, the OpenAPI snapshot and frontend types are hot files, so serial) · then XL-3 alone |

Where a lane table and the "No shared files" rule disagree, the rule
wins. For example, MDL-3 edits the `tracked_source` writer in
`tmdb_orchestrator.py`, so it must not run alongside ORC-9.

### Merging and releases

- **Merging:** when a sub-agent finishes (checks green, Bugbot
  addressed, reviewer approved), the coordinator merges `main` into the
  item branch, re-runs the pre-push checks, and merges. Merges happen
  one at a time. If merging `main` in causes a conflict, return the item
  to its sub-agent instead of resolving it in the coordinator.
- **Release per wave (D1):** once every item in a wave has merged
  (backend and frontend lanes), the coordinator opens
  `chore/release-wave-<n>`. It bumps the version the way commit `69c7290`
  did (`pyproject.toml`, `src/jidou/__init__.py`,
  `frontend/package.json`, `uv lock`), and adds one `CHANGELOG.md` entry
  listing the wave's PRs. The next wave starts after this PR merges.
  That gives 5 releases in total.

## 5. Cross-layer items (new tasks owned by this roadmap)

### XL-1: Move task dispatch out of `progress.py` (R3)

**Files:** modify `src/jidou/services/progress.py` and
`src/jidou/services/task_dispatch.py` (created by API-4), plus every
importer (`grep -rn "enqueue_task\|TaskDispatchError\|get_active_task" src tests`).

- [ ] Move `enqueue_task`, `TaskDispatchError` and `get_active_task`
  verbatim into `task_dispatch.py`. Update the importers and `patch()`
  targets.
- [ ] Verify: `uv run pytest -q`. The OpenAPI snapshot is unchanged.
- [ ] Commit: `refactor(services): task dispatch lives in task_dispatch, not progress`

### XL-2: Domain errors for regex suggestion (R5)

**Files:** modify `src/jidou/services/rss_regex_suggestor.py`,
`src/jidou/orchestrators/errors.py` (from ORC-8), `src/jidou/main.py`'s
handler table, and the split `rss_*` route module that catches
`RegexSuggestionError`.

- [ ] Add `ServiceUnavailableError(OrchestratorError)` → 503 to the
  handler table. Replace `RegexSuggestionError(422, …)` with
  `InvalidRequestError(…)` and `RegexSuggestionError(503, …)` with
  `ServiceUnavailableError(…)`, keeping the `detail` strings
  byte-for-byte. Delete `RegexSuggestionError` and the route's
  `try/except`.
- [ ] Verify: `uv run pytest tests/test_rss_regex_suggestor.py tests/test_rss_feed_regex_routes.py tests/test_rss_routes.py tests/test_api_contract.py -q`.
  Status codes and bodies must be unchanged.
- [ ] Commit: `refactor: regex suggestion errors use the domain error handler`

### XL-3: Program closeout

- [ ] Confirm the final ratchet values in §8, each set in its test or
  config file.
- [ ] Full backend and frontend check sequences on a fresh clone with
  Node 24 / `npm ci`; `alembic upgrade head` and `alembic check` against
  a fresh Postgres.
- [ ] Update `docs/architecture.md` (layer boundaries, the layering
  guards, the hooks boundary) and `docs/developer.md` (ratchets, the
  `alembic check` gate, the OpenAPI snapshot and type regeneration).
- [ ] D32: in `docs/setup.md` and `docs/developer.md`, state that
  frontend work needs Node 24 (`.nvmrc` pins it; run `nvm use`), and
  that `npm ci` fails on older Node versions.
- [ ] `graphify update .`; commit
  `docs: architecture and guardrails after the simplification program`.

## 5A. Decision follow-up items (DF-1 … DF-20)

Every DF item is a small PR under §1's Global Constraints, with one
exception: the behavior named in its decision changes on purpose. Each
item:
- **writes the test that pins the new behavior first** and shows it
  failing;
- updates any existing assertion that encoded the old behavior, naming
  it in the PR body;
- regenerates the OpenAPI snapshot and the frontend types when its Kind
  says "contract".

### DF-1 (D7): one 503 dispatch message
- **Files:** `src/jidou/services/task_dispatch.py` (and the `trigger_task`
  route if it still builds its own string).
- **Change:** every broker-dispatch failure answers 503 with
  `detail="Task broker unavailable"`.
- **Tests:** a parametrized test over the task trigger, the import
  routes and the RSS trigger routes, each with a failing broker, checks
  the 503 and the exact `detail`. Update the test that asserted
  `"Failed to dispatch task to broker"`.

### DF-2 (D12): `patch_file` show change clears old tracking
- **Files:** `src/jidou/services/file_relink.py` (from API-5).
- **Change:** when `show_id` changes and no `episode_id` is given, call
  `clear_if_unreferenced(session, old_episode_id, None)` before nulling
  the link.
- **Tests:** `test_reassign_show_without_episode_clears_old_tracking`
  replaces the API plan's
  `test_reassign_show_without_episode_does_not_clear_old_tracking`,
  with the opposite assertion. Add one more test: the old episode is
  **not** cleared while another file still references it.

### DF-3 (D9): Redis required in both health endpoints
- **Files:** `src/jidou/api/routes/admin.py` (`system_health`),
  `src/jidou/services/health_probes.py` (from API-7).
- **Change:** an unreachable *or unconfigured* Redis makes
  `/api/admin/health` unhealthy, matching `/api/health`. The response
  shape is unchanged.
- **Tests:** replace
  `test_health_redis_not_configured_does_not_make_unhealthy` with
  `test_health_redis_not_configured_is_unhealthy`. Keep the test for
  Redis being down.

### DF-4 (D25): eager loading before `lazy="raise"`
- **Files:** every route that returns `FileRead` (find them with
  `grep -rn "response_model=.*FileRead\|FileRead\]" src/jidou/api`),
  plus `src/jidou/models/downloaded_file.py`.
- **Step 1, refactor:** add `selectinload(DownloadedFile.show),
  selectinload(DownloadedFile.episode)` to every query whose result is
  serialized as `FileRead`. For objects returned after a commit (the
  manual-match response), re-select them with those options. The JSON
  must stay identical, and the full suite must pass.
- **Step 2, behavior:** switch both relationships to `lazy="raise"`. A
  missed load now fails in tests instead of silently returning `null`.
- **Tests:** `test_file_read_routes_include_show_and_episode`,
  parametrized over the routes, checks that `show` / `episode` are
  populated when they are linked.

### DF-5 (D19): one media-extension list
- **Files:** `src/jidou/services/path_parser.py`.
- **Change:** delete `_MEDIA_EXTENSIONS` and use
  `file_filters.MEDIA_EXTENSIONS` (adds `.iso`, `.av1`, `.ogm`).
- **Tests:** `test_parse_line_accepts_every_scan_extension`, one case per
  extension in `MEDIA_EXTENSIONS`.

### DF-6 (D20 + D21): 4-digit episodes; shared tokens
- **Files:** `src/jidou/services/file_filters.py` (new shared
  `RESOLUTION_TOKENS` and `QUALITY_TOKENS`), `filename_parser.py`,
  `path_parser.py`, and the golden table in
  `tests/test_path_parser_episode_rules.py`.
- **Change:**
  - Every **explicit-marker** episode pattern accepts 1–4 digits: `SxxEyyyy`,
    `NxNNNN`, `Episode N`, `Ep N`, `- N`, `N - Title`.
  - Every **bare-number** pattern accepts 1–4 digits **only** after
    excluding years (1900 through the current year + 2) and the shared
    resolution tokens.
  - `filename_parser._QUALITY_PAT` and `path_parser._COMPACT_QUALITY`
    are built from the shared token lists (D21).
  - The compact SEEE/SSEEE heuristic keeps its order and its
    `absolute_candidate`.
- **Tests:** first add golden rows that pin the current results. Then
  change them, so the PR diff shows each new outcome explicitly:

  | Input | Expected after DF-6 |
  |---|---|
  | `Show S01E1001` | (1, 1001) |
  | `Show 1x1000` | (1, 1000) |
  | `Show - 1071 [1080p]` | (None, 1071) |
  | `One Piece 1071` | Compact guess plus absolute candidate 1071 |
  | `Show 2024` | (None, None): year excluded |
  | `Show 1080p` | (None, None): resolution excluded |
  | `Episode 1100` | (None, 1100) |

  Any other row whose result changes must be listed in the PR body.

### DF-7 (D13): event-logging failures never abort work
- **Files:** `src/jidou/orchestrators/{sync,path_import,rss_import,rss_publish}_orchestrator.py`,
  `src/jidou/services/episode_match_llm.py` (`_emit`).
- **Change:** use `EventSink(..., swallow_errors=True)` everywhere. The
  services `_emit` swallows and logs `"Event logging failed; continuing"`.
- **Tests:** in ORC-1's `test_event_failure_semantics.py`, change
  `test_sync_event_failure_propagates` and
  `test_path_import_event_failure_propagates` to `*_is_swallowed`, and
  add RSS import/publish cases.

### DF-8 (D14): race recovery by `tmdb_id`
- **Files:** `src/jidou/orchestrators/path_import_orchestrator.py` (the
  `refind=` argument from ORC-3) and `manual_match_orchestrator.py`.
- **Change:** every provisioning caller passes a `refind` that looks the
  show up by `tmdb_id` and then calls `ensure_episode_group_map`. Each
  caller keeps its own alias-failure policy.
- **Tests:** `test_path_import_race_refinds_by_tmdb_id_not_title`: a
  different show with the same title exists, and the result must be the
  `tmdb_id` match. Also `test_manual_match_race_ensures_group_map`.

### DF-9 (D15): one name-agreement rule
- **Files:** `src/jidou/services/alias_handling.py` (new
  `names_agree(name: str, show: Show) -> bool`), `parse_orchestrator.py`
  (`_is_exact_alias_match`), `path_import_orchestrator.py`
  (`_agrees_with_show`, `_normalize_title`).
- **Change:** case- and punctuation-insensitive equality against the
  title or any alias. Never a substring match.
- **Tests:** `"Daredevil Born Again"` agrees with `"Daredevil: Born Again"`;
  `"Daredevil"` does **not** agree with `"Daredevil: Born Again"`; an
  alias match agrees.

### DF-10 (D16): one `local_path` auto-population helper
- **Files:** `src/jidou/services/path_resolution.py` (new
  `auto_local_path_for(show, *, tv, anime, movie) -> str | None`, which
  returns `None` unless `content_type` is set or `media_type == "movie"`),
  `parse_orchestrator.py`, `path_import_orchestrator.py`,
  `services/show_creation.py`.
- **Tests:** unit tests for the rule. Path import (which always sets
  `content_type`) keeps the same paths, per the existing
  `test_path_import.py`.

### DF-11 (D17): sync warns about a missing show
- **Files:** `src/jidou/orchestrators/sync_orchestrator.py`
  (`_sync_tmdb_phase`).
- **Change:** a missing `show_id` emits
  `warn "Show id=<n> not found; TMDB phase skipped"` and logs a warning.
  The result stays `TMDBSyncResult.empty()`.
- **Tests:** replace ORC-7's
  `test_sync_tmdb_phase_missing_show_returns_empty_and_orchestrator`
  pin with one that also asserts the event.

### DF-12 (D18): duplicate exact titles are ambiguous
- **Files:** `src/jidou/services/fuzzy_match.py` (from ORC-12),
  `rss_import_orchestrator._fuzzy_show_id`, `services/rss_stub.py`.
- **Change:** if two or more candidates match the query exactly
  (case-insensitive), return `None`, the same as a fuzzy tie.
- **Tests:** two shows titled `"Some Show"` give no link in both callers.

### DF-13 (D33): duplicate files for one episode are flagged
- **Files:** a new migration under `alembic/versions/`,
  `src/jidou/models/downloaded_file.py`,
  `src/jidou/orchestrators/parse_orchestrator.py`,
  `src/jidou/schemas/file_schema.py`, `frontend/src/pages/Files.tsx` (plus
  hook and types).
- **Interfaces:**
  - `DownloadedFile.duplicate_of_file_id: Mapped[int | None]`, a foreign
    key to `downloaded_files.id` with `ON DELETE SET NULL`, indexed.
  - `FileRead.duplicate_of_file_id: int | None`.
- **Change:** when parse links a file to an episode that already has
  another non-synthetic file in `MATCHED`, `ROUTING` or `ROUTED`:
  - set `duplicate_of_file_id` to that file's id;
  - emit
    `warn "Episode S01E05 of '<show>' already has '<file>'; '<new file>' flagged as a duplicate (both kept)"`.

  Routing is unchanged: both files are kept, and choosing which copy to
  keep stays a manual decision. The Files page shows a "Duplicate" badge
  and a filter for it.
- **Tests:**
  - `test_parse_flags_second_file_for_same_episode`;
  - `test_parse_does_not_flag_synthetic_import_rows`;
  - the migration upgrades and downgrades, and `alembic check` is clean;
  - a frontend test for the badge.

### DF-14 (D29): SFTP connection test uses the factory
- **Files:** `src/jidou/services/sftp_service.py` (`create_sftp_service`
  gains an optional `remote_base_path` override),
  `src/jidou/api/routes/config.py`.
- **Tests:** the existing config route tests pass. A unit test checks the
  override reaches the service.

### DF-15 (D30): harness `set_progress_total`
- **Files:** `src/jidou/workers/_harness.py` (`WorkFn` gains a fourth
  callable, `set_total(total: int, message: str)`), every worker
  `_work`, `import_tasks.py`, `db_import_tasks.py`.
- **Change:** the two import workers stop calling `update_task_status`
  directly.
- **Tests:** a harness unit test for `set_total`. The workers plan's
  golden summaries stay unchanged, and the 5 tests that patched
  `import_tasks.update_task_status` are retargeted to the callback.

### DF-16 (D6): dedicated show-creation input
- **Files:** `src/jidou/orchestrators/show_creation_orchestrator.py`
  (a new frozen dataclass `ShowSeed` built from `ShowCreate` at the
  route boundary), and the two callers.
- **Change:** the orchestrator no longer calls `model_dump()` / `pop()`
  on an HTTP schema.
- **Tests:** the existing show-creation and feed-onboarding tests pass
  unchanged.

### DF-17 (D5): typed TMDB sub-objects
- **Files:** `src/jidou/schemas/_base.py` / `show_schema.py` (new
  `TmdbGenre`, `TmdbNetwork`, `TmdbEpisodeRef`, each with
  `ConfigDict(extra="allow")`), the response schemas that use them, and
  `frontend/src/types/api.ts`.
- **Change:** `genres`, `networks`, `last_episode_to_air` and
  `next_episode_to_air` are typed. Then delete the matching `Omit<>`
  overrides in `api.ts` (`ShowList`, `CalendarEpisode`,
  `RecentEpisodeItem` where applicable).
- **Tests:** a response-validation test with an extra unknown TMDB key
  passes, and existing JSON is unchanged. The snapshot and frontend
  types are regenerated.

### DF-18 (D10): `GET /shows/index`
- **Files:** a new route in the shows route module (after API-8),
  `schemas/show_schema.py` (`ShowIndexEntry`: `id`, `tmdb_id`, `title`,
  `sys_name`, `aliases`, `media_type`, `content_type`),
  `frontend/src/hooks/useShows.ts` (`useLibraryIndex` reads it),
  `SubscriptionEditModal.tsx`, and `ShowDetail` (watchlist membership
  via `/watchlist?show_id=` instead of fetching up to 10,000 entries).
- **Change:** a lightweight index for pickers and lookups, sized for
  several thousand shows. The Shows and Watchlist pages keep their full
  lists, because they render every card; real pagination there is in
  the backlog (§9).
- **Tests:** a route test (fields, ordering, no N+1 queries). Frontend
  hook and picker tests use the new endpoint through MSW.

### DF-19 (D8): CI type-drift check
- **Files:** `make.py` (a new `export-openapi` command that writes
  `app.openapi()` to a file without starting a server), and
  `.github/workflows/ci.yml` (frontend job: export, then
  `npx openapi-typescript <file> -o /tmp/api-generated.ts`, then
  `diff` it against `frontend/src/types/api-generated.ts`).
- **Tests:** the CI job fails on a deliberately stale type file in a
  scratch commit (not merged) and passes on the real one.

### DF-20 (D4): reject unknown fields in request bodies
- **Files:** `src/jidou/schemas/_base.py` (new `RequestModel(BaseModel)`
  with `extra="forbid"`), every request-body schema, and any request
  model still defined inside a route module.
- **Pre-check:** `buildShowCreatePayload` already sends only
  `ShowCreate` fields. Confirm the same for every frontend mutation
  body: the request types come from `api.ts`, so `tsc` catches extras.
- **Tests:** a parametrized test that every request-body schema rejects
  an unknown field with a 422 `extra_forbidden` error. The full backend
  and frontend suites must pass.

## 6. Behavior changes the program makes

B1–B4 and every DF item are **approved**. Everything else is a refactor
or a contract change with no change in JSON values.

| # | Item | Change | Why it is acceptable |
|---|---|---|---|
| B1 | SVC-3 | `llm_match_episode` returns the lowest-id row on duplicate episodes instead of raising `MultipleResultsFound` | It is a bug fix and matches the rest of `resolve_episode` (issue #313) |
| B2 | FE-2 | The Settings page caches `/config` for 60 s like the other 6 callers, and redundant refetches of the same query key are dropped | No visible effect; fewer requests |
| B3 | MDL-5 | Two new non-unique indexes on `episodes`, built concurrently | Performance only; downgrade drops them |
| B4 | SCH-5 | Request `media_type` / `content_type` are validated as enums; rematch with a bad value answers 422 instead of 502 | Approved (D11) |
| B5 | DF-1 … DF-20 | Each approved decision in §7 | Approved one by one; each has its own PR and tests (§5A) |
| — | SCH-3, SCH-4, ORC-8 | OpenAPI component names and enum `$ref`s change; HTTP errors come from one handler | JSON values, status codes and `detail` strings are unchanged; frontend types are regenerated in the same PR |

## 7. Decision register

Every decision now has an outcome. **Approved** decisions become the DF
items in Wave 5 (§5A). **Keep** means no change; the reason is recorded
so the question doesn't come back.

| # | Decision | Outcome | Item |
|---|---|---|---|
| D1 | Version bumps | **Once per wave**: one `chore/release-wave-<n>` PR per wave (§4A, R10) | — |
| D2 | Serial vs parallel | **Parallel sub-agents** under the §4A rules | — |
| D3 | Delete `fetch_trending_shows_task` | **Keep.** It will use the TMDB cache **and** a separate `trending_titles` table, never `shows`. Tracked in jamesbconner/Jidou#655. | — |
| D4 | `extra="forbid"` on request bodies | **Approved** | DF-20 |
| D5 | Typed TMDB sub-objects | **Approved** (`extra="allow"` sub-models) | DF-17 |
| D6 | Dedicated show-creation input model | **Approved** | DF-16 |
| D7 | Unify the 503 dispatch message | **Approved** | DF-1 |
| D8 | CI type-drift check | **Approved** | DF-19 |
| D9 | Redis rules in the two health endpoints | **Approved: Redis required in both** (the opposite of the original "keep both" recommendation) | DF-3 |
| D10 | Replace the `limit=10000` "fetch everything" calls | **Approved**, sized for several thousand shows (`/shows/index`) | DF-18 |
| D11 | Request vocabularies typed as enums | **Approved** | SCH-5 |
| D12 | `patch_file` stale tracking | **Approved** | DF-2 |
| D13 | Event-logging failures | **Approved: swallow everywhere** | DF-7 |
| D14 | Race recovery lookup key | **Approved: `tmdb_id`, plus `ensure_episode_group_map`** | DF-8 |
| D15 | Name-agreement rule | **Approved** | DF-9 |
| D16 | `local_path` auto-population | **Approved** | DF-10 |
| D17 | Sync with a missing `show_id` | **Approved: warn** | DF-11 |
| D18 | Duplicate exact titles in the fuzzy matchers | **Approved: ambiguous** | DF-12 |
| D19 | Media extension lists | **Approved**: `.iso`, `.av1`, `.ogm` are tracked everywhere | DF-5 |
| D20 | Episode-number digit cap | **Approved: 4 digits everywhere** (long-running shows passed episode 1,000), with year and resolution exclusions | DF-6 |
| D21 | Shared quality/resolution tokens | **Folded into D20**: DF-6's resolution exclusion needs the shared list | DF-6 |
| D22 | Different single-flight semantics for TMDB and LLM | **Keep**: the LLM signals failure with `None`, so a cap would only add latency | — |
| D23 | YaRSS2 edge-case differences | **Keep**: a bad saved pattern must not break the feed browser | — |
| D24 | Legacy `FileStatus.PENDING` | **Not needed**: no `pending` rows exist. The enum value and its one reference stay; they are harmless. | — |
| D25 | `lazy="noload"` on `DownloadedFile` relationships | **Approved**: explicit loading, then `raise` | DF-4 |
| D26 | Dates stored as strings on `Show` | **Keep**: ISO strings sort correctly; a migration plus contract change isn't worth it today | — |
| D27 | Physical split of `Show` | **Keep a single table**: MDL-4's provenance tags give the ownership benefit | — |
| D28 | `task_type` stays a free string | **Keep**: `TASK_REGISTRY` plus SCH-2's guard test pin it | — |
| D29 | API SFTP connection test | **Approved** | DF-14 |
| D30 | Harness `set_progress_total` | **Approved** | DF-15 |
| D31 | Backup-restore rules; scheduled-dispatch cleanup | **Keep**: both deliberate and documented | — |
| D32 | Node version | **Document only** (Node 24, `.nvmrc`); no `engine-strict` | XL-3 |
| D33 | Several files matched to one episode in the download pipeline | **Approved: warn and flag the newer file; keep both** | DF-13 |

## 8. Ratchets and final targets

| Layer | Guard file | Start → end | Lowered in |
|---|---|---|---|
| API | `tests/test_api_contract.py` `_API_MAX_COMPLEXITY` | 16 → 11 (→ 10 with the deferred `get_similar_shows` extraction) | API-5, API-6, API-8 |
| Services | `tests/test_services_architecture.py` | 17 → 9 | SVC-2 … SVC-9 |
| Orchestrators | `tests/test_orchestrators/test_architecture.py` | 28 → 10 | ORC-4 … ORC-12 |
| Workers | `tests/test_workers_architecture.py` | 16 → 8 | WRK-4, WRK-5, WRK-6 |
| Models | `tests/test_models_schema.py` + `alembic check` | no complexity; drift must be 0 | MDL-1 onward |
| Frontend | `frontend/eslint.config.js` `complexity` | 92 → 25 | FE-3 … FE-7 |

## 9. Backlog (out of scope for this program)

Each item is a candidate for a later program, with a suggested priority.

- **Medium:** API R8 `LocalFileScanService` (merging the two scan-local
  endpoints); API R9 (the rest of the link/unlink invariants in
  `orphans.py` and `shows.py`); a `StatsQueryService` for the 18 admin
  and dashboard queries; `get_similar_shows` as a pure function (API
  ratchet → 10).
- **Medium:** server-side pagination for the Shows and Watchlist pages,
  which still load the full library after DF-18. Worth doing as the
  library grows past several thousand shows.
- **Low:** rename the `jidou:tmdb_cache:*` key space now that the feed
  cache shares it (needs a cache flush note); a neutral `jidou/prompts/`
  package for the LLM prompt files (orchestrators O5); a pipeline-stage
  protocol for `SyncOrchestrator`; moving
  `decode_path_bytes_for_display` to a neutral module (schemas §6 item
  5, recommendation: leave).

## 10. Self-review

- **Coverage:** every PR row in the seven layer plans appears exactly
  once in §4: 8 + 9 + 12 + 6 + 6 + 5 + 8 = 54, plus XL-1, XL-2,
  XL-3 and DF-1 … DF-20, for 77. Every "Deferred" item from the seven
  plans appears in §3, §5, §5A, §7 or §9. Every approved decision in §7
  maps to exactly one item.
- **Dependencies:** every hard prerequisite from the layer plans'
  "Must run after" columns is met by the order in §4. R1 deliberately
  reverses one of them (MDL-2 now runs before SVC-9 and WRK-5).
- **Behavior:** Waves 0–4 change behavior only through B1–B4. Every
  other approved behavior change is a DF item in Wave 5, and §7 has no
  open decisions left.
