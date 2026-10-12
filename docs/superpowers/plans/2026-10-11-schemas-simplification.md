# Schemas Layer Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove dead and duplicated Pydantic contracts in
`src/jidou/schemas/`, and type the vocabulary fields consistently with
the model enums. Tasks 1–4 leave the HTTP contract and the OpenAPI
document byte-for-byte unchanged. Tasks 5–6 change OpenAPI on purpose,
without changing any JSON value. Task 7 changes request validation and
runs only if spec §6 item 2 is approved.

**Architecture:**
- An annotated `RegexPattern` type replaces the copied validator
  methods.
- An `ORMModel` base class replaces the repeated `from_attributes`
  configuration.
- Dead schemas are deleted.
- Response vocabulary fields use the model enums, and the duplicate
  `ShowBrief` gets two distinct names.

Each change that alters the contract regenerates the frontend types in
the same commit.

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI, pytest, ruff, mypy
(strict), uv; `openapi-typescript` via `make.py generate-types`.

**Spec:** `docs/superpowers/specs/2026-10-11-schemas-simplification-design.md`.
Read it first. Finding IDs (SC*) and section numbers (§) refer to it.

> **Status note:** This plan covers the schemas layer only. It will be
> merged with the API, services, orchestrators, workers and models plans,
> and the frontend plan, before execution. Line numbers were correct at
> commit `7d60acc`.

## Global Constraints

- **The OpenAPI snapshot is the contract.** This plan depends on API
  plan Task 1 (`tests/test_api_contract.py` and
  `tests/fixtures/openapi_snapshot.json`).
  - In Tasks 1–4, the snapshot test must pass **without regenerating
    the fixture**.
  - In Tasks 5–7, regenerate the fixture in the same commit, and the
    diff must contain **only** the changes that task describes.
- **JSON values do not change.** Every response body keeps the same keys
  and values. For request bodies, valid inputs keep producing the same
  result. Only Task 7 (gated) changes how invalid inputs are rejected.
- **Frontend types** follow every change to OpenAPI. Run
  `uv run python make.py docker-up`, then
  `uv run python make.py generate-types`, then hand-update
  `frontend/src/types/api.ts` as `make.py` instructs. Commit both files
  with the schema change, then run `npm --prefix frontend run build` and
  `npm --prefix frontend test`.
- **No backward-compatibility shims.** When a name moves, update every
  importer. Do not re-export it from the old location.
- **Do not edit existing test assertions**, except to delete tests of
  deleted classes (Task 1).
- **Commands:** use `uv` only for Python; use `npm --prefix frontend` for
  the frontend.
- **Style:** ruff target `py313`, `line-length = 100`; mypy
  `strict = true`; Google-style docstrings; explicit type hints;
  `Field(description=…)` on every field that appears in OpenAPI.
- **Pre-push checks, in this order:** `uv run ruff check .` →
  `uv run ruff format --check .` → `uv run mypy src/` →
  `uv run bandit -r src/ -l` → `uv run pytest`, plus the frontend build
  and tests whenever `frontend/` changed.
- **After code changes:** run `graphify update .`.
- **Git:** never commit to `main`. Use one branch and one PR per row of
  "PR grouping", work serially, and merge with `--merge`. Each PR ends with
  a version-bump commit following the repo convention (see commit
  `69c7290`).
- **Commit trailer:** end every commit message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **An invalid regex sent to any of the six request bodies.** Expected:
   422 with error `type == "value_error"`, `loc` ending in the field
   name, and `msg == "Value error, Invalid regular expression: <re
   error>"`, exactly as today. Pinned by Task 2's
   `test_invalid_regex_error_shape_unchanged`, which is parametrized over
   all 7 fields.
2. **An ORM row with `matched_by=NULL` / `ignored_reason=NULL` serialized
   after Task 6.** Expected: `null`, not an error. Pinned by Task 6's
   `test_file_read_enum_fields_accept_none`.
3. **A frontend type that disappears after the `ShowBrief` rename.**
   Expected: `npm --prefix frontend run build` passes, with `api.ts`'s
   `ShowBrief` and `WatchlistShowBrief` aliases repointed. Pinned by
   Task 5, Step 4.
4. **The worker task-type strings drift from the `TaskType` `Literal`.**
   Expected: a test fails. Pinned by Task 4's
   `test_task_type_literal_matches_worker_types`.
