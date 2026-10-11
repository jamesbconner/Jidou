# Models Layer Simplification — Analysis (Spec)

**Date:** 2026-10-11
**Scope:** `src/jidou/models/` (11 modules, 783 lines), plus the model
wiring in `src/jidou/database.py` and `alembic/env.py`, and the 14
migrations under `alembic/versions/`, which define what the models are
supposed to describe.
**Status:** Analysis complete. The companion plan is
`docs/superpowers/plans/2026-10-11-models-simplification.md`. This is
the fifth per-layer analysis, after the API, services, orchestrators and
workers specs of the same date. Still to analyze: `schemas/` and
`frontend/`.

Measured at commit `b2f35b7`. There are no functions above complexity 8
(`ruff C901` is clean), so this analysis is about **schema design and
consistency**, not control flow.

---

## 1. Summary

The models themselves are clean, declarative SQLAlchemy 2 classes with
good docstrings and state-machine diagrams. Every model shares
`TimestampMixin`. The problems are in how the models relate to everything
around them:

1. **The models do not describe the real schema.** Three hand-written
   indexes exist only in migrations, and there is a "unique constraint vs
   unique index" mismatch on two tables. One of those indexes is a
   uniqueness rule, "one stub subscription per show", that
   `services/rss_stub` relies on through `IntegrityError`.
   `alembic --autogenerate` currently proposes **dropping the GIN index
   that alias matching uses**. The 2026-07-08 migration's docstring
   records this and says the generated diff was pruned by hand.
2. **The status vocabularies are defined outside the models.** The
   "active" and "terminal" sets of `TaskStatus` are rebuilt in six
   places across three layers. `BackgroundTask.status` is a plain string
   column, which forces 20 `TaskStatus.X.value` comparisons.
3. **Typed vocabularies are not used consistently.** Four enum columns
   repeat the same `SAEnum(..., values_callable=lambda e: [x.value for x
   in e])` incantation. Meanwhile `ContentType` exists but
   `Show.content_type` is typed as `str`, and `tracked_source` /
   `snapshot_type` are free strings with fixed values.
4. **Each layer keeps its own copy of the column provenance of the
   45-column `Show`.** Which columns TMDB owns, which the user owns, and
   which are derived is re-listed by `tmdb_mapping.build_show_fields`,
   the backfill orchestrator's `_SKIP_FIELDS`, and the 40-name restore
   lists in `db_import_tasks`.

## 2. Structural map

```
base.py ─ Base (DeclarativeBase), TimestampMixin(created_at, updated_at)
  ├─ show.Show (45 cols, ContentType enum unused by the column) ◄─ FK from episodes, downloaded_files,
  │                                                                 orphaned_tracking_records, watchlist, rss_subscriptions
  ├─ episode.Episode ── show_id CASCADE
  ├─ downloaded_file.DownloadedFile ── show_id SET NULL, episode_id SET NULL; FileStatus/MatchedBy/IgnoredReason (PG enums)
  │       relationships: show, episode  lazy="noload"
  ├─ orphan.OrphanedTrackingRecord ── show_id CASCADE, downloaded_file_id SET NULL
  ├─ watchlist.WatchlistEntry ── show_id CASCADE, unique(show_id); WatchlistStatus (PG enum); show lazy="raise"
  ├─ rss.RssFeed ◄── rss.RssSubscription ── feed_id SET NULL, show_id SET NULL; lazy="raise"
  ├─ rss.RssConfigSnapshot
  ├─ task.BackgroundTask (status: String(50) + TaskStatus enum kept separately)
  ├─ scanned_directory.ScannedDirectory
  └─ app_setting.AppSetting (key PK, JSONB value)

models/__init__.py exports everything.
database.py imports 5 of the 11 model modules "for registration".
alembic/env.py imports Base plus 2 model modules.
```

Indexes present in the database but **not** in the models:

| Index | Defined in | Who depends on it |
|---|---|---|
| `ix_shows_aliases_gin` (GIN, `jsonb_path_ops`) | `0001_initial` (raw SQL) | `services/show_lookup` alias containment, which is the first step of every match |
| `ix_rss_subscriptions_unique_stub_per_show` (unique, `WHERE remote_key IS NULL`) | `0001_initial` | `services/rss_stub.ensure_rss_stub`'s `IntegrityError` race recovery |
| `ix_episodes_show_id_file_tracked` | `0001_initial` | Rematch, stats and tracking checks |
| `background_tasks.celery_task_id`, `rss_feeds.remote_key`: the migration creates a `UniqueConstraint` and a plain index, while the model declares `unique=True, index=True` (a unique index) | `0001_initial` | Autogenerate reports this as a difference |

## 3. Findings

| # | Finding | Where | Target |
|---|---|---|---|
| M1 | Model/migration drift (above) | `show.py`, `rss.py`, `episode.py`, `task.py`; `0001_initial` | Declare every index in `__table_args__` exactly as it exists, so that `alembic check` reports no changes. Add `alembic check` to the CI step that already runs `alembic current` against a real Postgres. |
| M2 | `TaskStatus` "active" and "terminal" sets rebuilt in 6 places | `services/progress` (×3), `api/routes/tasks.py`, `workers/scheduled_tasks.py`, `workers/_harness.py` | `models/task.py: ACTIVE_TASK_STATUSES`, `TERMINAL_TASK_STATUSES`. **This supersedes** the services plan's `progress.TERMINAL_STATUSES` and the workers plan's W8 target. |
| M3 | `BackgroundTask.status: Mapped[str]` with a separate enum, which forces `.value` everywhere (20 sites) | `task.py`; callers in progress, harness, scheduled tasks, the tasks route | `Mapped[TaskStatus]` via `SAEnum(TaskStatus, native_enum=False, length=50, values_callable=...)`. The column stays `VARCHAR(50)` (no DDL change; M1's `alembic check` proves it), and the `.value` noise goes away. |
| M4 | `SAEnum(X, values_callable=lambda e: [x.value for x in e])` repeated | 4 columns in `downloaded_file.py`, `watchlist.py` | `base.str_enum(enum_cls, **kw) -> SAEnum`. It must keep the default PostgreSQL type names (`filestatus`, `matchedby`, `ignoredreason`, `watchliststatus`). |
| M5 | Columns with a fixed vocabulary but no enum type | `Show.content_type` (and `ContentType` exists!), `Episode.tracked_source` / `OrphanedTrackingRecord.tracked_source` (`"match"`, `"import"`), `RssConfigSnapshot.snapshot_type` (`"import"`, `"pre_publish"`, `"post_publish"`) | Typed `Mapped[ContentType \| None]` etc. via `str_enum(..., native_enum=False)`, so no DDL change. Check the values in existing data first (plan Task 4 Step 1). |
| M6 | Each layer re-states which `Show` columns are TMDB-owned, user-owned or derived | `services/tmdb_mapping.build_show_fields` keys, `show_metadata_backfill._SKIP_FIELDS`, `db_import_tasks._SHOW_HANDLED_COLUMNS`, `show_rematch._apply_tmdb_metadata` | `mapped_column(..., info={"source": "tmdb" \| "user" \| "derived"})` on every `Show` column, plus `models/show.py: show_columns(source) -> frozenset[str]`. A guard test checks that every column is tagged and that `build_show_fields` returns exactly the `"tmdb"` set, plus `sys_name`. |
| M7 | Partial "registration" imports | `database.py` (5 of 11 modules, each `# noqa: F401`), `alembic/env.py` (2 modules) | `import jidou.models  # noqa: F401  (registers every mapper)`, once in each file |
| M8 | Redundant `nullable=True` next to `Mapped[X \| None]` (SQLAlchemy 2 infers it) | 40 columns (`show.py` 27, `episode.py` 7, `downloaded_file.py` 5, `orphan.py` 1) | Remove. `alembic check` proves there is no DDL change. **Low**: cosmetic. |
| M9 | No index for the most common `Episode` lookup: `(show_id, season_number, episode_number)` and `(show_id, absolute_episode_number)` in `services/episode_lookup.resolve_episode`, which runs per file during matching | `episode.py` | Non-unique composite indexes, created by a new migration. Non-unique because duplicates are tolerated on purpose (issue #313). |

## 4. Complexity hotspots

None. `ruff --select C901,PLR0911,PLR0912,PLR0915` passes. The only
logic in the layer is `DownloadedFile.new_from_remote` and the
`__repr__` methods.

## 5. Dead or redundant paths

| ID | Item | Action |
|---|---|---|
| D1 | The `database.py` model imports exist only for side effects and cover only 5 of the 11 models | Replaced by M7 |
| D2 | `FileStatus.PENDING` ("legacy — replaced by DISCOVERED") is still referenced in one place (`file_reconciliation._IN_FLIGHT_STATUSES`) | **Decision** (§6): the value cannot be dropped without checking for live rows and rewriting the PostgreSQL enum type |
| — | `__repr__` on 9 models | **No action.** These are hand-written on purpose for debugging. |

## 6. Divergences and decisions (not changed by this plan)

1. **`lazy="noload"` on `DownloadedFile.show` / `.episode`** (every
   other relationship uses `lazy="raise"`). It is load-bearing. Routes
   that serialize a file without `selectinload` (for example, the
   manual-match response) depend on getting `null` for those fields
   instead of an error. Switching to `raise` is safer but needs every
   `DownloadedFileResponse` path audited first.
2. **Dates stored as strings.** `Show.release_date` and `last_air_date`
   are `String(20)`, while `Episode.air_date` is a `Date`. This works
   only because ISO strings sort correctly. Converting them needs a data
   migration.
3. **The `FileStatus.PENDING` legacy value** (D2): run a
   `SELECT count(*) … WHERE status = 'pending'`, then decide whether to
   migrate the remaining rows and drop the value.
4. **`Show` as a 45-column table** combining a TMDB metadata cache, user
   overrides and matching data. Splitting it physically is not
   proposed. M6 gets the benefit without a migration.
5. **`BackgroundTask.task_type` is a free string** (`"download"`,
   `"scan"`, …). It is left alone because the API plan's `TASK_REGISTRY`
   becomes the source of truth for task types.

## 7. Priorities

- **High:** M1 drift plus the `alembic check` CI gate. Today it is one
  careless `--autogenerate` away from dropping the alias index.
- **Medium:** M2/M3 status vocabulary in the models, M4 enum helper, M6
  column provenance, M9 lookup index.
- **Low:** M5 typed vocabularies, M7 registration imports, M8 redundant
  `nullable`.

## 8. Interaction with the other plans

- **Services plan Task 14** adds `progress.TERMINAL_STATUSES`, and
  **workers plan Task 6** consumes it. With M2, both point at
  `models/task.py: TERMINAL_TASK_STATUSES` instead. If those PRs have
  already merged, this plan's Task 3 moves the constant and updates
  their importers. The merged app-wide plan should reconcile the three
  wordings into one task.
- **Workers plan Task 5** (table-driven restore) should build its
  `_SHOW_COLUMNS` from M6's `show_columns(...)`. The order is: this
  plan's Task 5 first, then workers Task 5. Otherwise workers Task 5
  hand-writes the list once more.
- **Services plan Task 6** fixes `llm_match_episode`'s lookup. M9's
  index speeds up the same query path.
- **API plan.** M3 changes `BackgroundTask.status` from `str` to
  `TaskStatus`. Response schemas serialize a `StrEnum` as its value, so
  JSON output is unchanged, and the API plan's OpenAPI snapshot catches
  any change in the schema.
