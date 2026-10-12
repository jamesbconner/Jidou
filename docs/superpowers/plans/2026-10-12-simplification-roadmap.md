# Jidou Simplification Roadmap (merged)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. This roadmap does **not** repeat task steps. Each roadmap item points at a PR in one of the seven layer plans, which holds the exact files, interfaces, tests and commands. Execute the items in the order of §4, after applying the reconciliations in §3 to the layer plans.

**Goal:** Carry out the seven per-layer simplification plans as one ordered
program of 57 PRs. The program resolves the overlaps between the plans,
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
- **Wave 4** finishes each layer and verifies the whole repository.

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
| Schemas | `specs/2026-10-11-schemas-simplification-design.md` | `plans/2026-10-11-schemas-simplification.md` | 5 (1 gated) | `SCH-n` |
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
  - Execution lanes follow decision **D2**.
  - After each push, poll `gh pr checks` every 60 s (at most 10 times)
    for Cursor Bugbot, and address its comments before moving on.
  - Version bumps follow decision **D1**.
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
Wave 4  Closeout .......... ORC-12  WRK-6  MDL-6  FE-7  FE-8  [SCH-5 if D11]  XL-3
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

## 4. Execution order (57 items)

The **Needs** column lists hard prerequisites; everything earlier in the
table also comes first. **Kind** is: `guard` (adds tests and gates
only), `refactor` (no behavior change), `contract` (OpenAPI changes, no
JSON value changes), `behavior` (listed in §6), or `gated` (waits on a
decision in §7).

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
| 49 | WRK-5 | Scheduled-task table; harness `_finish`; **trending task deleted** | WRK-2, MDL-2 | behavior (B4, D3) |
| 50 | SCH-4 | Response vocabularies typed as enums; types regenerated | SCH-1, MDL-3 | contract |

### Wave 4 — Closeout

| # | Item | What it delivers | Needs | Kind |
|---|---|---|---|---|
| 51 | ORC-12 | Lazy imports removed; fuzzy matcher; alias schema; ratchet → 10 | all ORC, SVC-3, SVC-8 | refactor |
| 52 | WRK-6 | Redis try-lock; `library_root`; long-task limits; ratchet → 8 | all WRK, SVC-6 | refactor |
| 53 | MDL-6 | Registration imports; redundant `nullable` removed | MDL-1 | refactor |
| 54 | FE-7 | Remaining hotspots; ratchet → 25 | FE-3…6 | refactor |
| 55 | FE-8 | Dead types; `ContentType` alias; overrides removed per R7 | FE-7, SCH-1, SCH-3, SCH-4 | refactor |
| 56 | SCH-5 | Request vocabularies typed as enums | **D11 approved**, SCH-1 | gated |
| 57 | XL-3 | Repository-wide verification and documentation (§5) | everything above | guard |

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
- [ ] `graphify update .`; commit
  `docs: architecture and guardrails after the simplification program`.

## 6. Behavior changes the program makes

Everything else is a refactor or a contract change with no change in
JSON values.