5. **A request body that someone forgot to add the regex type to.**
   Expected: the class-level guard catches it. Pinned by Task 2's
   `test_every_regex_field_uses_regex_pattern`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/jidou/schemas/_base.py` | Create | `ORMModel`, `RegexPattern`, `MediaType` |
| `src/jidou/schemas/import_schema.py` | Delete | Dead (SC1) |
| `src/jidou/schemas/{episode,file,task,watchlist,rss,show,settings,dashboard,orphan}_schema.py` | Modify | As described per task |
| `tests/test_schemas.py` | Create | Regex error shape, guards, enum fields |
| `tests/fixtures/openapi_snapshot.json` | Regenerate (Tasks 5–7 only) | API plan's snapshot |
| `frontend/src/types/api-generated.ts`, `frontend/src/types/api.ts` | Regenerate / hand-edit (Tasks 5–7) | Frontend contract |

## PR grouping

| PR | Branch | Tasks | Must run after |
|---|---|---|---|
| 1 | `refactor/schemas-dead-and-regex` | 1, 2 | **API plan PR 1** (snapshot) |
| 2 | `refactor/schemas-base-and-constants` | 3, 4 | PR 1; **models plan PR 2** for Task 4's SC5 step |
| 3 | `refactor/schemas-showbrief-names` | 5 | PR 1 |
| 4 | `refactor/schemas-response-enums` | 6 | PR 1; **models plan PR 3** (`TrackedSource`, `SnapshotType`) |
| 5 | `fix/schemas-request-vocabularies` | 7 | **Only if spec §6 item 2 is approved** |

---

## Phase 0 / High — no contract change

### Task 1: Delete dead schemas (SC1)

**Files:**
- Delete: `src/jidou/schemas/import_schema.py`
- Modify: `episode_schema.py` (remove `EpisodeRead`), `file_schema.py` (remove `FileList`), `task_schema.py` (remove `TaskProgress`), `watchlist_schema.py` (remove `WatchlistList`), `tests/test_task_routes.py` (delete the two `TaskProgress` tests)

- [ ] **Step 1: Re-prove each class is dead.** For each name, run
  `grep -rnw "<Name>" src tests` and also `grep -rn "import_schema" src tests`.
  - The only hits allowed are the definition itself and, for
    `TaskProgress`, `tests/test_task_routes.py`.
  - Hits in `frontend/src/types/api.ts` are hand-written TypeScript
    interfaces; they are the frontend plan's concern.
  - If anything else appears, keep that class and note it in the PR.
- [ ] **Step 2: Delete them**, plus the two `TaskProgress` tests
  (`# TaskProgress schema — _coerce_task_status` section).
- [ ] **Step 3: Verify.** `uv run pytest tests/test_api_contract.py tests/test_task_routes.py -q`.
  Expected: pass, and the snapshot is unchanged.
- [ ] **Step 4: Commit.** `chore(schemas): delete unused schemas and the dead import_schema module`

### Task 2: `RegexPattern` annotated type (SC2)

**Files:**
- Create: `src/jidou/schemas/_base.py`, `tests/test_schemas.py`
- Modify: `src/jidou/schemas/rss_schema.py`

**Interfaces:**
- Produces, in `_base.py`:
  ```python
  def _validate_regex(value: str) -> str: ...  # moved from rss_schema; same ValueError text


  RegexPattern = Annotated[str, AfterValidator(_validate_regex)]
  ```
  The seven fields become:
  - `RegexHintSample.hint: Annotated[RegexPattern, Field(min_length=1)]`
  - `regex_exclude_hint: RegexPattern | None`
  - `regex_include` / `regex_exclude: RegexPattern | None`, with
    `Field(max_length=MAX_REGEX_PATTERN_LENGTH)` kept where it exists
    today.

  Delete all seven `@field_validator` methods. The order of constraints
  stays the same: `min_length` / `max_length` run before the regex check,
  as today. Pydantic applies `Field` constraints before an
  `AfterValidator`.

