# Models Layer Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ORM models describe the real database schema exactly,
give status and vocabulary columns one typed home, and record `Show`
column provenance once. Apart from one new performance index
(Task 6), there is no DDL change and no change in behavior.

**Architecture:**
- Declare every hand-written index in `__table_args__` until
  `alembic check` is clean, and gate on that in CI.
- Add an enum-column helper and typed status columns that keep the
  existing `VARCHAR` / PostgreSQL enum types.
- Move the status sets into the models.
- Tag every `Show` column with `info={"source": …}` and expose
  `show_columns()` for the services and workers layers.

**Tech Stack:** Python 3.13, SQLAlchemy 2 (async), Alembic, PostgreSQL,
pytest, ruff, mypy (strict), uv.

**Spec:** `docs/superpowers/specs/2026-10-11-models-simplification-design.md`.
Read it first. Finding IDs (M*, D*) and section numbers (§) refer to it.

> **Status note:** This plan covers the models layer only. It will be
> merged with the API, services, orchestrators and workers plans, and the
> plans for the remaining layers, before execution. Line numbers were
> correct at commit `b2f35b7`.

## Global Constraints

- **No DDL change**, except Task 6's new indexes. After every other
  task, `alembic check` against a database migrated to `head` must
  report **"No new upgrade operations detected"**. That is the proof. Do
  not write migrations for Tasks 1–5 and 7.
- **No behavior change.** Values read from and written to every column
  stay the same, and so do API JSON outputs. The API plan's OpenAPI
  snapshot, once it exists, must not change.
- **No backward-compatibility shims.** When a name moves, update every
  importer and every `patch("…")` target. Do not re-export it from the
  old location.
- **Do not edit existing test assertions** to make a refactor pass.
- **Commands:** use `uv` only. Never use `pip` or `python -m venv`.
  Alembic runs through `uv run alembic …`.
- **Database for `alembic check`.** Locally, run `docker compose up -d
  postgres`, point `DATABASE_URL` at it, and run `uv run alembic upgrade
  head`. In CI, use the existing `docker compose` job in
  `.github/workflows/ci.yml` (the step that runs `alembic current`).
- **Style:** ruff target `py313`, `line-length = 100`; mypy
  `strict = true`; Google-style docstrings; explicit type hints; a
  comment on each non-obvious declaration explaining *why* it is there.
- **Pre-push checks, in this order:** `uv run ruff check .` →
  `uv run ruff format --check .` → `uv run mypy src/` →
  `uv run bandit -r src/ -l` → `uv run pytest`, then `alembic check` as
  described above.
- **After code changes:** run `graphify update .`.
- **Git:** never commit to `main`. Use one branch and one PR per row of
  "PR grouping", work serially, and merge with `--merge`. Each PR ends with
  a version-bump commit following the repo convention (see commit
  `69c7290`).
- **Commit trailer:** end every commit message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **`alembic --autogenerate` run after this plan.** Expected: no
   operations at all. In particular, it must not drop
   `ix_shows_aliases_gin` or `ix_rss_subscriptions_unique_stub_per_show`.
   Pinned by Task 1's CI gate.
2. **Two concurrent `ensure_rss_stub` calls for the same show.**
   Expected: one inserts and the other recovers through `IntegrityError`.
   That recovery depends on the partial unique index that Task 1
   declares. Pinned by Task 1's
   `test_stub_per_show_index_is_declared`.
3. **A `BackgroundTask` row read after Task 3.** Expected: `status` is a
   `TaskStatus`, equal to its string value, and `TaskResponse` still
   serializes `"running"`, not `"TaskStatus.RUNNING"`. Pinned by Task 3's
   `test_task_status_round_trips_as_value`, plus the existing task route
   tests.
4. **A PostgreSQL enum type name changes because of Task 2's helper.**
   Expected: `filestatus`, `matchedby`, `ignoredreason` and
   `watchliststatus` stay the same. Pinned by Task 2's
   `test_str_enum_keeps_pg_type_names`, and by `alembic check`.
5. **A new `Show` column added without a provenance tag.** Expected: a
   test fails. Pinned by Task 5's `test_every_show_column_has_source`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/jidou/models/base.py` | Modify | `str_enum()` helper |