| # | Item | Change | Why it is acceptable |
|---|---|---|---|
| B1 | SVC-3 | `llm_match_episode` returns the lowest-id row on duplicate episodes instead of raising `MultipleResultsFound` | It is a bug fix and matches the rest of `resolve_episode` (issue #313) |
| B2 | FE-2 | The Settings page caches `/config` for 60 s like the other 6 callers, and redundant refetches of the same query key are dropped | No visible effect; fewer requests |
| B3 | MDL-5 | Two new non-unique indexes on `episodes`, built concurrently | Performance only; downgrade drops them |
| B4 | WRK-5 | `fetch_trending_shows_task` is deleted | It is unreachable from the beat schedule, the API and the frontend, and it would write non-library rows into `shows`. Gated on **D3**. |
| — | SCH-3, SCH-4, ORC-8 | OpenAPI component names and enum `$ref`s change; HTTP errors come from one handler | JSON values, status codes and `detail` strings are unchanged; frontend types are regenerated in the same PR |

## 7. Decision register

Each row gives a recommendation and the effect if accepted. Rows marked
**Gate** block an item in §4. The others are follow-ups: once approved,
each becomes a small PR scheduled after the item named in "When".

### Program process

| # | Decision | Recommendation | When | Source |
|---|---|---|---|---|
| D1 | **Version bumps.** Each layer plan says every PR ends with a version bump, which would mean 57 bumps. | **Bump once per wave** (5 bumps), each with a CHANGELOG entry listing that wave's PRs. Refactor PRs should not each claim a release. | Before Wave 0 | All plans, Global Constraints |
| D2 | **Serial vs parallel.** The API plan says "work serially". | **Two lanes.** The backend items run serially in §4 order, and FE-1…FE-7 run serially in a parallel frontend lane, because they touch disjoint files. Only FE-8 waits for SCH-3/SCH-4. This roughly halves the calendar time with no added merge risk. | Before Wave 0 | API plan Global Constraints |
| D3 | **Gate WRK-5.** Delete `fetch_trending_shows_task`? | **Delete**, unless you trigger it by hand with `celery call`. It is unreachable, and it writes trending titles into the library table. | Before item 49 | Workers spec §5 D1 |

### API contract and validation

| # | Decision | Recommendation | When | Source |
|---|---|---|---|---|
| D4 | `extra="forbid"` on request bodies | **Adopt**, after FE-2 lands and the frontend's request bodies are confirmed to come from the generated types. Unknown fields currently disappear silently. | After FE-8 | Schemas spec §6 item 1 |
| D5 | Typed TMDB sub-objects (`genres`, `networks`, …) | **Adopt**, with sub-models using `extra="allow"` so new TMDB keys don't cause 500s. Then delete the matching `api.ts` overrides. | After SCH-4 | Schemas spec §6 item 3, frontend spec §6 item 2 |
| D6 | A dedicated show-creation input model instead of `ShowCreate` | **Adopt** as a small follow-up. It separates the HTTP contract from the domain input once ORC-3 has unified provisioning. | After ORC-3 | Schemas spec §6 item 4 |
| D7 | Unify the 503 dispatch detail string | **Adopt** `"Task broker unavailable"` everywhere. API-4 already centralizes dispatch. Update the tests that assert the old string. | After API-4 | API spec §5 |
| D8 | CI type-drift check | **Adopt**: generate OpenAPI from `app.openapi()` offline (no container), run `openapi-typescript`, and fail on a diff of `api-generated.ts`. | After SCH-3 | Frontend spec §6 item 3 |
| D9 | `/api/health` requires Redis; `/api/admin/health` treats it as optional | **Keep both.** The Docker probe should fail without Redis, because workers and pubsub depend on it. The admin view should degrade instead. Document why. | Docs, XL-3 | API spec §5 |
| D10 | Replace the `limit=10000` "fetch everything" calls (7 sites) | **Adopt** a lightweight `GET /shows/index` (`id`, `title`, `tmdb_id`, `sys_name`, `aliases`) for `useLibraryIndex` and pickers. Keep full lists only where cards are rendered. | After FE-7 | Frontend spec §6 item 1 |
| D11 | **Gate SCH-5.** Validate request `media_type` / `content_type` as enums | **Approve.** It turns `RematchRequest`'s 502-on-bad-input into a proper 422. The frontend only sends valid values; only the 422 error wording changes. | Before item 56 | Schemas spec §6 item 2 |

### Data integrity and matching semantics

| # | Decision | Recommendation | When | Source |
|---|---|---|---|---|
| D12 | `patch_file` with a new `show_id` and no `episode_id` leaves stale tracking on the old episode | **Fix**: call `clear_if_unreferenced` for the old episode, with a test. This is a real integrity bug. | After API-5 | API spec §5 |
| D13 | Event-logging failures abort sync, path import and RSS, but not download/parse/route/scan | **Swallow everywhere** (`EventSink(swallow_errors=True)`). The event log is observability and must not abort work. Log the swallowed error. | After ORC-2 | Orchestrators spec §6 item 1 |
| D14 | Race recovery in show provisioning looks shows up again by title (path import) or by `tmdb_id` (the others) | **Use `tmdb_id` everywhere**, and always call `ensure_episode_group_map` afterwards. Looking up by title can pick a different show with the same name. Keep each caller's alias-failure policy. | After ORC-3 | Orchestrators spec §6 item 2 |
| D15 | Name-agreement rules differ between parse and path import | **Unify** on punctuation-insensitive normalized equality (title or alias) in `services/alias_handling`. It is still exact, so it keeps the "no fuzzy substring aliases" guarantee. | After ORC-11 | Orchestrators spec §6 item 3 |
| D16 | `local_path` auto-population rules differ | **One helper**, using parse's rule (content type known, or a movie). Path import always knows its content type, so its behavior does not change. | After ORC-11 | Orchestrators spec §6 item 4 |
| D17 | `sync(show_id=…)` for a missing show is silent | **Emit a `warn` event** and log it. | After ORC-7 | Orchestrators spec §6 item 5 |
| D18 | Exact duplicate titles resolve differently in the two fuzzy matchers | **Treat duplicate exact titles as ambiguous (`None`) in both**, matching the fuzzy tie rule. | After ORC-12 | Orchestrators spec §6 item 6 |
| D19 | Media extension lists: path import rejects `.iso` / `.av1` / `.ogm` | **Unify** on `file_filters.MEDIA_EXTENSIONS`, so bulk import accepts what local scan accepts. | After SVC-4 | Services spec §6 item 1 |
| D20 | `NxNN` episode capped at 2 digits in `path_parser` and 3 in `filename_parser` | **Align at 3 digits**, after adding golden rows such as `Show 1x100` and `Show 1080p` to SVC-1's table first. | After SVC-4 | Services spec §6 item 2 |
| D21 | Quality-token lists are duplicated | **One shared constant** in `services/file_filters.py`. | After SVC-4 | Services spec §6 item 3 |
| D22 | Single-flight semantics differ (TMDB fails fast; LLM keeps electing owners) | **Keep.** The LLM signals failure with `None`, not an exception, so a cap would only add latency. Document it in `single_flight.py`. | — | Services spec §6 item 4 |
| D23 | YaRSS2 edge cases (preview raises and truncates; the matcher skips bad patterns) | **Keep.** A saved subscription with a bad pattern must not break the feed browser. | — | Services spec §6 item 5 |
| D24 | `FileStatus.PENDING` legacy value | **Migrate any `pending` rows to `discovered`** and remove the Python reference in `file_reconciliation`. Leave the PostgreSQL enum value in place; dropping an enum value means rebuilding the type. | After MDL-3 | Models spec §6 item 3 |
| D25 | `lazy="noload"` on `DownloadedFile.show` / `.episode` | **Keep for now**, then add explicit `selectinload` to every route that serializes `FileRead`, and switch to `lazy="raise"` in a follow-up PR. Today a missing load silently returns `null`. | After API-8 | Models spec §6 item 1 |
| D26 | `Show.release_date` / `last_air_date` stored as strings | **Keep.** ISO strings sort correctly, and a data migration costs more than it gains. | — | Models spec §6 item 2 |
| D27 | Split `Show` physically | **No.** MDL-4's provenance tags give the benefit without a migration. | — | Models spec §6 item 4 |
| D28 | `BackgroundTask.task_type` stays a free string | **Keep.** `TASK_REGISTRY` (API-4) and SCH-2's task-type guard test already pin the vocabulary. | — | Models spec §6 item 5 |

### Workers and operations

| # | Decision | Recommendation | When | Source |
|---|---|---|---|---|
| D29 | The API's SFTP connection test builds `SFTPService` its own way | **Use `create_sftp_service`**, with a `remote_base_path` override. | After WRK-3 | Workers spec §6 item 1 |
| D30 | A harness-level `set_progress_total` callback | **Adopt.** It removes the direct `update_task_status` calls from the import workers; it is a one-time `WorkFn` signature change. | After WRK-6 | Workers spec §6 item 4 |
| D31 | Backup-restore per-column rules; scheduled dispatch deletes its row on failure while the API marks it FAILED | **Keep both.** Each is documented as deliberate. | — | Workers spec §6 items 2–3 |
| D32 | Node version for frontend installs | **Document "Node 24 required (npm 11)"** in `docs/setup.md` / `developer.md`. With Node 22, `npm ci` rejects the lockfile. | XL-3 | Frontend spec §6 item 4 |

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
- **Low:** rename the `jidou:tmdb_cache:*` key space now that the feed
  cache shares it (needs a cache flush note); a neutral `jidou/prompts/`
  package for the LLM prompt files (orchestrators O5); a pipeline-stage
  protocol for `SyncOrchestrator`; moving
  `decode_path_bytes_for_display` to a neutral module (schemas §6 item
  5, recommendation: leave).

## 10. Self-review

- **Coverage:** every PR row in the seven layer plans appears exactly
  once in §4: 8 + 9 + 12 + 6 + 6 + 5 + 8 = 54, plus XL-1, XL-2 and
  XL-3, for 57. Every "Deferred" item from the seven plans appears in
  §3, §5, §7 or §9.
- **Dependencies:** every hard prerequisite from the layer plans'
  "Must run after" columns is met by the order in §4. R1 deliberately
  reverses one of them (MDL-2 now runs before SVC-9 and WRK-5).
- **Behavior:** the only behavior changes are B1–B4 and the
  contract-only changes in §6. Every other change in behavior waits on
  a decision in §7.