- [ ] **Step 1: Write the tests in `test_schemas.py`.**
  - `test_invalid_regex_error_shape_unchanged`, parametrized over
    `(model, field)` for all 7 fields. Validate `{field: "("}` plus that
    model's required fields. Assert `errors()[0]["type"] ==
    "value_error"`, the `loc` ends with the field, and `msg` starts with
    `"Value error, Invalid regular expression:"`.
  - `test_every_regex_field_uses_regex_pattern`: for every `BaseModel`
    subclass in `jidou.schemas.rss_schema`, every field named
    `regex_*` or `hint` has the `_validate_regex` `AfterValidator` in its
    metadata.
- [ ] **Step 2: Run.** Expected: the first test passes today and is a
  guard; the second fails.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Verify.** `uv run pytest tests/test_schemas.py tests/test_rss_routes.py tests/test_rss_feed_regex_routes.py tests/test_rss_feed_add_show_route.py tests/test_api_contract.py -q`.
  Expected: pass, and the snapshot is unchanged (an `AfterValidator`
  adds nothing to the JSON schema).
- [ ] **Step 5: Commit.** `refactor(schemas): one RegexPattern type replaces seven validators`

---

## Phase 1 — Low, no contract change

### Task 3: `ORMModel` base and removing no-op configuration (SC3, SC4)

**Files:**
- Modify: `src/jidou/schemas/_base.py`, and every schema module with `ConfigDict(from_attributes=True)` (21 classes), plus `task_schema.TaskTrigger` and `show_schema.ShowPatch`

**Interfaces:**
- Produces:
  `class ORMModel(BaseModel): model_config = ConfigDict(from_attributes=True)`.
  Each of the 21 classes inherits from it instead of `BaseModel` and
  drops its own `model_config`.
- `TaskTrigger` loses `validate_assignment=True`. First confirm nothing
  assigns to a `TaskTrigger` instance:
  `grep -rn "payload\.\(task_type\|dry_run\) *=" src` must be empty.
- `ShowPatch` loses `populate_by_name=True`. First confirm it has no
  `alias=`.

- [ ] **Step 1: Make the edits.**
- [ ] **Step 2: Verify.** `uv run pytest -q`; `test_api_contract.py`
  passes with an unchanged snapshot (model configuration does not appear
  in OpenAPI; the component title is still the class name).
- [ ] **Step 3: Commit.** `refactor(schemas): ORMModel base; drop no-op model configs`

### Task 4: Shared constants, task-type guard, status coercion (SC5, SC6)

**Files:**
- Modify: `src/jidou/schemas/settings_schema.py`, `rss_schema.py`, `task_schema.py`
- Test: `tests/test_schemas.py` (append)

**Interfaces:**
- `similar_titles_count` uses `ge=SIMILAR_TITLES_COUNT_MIN,
  le=SIMILAR_TITLES_COUNT_MAX`, imported from
  `services/settings_service`, in both `AppSettingsRead` and
  `AppSettingsPatch`.
- `task_schema._coerce_task_status` and the `_validate_status` validator
  on `TaskList` are deleted. **Only do this after models plan Task 3**
  (typed `BackgroundTask.status`) has merged. Before then, skip this
  bullet and say so in the PR.

- [ ] **Step 1: Write `test_task_type_literal_matches_worker_types`.**
  - Collect the second positional argument of every
    `run_task_workflow(` call under `src/jidou/workers/`, with an AST
    scan.
  - Assert the collected set `== set(get_args(TaskType))`. This pins the
    `Literal` against the strings the workers actually write.
- [ ] **Step 2: Run.** Expected: it passes today. It is a guard.
- [ ] **Step 3: Implement the constants and the coercion removal.**
- [ ] **Step 4: Verify.** `uv run pytest tests/test_schemas.py tests/test_settings_routes.py tests/test_task_routes.py tests/test_api_contract.py -q`.
  Expected: pass, and the snapshot is unchanged: `minimum: 1`,
  `maximum: 40` are the same values.
- [ ] **Step 5: Commit.** `refactor(schemas): shared bounds, task-type guard, drop redundant status coercion`

---

## Phase 2 — Medium, deliberate contract changes (no JSON value changes)

### Task 5: Give the two `ShowBrief` classes distinct names (SC7)

**Files:**
- Modify: `src/jidou/schemas/file_schema.py`, `watchlist_schema.py`, `show_schema.py` (if it imports either), `tests/fixtures/openapi_snapshot.json`, `frontend/src/types/api-generated.ts`, `frontend/src/types/api.ts` (2 lines)

**Interfaces:**
- `file_schema.ShowBrief` becomes `FileShowBrief`, and
  `watchlist_schema.ShowBrief` becomes `WatchlistShowBrief`. Fields stay
  as they are.
- In `api.ts`:
  - line 88 becomes
    `export type ShowBrief = components['schemas']['FileShowBrief']`;
  - line 417 becomes
    `export type WatchlistShowBrief = components['schemas']['WatchlistShowBrief']`.

  The TypeScript alias names are unchanged, so no component code
  changes.

- [ ] **Step 1: Rename, and update the importers**
  (`grep -rnw ShowBrief src`).
- [ ] **Step 2: Regenerate the snapshot** with the API plan's documented
  regeneration command. Then
  `git diff tests/fixtures/openapi_snapshot.json`: the only changes must
  be the two component names and the `$ref`s that point at them.
- [ ] **Step 3: Regenerate the frontend types** (see Global
  Constraints), then edit the two `api.ts` lines.
- [ ] **Step 4: Verify.** `uv run pytest -q`,
  `npm --prefix frontend run build`, `npm --prefix frontend test`.
  Expected: all pass.
- [ ] **Step 5: Commit.** `refactor(schemas)!: distinct FileShowBrief/WatchlistShowBrief component names`

### Task 6: Use the enums for response vocabularies (SC8)

**Files:**
- Modify: `src/jidou/schemas/file_schema.py`, `dashboard_schema.py`, `orphan_schema.py`, `rss_schema.py`, the snapshot, and the frontend types
- Test: `tests/test_schemas.py` (append)

**Interfaces:**
- `FileRead.matched_by: MatchedBy | None`,
  `FileRead.ignored_reason: IgnoredReason | None`.
- `RecentShowItem.content_type` / `DashboardShowSummary.content_type:
  ContentType | None`.
- `OrphanRead.tracked_source: TrackedSource`,
  `RssConfigDiff.snapshot_type: SnapshotType`. These two come from
  models plan Task 4.

Each `StrEnum` serializes to its value, so the JSON is unchanged. In
OpenAPI each field becomes `$ref` to an enum component instead of
`string`.

- [ ] **Step 1: Write the tests.**
  - `test_file_read_enum_fields_accept_none`: build a `FileRead` from an
    ORM-like object with both fields `None`.
  - `test_response_enum_fields_serialize_as_values`: for each changed
    field, `model_dump(mode="json")` gives the plain string.
- [ ] **Step 2: Run.** Expected: the first passes today; the second
  passes today as well. Both are guards.
- [ ] **Step 3: Implement it.** Regenerate the snapshot and diff it: the
  only changes allowed are those 6 fields becoming enum `$ref`s, plus any
  new enum components (`MatchedBy`, `IgnoredReason`, `TrackedSource`,
  `SnapshotType`). Regenerate the frontend types and update any `api.ts`
  narrowing that overrode these fields as `string`.
- [ ] **Step 4: Verify.** `uv run pytest -q`, plus the frontend build and
  tests.
- [ ] **Step 5: Commit.** `refactor(schemas)!: response vocabularies typed with model enums`

---

## Gated on spec §6 item 2

### Task 7: Request vocabularies (SC9) — run only if approved

**Files:**
- Modify: `src/jidou/schemas/_base.py` (`MediaType`), `show_schema.py` (`ShowCreate.media_type`, `RematchRequest.media_type`), `file_schema.py` (`FileMatchRequest.tmdb_media_type`, `.content_type`), the snapshot, and the frontend types
- Test: `tests/test_shows_routes.py`, `tests/test_files_routes.py` (append)

**Interfaces:**
- `MediaType = Literal["tv", "movie"]` in `_base.py`.
- `ShowCreate.media_type: MediaType = "tv"`,
  `RematchRequest.media_type: MediaType = "tv"`,
  `FileMatchRequest.tmdb_media_type: MediaType | None`,
  `FileMatchRequest.content_type: ContentType | None`.

- [ ] **Step 1: Write the tests.**
  - `test_rematch_invalid_media_type_is_422` (today it is 502).
  - `test_file_match_invalid_content_type_is_422_enum_error`: assert the
    error `type == "enum"`.
- [ ] **Step 2: Run.** Expected: both fail.
- [ ] **Step 3: Implement it.** Regenerate the snapshot and the frontend
  types.
- [ ] **Step 4: Verify.** `uv run pytest -q`, plus the frontend build and
  tests.
- [ ] **Step 5: Commit.** `fix(schemas)!: validate media_type/content_type request fields as enums`.
  The PR body must list the error-format changes.

---

## Deferred to the merged app-wide plan

- Spec §6 items 1, 3, 4 and 5: `extra="forbid"` on request bodies, typed
  TMDB sub-objects, a dedicated show-creation DTO, and where
  `decode_path_bytes_for_display` should live.
- In the frontend: orphaned hand-written interfaces in `api.ts`
  (`EpisodeRead`, `FileList`, `WatchlistList`) once Task 1 lands.