| `src/jidou/models/{show,episode,rss,task}.py` | Modify | `__table_args__` indexes (Task 1) |
| `src/jidou/models/task.py` | Modify | `Mapped[TaskStatus]`, `ACTIVE_TASK_STATUSES`, `TERMINAL_TASK_STATUSES` |
| `src/jidou/models/show.py` | Modify | Typed `content_type`; `info={"source": …}`; `show_columns()` |
| `src/jidou/models/{episode,orphan,rss}.py` | Modify | `TrackedSource`, `SnapshotType` enums (Task 4) |
| `src/jidou/database.py`, `alembic/env.py` | Modify | `import jidou.models` (M7) |
| `alembic/versions/<new>_add_episode_lookup_indexes.py` | Create (Task 6) | M9 indexes |
| `.github/workflows/ci.yml` | Modify | `alembic check` step |
| `tests/test_models_schema.py` | Create | Index declarations, enum type names, provenance guards |

## PR grouping

| PR | Branch | Tasks | Must run after |
|---|---|---|---|
| 1 | `refactor/models-schema-drift` | 1 | — |
| 2 | `refactor/models-enums-status` | 2, 3 | PR 1 (and the services PR 9 and workers PR 5 importers, if they have merged; see Task 3) |
| 3 | `refactor/models-vocabularies` | 4 | PR 2 |
| 4 | `refactor/models-show-provenance` | 5 | PR 1; **before** workers plan PR 4 |
| 5 | `refactor/models-episode-lookup-index` | 6 | PR 1 |
| 6 | `refactor/models-low-cleanups` | 7 | PR 1 |

---

## Phase 0 — Schema truth

### Task 1: Declare every index; gate on `alembic check` (M1)

**Files:**
- Modify: `src/jidou/models/show.py`, `episode.py`, `rss.py`, `task.py`, `.github/workflows/ci.yml`
- Create: `tests/test_models_schema.py`

**Interfaces:**
- `Show.__table_args__` gains:
  ```python
  Index("ix_shows_aliases_gin", "aliases", postgresql_using="gin", postgresql_ops={"aliases": "jsonb_path_ops"})
  ```
  with a comment naming `services/show_lookup` as its consumer.
- `RssSubscription.__table_args__` gains:
  ```python
  Index("ix_rss_subscriptions_unique_stub_per_show", "show_id", unique=True, postgresql_where=text("remote_key IS NULL"))
  ```
  with a comment naming `services/rss_stub` as its consumer.
- `Episode.__table_args__` gains
  `Index("ix_episodes_show_id_file_tracked", "show_id", "file_tracked")`.
- `BackgroundTask.celery_task_id` and `RssFeed.remote_key` are
  re-declared to match the database (a `UniqueConstraint` plus a plain
  index), using exactly the names `0001_initial` created. Take those
  names from the migration or from the `alembic check` output, not from
  this plan.

- [ ] **Step 1: Capture the drift.** Against a database migrated to
  `head`, run `uv run alembic check`. Expected: it fails and lists the
  three indexes plus the constraint/index differences on
  `background_tasks` and `rss_feeds`. Save the output in the PR
  description.
- [ ] **Step 2: Write `tests/test_models_schema.py`.**
  - `test_alias_gin_index_is_declared`: find the index by name in
    `Show.__table__.indexes`. Assert
    `dialect_options["postgresql"]["using"] == "gin"`.
  - `test_stub_per_show_index_is_declared`: `unique is True`, and the
    `where` clause compiles to `remote_key IS NULL`.
  - `test_episode_tracking_index_is_declared`.
- [ ] **Step 3: Run.** Expected: all three fail.
- [ ] **Step 4: Add the declarations.** Re-run `alembic check` and
  iterate until it reports no changes. Change only the model
  declarations; never the database.
- [ ] **Step 5: Add the CI gate.** In `ci.yml`, right after the step that
  runs `docker compose exec -T jidou-api alembic current`, add a step
  `docker compose exec -T jidou-api alembic check`.
- [ ] **Step 6: Verify.** `uv run pytest tests/test_models_schema.py tests/test_models.py tests/test_database.py -q`
  and `alembic check`. Expected: all pass, with no operations detected.
- [ ] **Step 7: Commit.** `fix(models): declare hand-written indexes; CI fails on model/schema drift`

---

## Phase 1 — Medium

### Task 2: `str_enum` helper (M4)

**Files:**
- Modify: `src/jidou/models/base.py`, `downloaded_file.py`, `watchlist.py`
- Test: `tests/test_models_schema.py` (append)

**Interfaces:**
- Produces:
  ```python
  def str_enum(enum_cls: type[StrEnum], **kwargs: Any) -> SAEnum:
      """SAEnum storing member *values* (not names); kwargs pass through (e.g. native_enum=False, length=50)."""
  ```
  The four existing columns become `str_enum(FileStatus)`,
  `str_enum(MatchedBy)`, `str_enum(IgnoredReason)` and
  `str_enum(WatchlistStatus)`. Do not pass a `name=`; the default type
  name is the lower-cased class name, which is what exists today.

- [ ] **Step 1: Write the tests.**
  - `test_str_enum_keeps_pg_type_names`: for each of the 4 columns,
    `column.type.name` is the lower-cased class name.
  - `test_str_enum_stores_values`: `column.type.enums ==
    [m.value for m in cls]`.
- [ ] **Step 2: Run.** Expected: they pass today. They guard the
  refactor.
- [ ] **Step 3: Implement it.** Then run `alembic check`. Expected: no
  operations.
- [ ] **Step 4: Commit.** `refactor(models): str_enum helper for value-stored enums`

### Task 3: Typed task status and shared status sets (M2, M3)

**Files:**
- Modify: `src/jidou/models/task.py`, `src/jidou/services/progress.py`, `src/jidou/api/routes/tasks.py`, `src/jidou/workers/_harness.py`, `src/jidou/workers/scheduled_tasks.py`, and any module the services plan (Task 14) or workers plan (Task 6) has since pointed at `progress.TERMINAL_STATUSES`
- Test: `tests/test_models_schema.py`, `tests/test_task_routes.py` (append)

**Interfaces:**
- Produces, in `models/task.py`:
  ```python
  ACTIVE_TASK_STATUSES: Final[frozenset[TaskStatus]] = frozenset({TaskStatus.PENDING, TaskStatus.RUNNING})
  TERMINAL_TASK_STATUSES: Final[frozenset[TaskStatus]] = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})
  status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus, native_enum=False, length=50), default=TaskStatus.PENDING)
  ```
  - The members are `StrEnum`s, so the sets also match plain strings,
    and `.in_(…)` binds their values.
  - Delete every local copy: `progress` (the inline sets in
    `update_task_status` and `create_task_record`, and
    `_ACTIVE_STATUSES`), `tasks.py` `_ACTIVE_STATUSES`,
    `_harness._TERMINAL_STATUSES`, `scheduled_tasks._ACTIVE_STATUSES`.
    If the services or workers plans have already added
    `progress.TERMINAL_STATUSES`, delete that too and repoint its
    importers.
  - Remove every `TaskStatus.X.value` whose purpose was comparing with or
    assigning to `BackgroundTask.status`. Keep `.value` where the result
    really must be a `str` (for example, JSON payloads built by hand).
  - `schemas/task_schema._coerce_task_status` is **not** changed here.
    It becomes redundant, and the schemas-layer analysis will decide what
    to do with it.

- [ ] **Step 1: Write the tests.**
  - `test_task_status_round_trips_as_value`: a `BackgroundTask` with
    `status=TaskStatus.RUNNING`. Assert the column's bind processor
    produces `"running"`, and that a value of `"running"` loads as
    `TaskStatus.RUNNING`.
  - `test_task_status_sets_partition_enum`: `ACTIVE | TERMINAL ==
    set(TaskStatus)`, and they do not overlap.
  - `test_list_active_tasks_json_status_is_plain_string`: in
    `test_task_routes.py`, the response JSON `status == "running"`.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it.** Search for the remaining sites with
  `grep -rn "TaskStatus\.[A-Z]*\.value" src`. Run `alembic check`.
  Expected: no operations (the column stays `VARCHAR(50)`, with no CHECK
  constraint).
- [ ] **Step 4: Verify.** `uv run pytest tests/test_progress.py tests/test_progress_service.py tests/test_task_routes.py tests/test_worker_harness.py tests/test_scheduled_tasks.py tests/test_task_cancellation.py tests/test_models_schema.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** `refactor(models): typed BackgroundTask.status and one home for task-status sets`

### Task 4: Typed vocabularies (M5)

**Files:**
- Modify: `src/jidou/models/show.py`, `episode.py`, `orphan.py`, `rss.py`, and the writers of these columns (find them with `grep -rn "tracked_source=\|snapshot_type=\|content_type=" src`)
- Test: `tests/test_models_schema.py` (append)

**Interfaces:**
- Produces:
  ```python
  class TrackedSource(StrEnum): MATCH = "match"; IMPORT = "import"   # models/episode.py
  class SnapshotType(StrEnum): IMPORT = "import"; PRE_PUBLISH = "pre_publish"; POST_PUBLISH = "post_publish"  # models/rss.py
  ```
  - `Show.content_type: Mapped[ContentType | None]`,
    `Episode.tracked_source` / `OrphanedTrackingRecord.tracked_source:
    Mapped[TrackedSource | None]` (the latter non-optional, as today), and
    `RssConfigSnapshot.snapshot_type: Mapped[SnapshotType]`.
  - Each uses `str_enum(…, native_enum=False, length=<current length>)`:
    20 / 20 / 20 / 32.
  - Writers pass enum members instead of string literals.
  - `DownloadedFile.parsed_content_type` stays a `str`. It records the
    LLM's raw answer, and a value outside the enum must not fail a load.

- [ ] **Step 1: Check the live data.** Against a production snapshot, or
  the dev database if that is all there is, run
  `SELECT DISTINCT content_type FROM shows`,
  `SELECT DISTINCT tracked_source FROM episodes`,
  `SELECT DISTINCT tracked_source FROM orphaned_tracking_records` and
  `SELECT DISTINCT snapshot_type FROM rss_config_snapshots`. Every
  non-NULL value must be a member of the target enum. If one is not,
  stop and raise it as a §6 decision; loading it would otherwise raise
  `LookupError`.
- [ ] **Step 2: Write `test_vocabulary_columns_are_typed`.** Assert each
  column's `type.enum_class` is the expected class and `type.length`
  is unchanged.
- [ ] **Step 3: Run.** Expected: fails.
- [ ] **Step 4: Implement it.** Run `alembic check`. Expected: no
  operations.
- [ ] **Step 5: Verify.** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit.** `refactor(models): typed content_type, tracked_source and snapshot_type`

### Task 5: `Show` column provenance (M6)

**Files:**
- Modify: `src/jidou/models/show.py`, `src/jidou/orchestrators/show_metadata_backfill_orchestrator.py` (`_SKIP_FIELDS`), and `src/jidou/workers/db_import_tasks.py` if workers plan Task 5 has already landed
- Test: `tests/test_models_schema.py`, `tests/test_tmdb_mapping.py` (append)

**Interfaces:**
- Produces:
  ```python
  ShowColumnSource = Literal["tmdb", "user", "derived", "key"]
  def show_columns(*sources: ShowColumnSource) -> frozenset[str]
  ```
  `show_columns` reads `Show.__table__.columns[c].info["source"]`.
  Tagging:

  | Source | Columns |
  |---|---|
  | `"key"` | `id`, `tmdb_id`, `created_at`, `updated_at` |
  | `"tmdb"` | every key `build_show_fields` returns except `tmdb_id` and `sys_name` |
  | `"derived"` | `sys_name`, `cached`, `episode_group_map` |
  | `"user"` | `content_type`, `local_path`, `aliases`, `aliases_sources`, `active_episode_group_id`, `active_episode_group_name`, `list_poster_path`, `detail_poster_path`, `banner_path`, `track_missing_episodes` |

  `aliases` is user-or-LLM curated and is never written by
  `build_show_fields`, so it is `"user"`. `sys_name` is `"derived"`
  because it is computed from the title but the user may override it.
  That is why the backfill skips it.
  - `TimestampMixin` columns are tagged `"key"` through the mixin's
    `mapped_column(..., info=…)`. For other models the tag is harmless.
  - The backfill's `_SKIP_FIELDS` becomes `show_columns("derived")`
    intersected with what `build_show_fields` returns. That is
    `{"sys_name"}` today, so its behavior is unchanged.

- [ ] **Step 1: Write the tests.**
  - `test_every_show_column_has_source`.
  - `test_build_show_fields_writes_exactly_tmdb_columns`: call
    `build_show_fields` on a full TMDB fixture. Assert
    `set(fields) == show_columns("tmdb") | {"tmdb_id", "sys_name"}`.
- [ ] **Step 2: Run.** Expected: both fail.
- [ ] **Step 3: Tag the columns and implement `show_columns`.** `info=`
  does not affect DDL; confirm with `alembic check`.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_models_schema.py tests/test_tmdb_mapping.py tests/test_orchestrators/test_show_metadata_backfill_orchestrator.py tests/test_db_import_tasks.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** `refactor(models): record Show column provenance once`

### Task 6: Episode lookup indexes (M9)

**Files:**
- Create: `alembic/versions/<date>_<rev>_add_episode_lookup_indexes.py`
- Modify: `src/jidou/models/episode.py`
- Test: `tests/test_models_schema.py` (append)

**Interfaces:**
- `Episode.__table_args__` gains
  `Index("ix_episodes_show_season_episode", "show_id", "season_number", "episode_number")`
  and
  `Index("ix_episodes_show_absolute", "show_id", "absolute_episode_number")`.
  Both are non-unique; a comment cites issue #313.
- The migration creates both indexes with `postgresql_concurrently=True`
  inside `op.get_context().autocommit_block()`, so large tables are not
  locked. Downgrade drops them.

- [ ] **Step 1: Write `test_episode_lookup_indexes_are_declared`.**
- [ ] **Step 2: Run.** Expected: fails.
- [ ] **Step 3: Implement it.** Generate the migration with
  `uv run alembic revision --autogenerate -m "add episode lookup indexes"`
  and check that it contains **only** these two indexes. After Task 1
  it should. Then add the concurrently/autocommit handling by hand.
- [ ] **Step 4: Verify.** `uv run alembic upgrade head`,
  `uv run alembic downgrade -1`, `uv run alembic upgrade head`,
  `uv run alembic check`. Expected: every command succeeds and the check
  reports no operations. Run `EXPLAIN` on the `resolve_episode` query and
  confirm it uses `ix_episodes_show_season_episode`; paste the plan into
  the PR.
- [ ] **Step 5: Commit.** `perf(models): index episode lookups by (show, season, episode) and (show, absolute)`

---

## Phase 2 — Low

### Task 7: Registration imports and redundant `nullable` (M7, M8, D1)

**Files:**
- Modify: `src/jidou/database.py`, `alembic/env.py`, `src/jidou/models/show.py`, `episode.py`, `downloaded_file.py`, `orphan.py`

- [ ] **Step 1: Simplify the registration imports.** Replace the five
  `from jidou.models.<m> import <X>  # noqa: F401` lines in
  `database.py`, and the two in `alembic/env.py`, with
  `import jidou.models  # noqa: F401 — registers every mapper`.
  `env.py` keeps `from jidou.models import Base`.
- [ ] **Step 2: Remove `nullable=True`** wherever the annotation is
  already `Mapped[X | None]`. There are 40 such columns. Leave
  `nullable=` wherever it disagrees with the annotation; there are none
  today. If one appears, it is a finding, not a cleanup.
- [ ] **Step 3: Verify.** `uv run alembic check` reports no operations.
  `uv run pytest -q` passes. `uv run python -c "import jidou.main"`
  succeeds.
- [ ] **Step 4: Commit.** `chore(models): single registration import; drop redundant nullable=True`

---

## Deferred to the merged app-wide plan

- Spec §6 decisions: `lazy="noload"` on `DownloadedFile`, dates stored
  as strings on `Show`, the legacy `FileStatus.PENDING` value, and any
  physical split of `Show`.
- `schemas/task_schema._coerce_task_status` once Task 3 makes it
  redundant. This belongs to the schemas-layer analysis.
- Reconciling the status-set wording across the services (Task 14),
  workers (Task 6) and models (Task 3) plans into a single task.
