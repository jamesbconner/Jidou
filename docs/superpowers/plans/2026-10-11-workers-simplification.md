# Workers Layer Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the wrapper boilerplate and the two complexity hotspots
in `src/jidou/workers/` without
changing externally observable behavior. These must stay the same:
Celery task names and signatures, `BackgroundTask` state transitions,
`progress_message` / `result_summary` contents, WebSocket messages, and
soft-time-limit handling.

**Architecture:**
- Collapse each task's entrypoint into a single harness call
  (`run_harnessed`).
- Move the per-event-loop engine lifecycle into
  `database.task_sessionmaker()`.
- Build `SFTPService` from settings with a factory, and build summaries
  from result dataclasses with `summarize()`.
- Rewrite the database-restore task as column tables plus one function
  per section.

First, a ratchet, an include-list guard, a visibility-timeout invariant
test and golden-summary tests pin today's behavior.

**Tech Stack:** Python 3.13, Celery, SQLAlchemy 2 (async), redis-py
asyncio, pytest (+ pytest-asyncio), ruff, mypy (strict), uv.

**Spec:** `docs/superpowers/specs/2026-10-11-workers-simplification-design.md`.
Read it first. Finding IDs (W*, D*) and section numbers (§) refer to it.

> **Status note:** This plan covers the workers layer only. It will be
> merged with the API, services and orchestrators plans, and the plans
> for the remaining layers, before execution. Line numbers were correct at
> commit `2e202f5`. Find code by its quoted text, not by line number.

## Global Constraints

- **No behavior change.** The trending task (spec D1) is kept; see
  jamesbconner/Jidou#655. Every Celery task name, every positional/keyword parameter, every
  `time_limit` / `soft_time_limit`, every `result_summary` key and value,
  every `progress_message` and every emitted WebSocket payload stays the
  same. Task 1's golden-summary tests enforce the summaries.
- **No backward-compatibility shims.** When a name moves, update every
  importer and every `patch("…")` target in `tests/`. Do not re-export it
  from the old location. Each task lists the patch targets it moves.
- **Do not edit existing test assertions** to make a refactor pass. Only
  import paths, patch targets and fixture wiring may change.
- **Commands:** use `uv` only. Never use `pip` or `python -m venv`.
- **Style:** ruff target `py313`, `line-length = 100`; mypy
  `strict = true`; Google-style docstrings on every public function and
  class; explicit type hints; a comment on each non-obvious branch
  explaining *why* it is there.
- **Pre-push checks, in this order:** `uv run ruff check .` →
  `uv run ruff format --check .` → `uv run mypy src/` →
  `uv run bandit -r src/ -l` → `uv run pytest`.
- **After code changes:** run `graphify update .`.
- **Git:** never commit to `main`. Use one branch and one PR per row of
  "PR grouping", work serially, and merge with `--merge`. Each PR ends with
  a version-bump commit following the repo convention (see commit
  `69c7290`).
- **Commit trailer:** end every commit message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A soft time limit fires inside a task.** Expected:
   `mark_task_timed_out(task_id)` runs on a fresh event loop, then
   `SoftTimeLimitExceeded` is re-raised. It is not swallowed, and it is
   not wrapped in another exception. Pinned by Task 2's
   `test_run_harnessed_marks_timeout_and_reraises`, plus the existing
   per-module timeout tests.
2. **A backup restore with explicit `null` timestamps and a malformed
   `air_date`.** Expected: `file_tracked_at` / `watched_at` are cleared,
   `air_date` keeps its old value, and `local_path` keeps its live value
   when the backup's value is `null` (spec §6 item 2). Pinned by Task 5's
   `test_update_episode_null_and_malformed_rules` and
   `test_update_show_preserves_local_path_and_cached`.
3. **A new column added to `Show` or `Episode` without restore support.**
   Expected: the existing `check_restore_field_coverage` test still fails
   until the column is handled. Task 5 must keep that function driving
   off the same sets that the copy uses.
4. **A task module added without adding it to `celery_app.include`.**
   Expected: a test fails rather than the task silently never
   registering on the worker. Pinned by Task 1's
   `test_every_task_module_is_included`.
5. **A new task `time_limit` above the broker `visibility_timeout`.**
   Expected: a test fails, because otherwise Redis redelivers the
   running task every hour. Pinned by Task 1's
   `test_visibility_timeout_exceeds_every_task_time_limit`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tests/test_workers_architecture.py` | Create | Ratchet, include-list guard, visibility-timeout invariant |
| `tests/test_worker_summaries.py` | Create | Golden `result_summary` / `message` for 7 workers |
| `src/jidou/workers/_harness.py` | Modify | Gains `run_harnessed`, `mark_task_timed_out` (moved from services), `summarize`, `_finish` |
| `src/jidou/database.py` | Modify | Gains `task_sessionmaker()` |
| `src/jidou/services/sftp_service.py` | Modify | Gains `create_sftp_service(settings)` |
| `src/jidou/services/progress.py` | Modify | Loses `mark_task_timed_out` |
| `src/jidou/workers/*_tasks.py` | Modify | As described per task |
| `src/jidou/workers/tasks.py` | Modify (Task 3 only) | Trending task, **kept** (see jamesbconner/Jidou#655); switches to `task_sessionmaker` |
| `src/jidou/workers/celery_app.py` | Modify | `LONG_TASK_LIMITS`; drop `jidou.workers.tasks` from `include` |

## PR grouping

| PR | Branch | Tasks | Must run after |
|---|---|---|---|
| 1 | `refactor/workers-baseline-guards` | 1 | — |
| 2 | `refactor/workers-entrypoint-engine` | 2, 3 | PR 1 |
| 3 | `refactor/workers-factories-summaries` | 4 | PR 2 |
| 4 | `refactor/workers-db-import` | 5 | PR 2 |
| 5 | `refactor/workers-scheduled-harness` | 6, 7 | PR 2, **services plan PR 9** (`TERMINAL_STATUSES`) |
| 6 | `refactor/workers-low-cleanups` | 8, 9 | all above; **services plan PR 6** (`redis_session`) |

### Complexity ratchet rule

`_WORKERS_MAX_COMPLEXITY` starts at **16** (Task 1) and ends at **8**
(Task 9). It is lowered to the new maximum reported by the command below
whenever the worst function improves, and it never goes up.

```bash
uv run ruff check src/jidou/workers --select C901 \
  --config lint.mccabe.max-complexity=1 --output-format concise --no-cache \
  | sed -E 's/.*\(([0-9]+) > 1\).*/\1/' | sort -n | tail -1
```

---

## Phase 0 — Safety net

### Task 1: Ratchet, include-list guard, visibility invariant, golden summaries

**Files:**
- Create: `tests/test_workers_architecture.py`, `tests/test_worker_summaries.py`

**Interfaces:**
- Produces: `_WORKERS_MAX_COMPLEXITY = 16`.

- [ ] **Step 1: Write the ratchet test.**
  `test_workers_cyclomatic_complexity_ratchet` uses the same
  `subprocess.run([sys.executable, "-m", "ruff", "check", …])` mechanism
  as the other layer plans.
- [ ] **Step 2: Write `test_every_task_module_is_included`.** Build the
  set of `jidou.workers.<stem>` for every `src/jidou/workers/*.py` file
  that contains `@shared_task`. Assert it equals
  `set(celery_app.conf.include)`.
- [ ] **Step 3: Write `test_visibility_timeout_exceeds_every_task_time_limit`.**
  Import every included module. Then, for each registered task in
  `celery_app.tasks.values()` whose name starts with `"jidou."`, take
  `limit = task.time_limit or celery_app.conf.task_time_limit` and
  assert `celery_app.conf.broker_transport_options["visibility_timeout"] > limit`.
- [ ] **Step 4: Write `test_worker_summaries.py`.** For each worker
  below, patch `jidou.workers.<module>.run_task_workflow` with an
  `AsyncMock`, call the module's async implementation, and capture the
  `work` argument. Patch the orchestrator's `run` to return the fixed
  result shown. Then
  `wr = await work(MagicMock(), AsyncMock(), AsyncMock())`, and assert
  `wr.result_summary`, `wr.message` and `wr.complete_summary` equal
  literal values. Paste those literals from a run against the current
  code, before any refactor.

  | Worker | Async impl | Orchestrator result to return |
  |---|---|---|
  | route | `_route_files(tid, dry_run=True)` | `RouteResult(3, 1, True)` |
  | match | `_match_files(tid, dry_run=False)` | `ParseResult(5, 3, 1, 1, False)` |
  | download | `_download_files(tid, dry_run=False)` | `DownloadResult(2, 2048, 1, False)` |
  | scan | `_scan_remote(tid, dry_run=False)` | `ScanResult(2, 10, 4, 6, 1)` |
  | seed | `_seed_remote(tid, dry_run=True)` | `SeedResult(2, 0, 9, 7, 2, {"routed": 2}, True)` |
  | backfill | `_backfill(tid, dry_run=False)` | `MetadataBackfillResult(4, 3, 1, ["A", "B", "C"], ["D"])` |
  | import | `_path_import(tid, "/x/Show/ep01.mkv", "anime", False, "full")` | `PathImportResult` with one `ShowImportResult` (every field non-default) |

  Patch out the SFTP, TMDB and LLM constructions in the same way the
  existing `test_workers.py` tests do. The import worker also needs the
  existing `parse_file` / `update_task_status` patches.
- [ ] **Step 5: Run.**
  `uv run pytest tests/test_workers_architecture.py tests/test_worker_summaries.py -v`.
  Expected: all pass against the current code. Check that the ratchet
  bites: set it to 15, confirm it fails and names `_db_import`, then
  restore it.
- [ ] **Step 6: Commit.** `test(workers): ratchet, include guard, visibility invariant, golden summaries`

---

## Phase 1 — High

### Task 2: One entrypoint helper; move `mark_task_timed_out` into the harness (W1)

**Files:**
- Modify: `src/jidou/workers/_harness.py`, every module that has a `SoftTimeLimitExceeded` handler (10 modules, 11 tasks), `src/jidou/services/progress.py`, `tests/test_progress.py` (move the `mark_task_timed_out` tests to `tests/test_worker_harness.py`), and the tests that patch the moved names

**Interfaces:**
- Produces, in `_harness.py`:
  ```python
  def run_harnessed[T](celery_task_id: str, coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
      """asyncio.run(coro_factory()); on SoftTimeLimitExceeded: asyncio.run(mark_task_timed_out(id)) then re-raise."""
  async def mark_task_timed_out(celery_task_id: str) -> None   # moved verbatim from services/progress.py
  ```
  Each Celery function body becomes, for example,
  `return run_harnessed(self.request.id, lambda: _route_files(self.request.id, dry_run))`.
  The `@shared_task(...)` decorators, the signatures and the docstrings
  do not change.
- Patch retargets. The new target for each of these is
  `jidou.workers._harness.mark_task_timed_out`:
  `jidou.workers.{route,scan,seed,sync,rss}_tasks.mark_task_timed_out`
  (7 sites at `2e202f5`).

- [ ] **Step 1: Write the tests** in `tests/test_worker_harness.py`.
  - `test_run_harnessed_returns_value`.
  - `test_run_harnessed_marks_timeout_and_reraises`: the factory raises
    `SoftTimeLimitExceeded`; `mark_task_timed_out` is patched; assert it
    was awaited with the id and that `SoftTimeLimitExceeded`
    propagates.
  - `test_run_harnessed_other_exceptions_do_not_mark_timeout`.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it.** Move `mark_task_timed_out` and its tests.
  Rewrite all 11 entrypoints. Remove the now-unused `asyncio` and
  `SoftTimeLimitExceeded` imports from the task modules.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_worker_harness.py tests/test_workers.py tests/test_rss_tasks.py tests/test_db_import_tasks.py tests/test_task_cancellation.py tests/test_progress.py tests/test_worker_summaries.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** `refactor(workers): single run_harnessed entrypoint; timeout marking lives in the harness`

### Task 3: Task-scoped engine (W4)

**Files:**
- Modify: `src/jidou/database.py`, `src/jidou/workers/_harness.py`, `scheduled_tasks.py`, `tasks.py`, and the tests that patch the moved names
- Test: `tests/test_database.py` (append)

**Interfaces:**
- Produces, in `database.py`:
  ```python
  @asynccontextmanager
  async def task_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
      """Fresh engine bound to the running event loop (pool_pre_ping=True, expire_on_commit=False); disposed on exit."""
  ```
  The docstring must keep the existing explanation of *why* a fresh
  engine is needed: each Celery task runs its own `asyncio.run()` loop,
  and a module-level pool would be bound to a dead loop.
  - `run_task_workflow` wraps its body in
    `async with task_sessionmaker() as session_factory:`.
  - `mark_task_timed_out`, `_try_claim_task` and `_delete_task_record`
    use it too. The scheduled helpers' `engine = None` / `if engine is
    not None` guards go away.
- Patch retargets. The new targets are
  `jidou.database.create_async_engine` and
  `jidou.database.async_sessionmaker`:
  `jidou.workers._harness.create_async_engine` (14),
  `jidou.workers._harness.async_sessionmaker` (14),
  `jidou.workers.scheduled_tasks.create_async_engine` (2), and the
  `jidou.workers.tasks.*` pair (2 each).

- [ ] **Step 1: Write the tests.**
  - `test_task_sessionmaker_disposes_engine_on_exit`: patch
    `jidou.database.create_async_engine`; assert `dispose` was awaited
    once.
  - `test_task_sessionmaker_disposes_engine_on_error`.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it, and retarget the patches.**
- [ ] **Step 4: Verify.** `uv run pytest tests/test_database.py tests/test_worker_harness.py tests/test_workers.py tests/test_scheduled_tasks.py tests/test_rss_tasks.py tests/test_task_cancellation.py tests/test_progress.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** `refactor(workers): task_sessionmaker owns the per-loop engine lifecycle`

### Task 4: `create_sftp_service` and `summarize` (W2, W3)

**Files:**
- Modify: `src/jidou/services/sftp_service.py`, `src/jidou/workers/_harness.py`, `download_tasks.py`, `scan_tasks.py`, `seed_tasks.py`, `sync_tasks.py`, `rss_tasks.py`, `route_tasks.py`, `match_tasks.py`, `backfill_tasks.py`, `import_tasks.py`, and the tests that patch the moved names
- Test: `tests/test_sftp_service.py`, `tests/test_worker_harness.py` (append)

**Interfaces:**
- Produces:
  ```python
  # services/sftp_service.py
  def create_sftp_service(settings: Settings) -> SFTPService
      # host=settings.sftp_host or "", port, username, password, key_path, known_hosts=None,
      # max_workers, max_retries, retry_delay — exactly the worker construction today
  # workers/_harness.py
  def summarize(result: DataclassInstance, *, dry_run: bool) -> dict[str, object]   # {**asdict(result), "dry_run": dry_run}
  ```
  - `summarize` is used by route, match, download, scan, seed, backfill
    and import. It stays a module-level function so `asdict` recurses
    into `PathImportResult.show_results`.
  - Sync and both RSS workers keep their hand-picked summaries (spec §3
    W3).
  - `rss_tasks._build_sftp` is deleted.
  - `api/routes/config.py` is **not** changed (spec §6 item 1).
- Patch retargets. The new target for each is
  `jidou.workers.<module>.create_sftp_service`:
  `jidou.workers.{scan,seed,sync}_tasks.SFTPService` (4) and
  `jidou.workers.rss_tasks._build_sftp` (8). A patched factory returns
  `mock.return_value`, which is the same value a patched class returns
  when called. Assertions do not change.

- [ ] **Step 1: Write the tests.**
  - `test_create_sftp_service_maps_settings`: a fake `Settings` with
    distinct values. Assert each attribute on the returned service, and
    that `host` is `""` when `sftp_host` is `None`.
  - `test_summarize_adds_dry_run_and_recurses`: a nested dataclass.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it, and retarget the patches.**
- [ ] **Step 4: Verify.** `uv run pytest tests/test_worker_summaries.py tests/test_workers.py tests/test_rss_tasks.py tests/test_sftp_service.py tests/test_worker_harness.py tests/test_seed_orchestrator.py tests/test_api_import_routes.py -q`.
  Expected: all pass. The golden summaries in Task 1 must not change.
- [ ] **Step 5: Commit.** `refactor(workers): settings-driven SFTP factory and dataclass summaries`

### Task 5: Database-restore decomposition (W5, W6)

**Files:**
- Modify: `src/jidou/workers/db_import_tasks.py`
- Test: `tests/test_db_import_tasks.py` (append)

**Interfaces:**
- Produces (private):
  ```python
  @dataclass(frozen=True)
  class _Column:
      name: str
      default: object = None              # used by _build_* when the key is absent
      convert: Callable[[object], object] | None = None   # e.g. _parse_iso_date / _parse_iso_datetime
  _SHOW_COLUMNS: tuple[_Column, ...]      # replaces _SHOW_HANDLED_COLUMNS; frozenset view kept for coverage
  _EPISODE_COLUMNS: tuple[_Column, ...]

  # columns never touched on update; local_path handled by its own rule
  _SHOW_INSERT_ONLY: frozenset[str] = frozenset({"tmdb_id", "cached"})
  # update-time rules from spec §6 item 2
  _EPISODE_UPDATE_SPECIAL: frozenset[str] = frozenset({"show_id", "tmdb_id", "air_date", "file_tracked_at", "watched_at"})

  @dataclass
  class _RestoreCounts:
      created: int = 0
      updated: int = 0

  async def _restore_shows(session, task_id: str, rows: list[dict[str, Any]], progress: _Progress) -> tuple[_RestoreCounts, dict[int, int]]
  async def _restore_episodes(session, task_id: str, rows: list[dict[str, Any]], show_id_map: dict[int, int], progress: _Progress) -> _RestoreCounts
  async def _restore_watchlist(session, task_id: str, rows: list[dict[str, Any]], show_id_map: dict[int, int], progress: _Progress) -> _RestoreCounts
  ```
  - `_Progress` is a small private class that holds `current`, `total`
    and `on_progress`. It reproduces today's cadence exactly: shows
    report after every row; episodes report when `current % 100 == 0`;
    the watchlist never reports.
  - Each restore function keeps its `check_task_cancelled` call per row,
    its skip-and-warn branches (same log text), and its `commit()` at
    the end.
  - `check_restore_field_coverage` derives its handled sets from the
    `_Column` tables.

- [ ] **Step 1: Write the characterization tests** before refactoring.
  - `test_update_episode_null_and_malformed_rules`: start from an
    episode with all fields set. Apply
    `{"file_tracked_at": None, "watched_at": "garbage", "air_date": None}`.
    Assert `file_tracked_at is None`, `watched_at` is unchanged and
    `air_date` is unchanged.
  - `test_update_show_preserves_local_path_and_cached`: a backup row
    with `local_path=None` and `cached=False` on a show with a path and
    `cached=True`. Assert both are unchanged.
  - `test_build_show_defaults`: a row with only `tmdb_id` and `title`.
    Assert `media_type == "tv"`, `vote_count == 0`, `cached is False`,
    `track_missing_episodes is True`.
  - `test_episode_progress_cadence`: 250 episode rows. Assert the
    episode-phase `on_progress` calls happen at `current` values that
    are multiples of 100.
- [ ] **Step 2: Run.** Expected: all pass today. They guard the
  refactor.
- [ ] **Step 3: Implement the column tables and the three restore
  functions.** `_work` becomes: parse the JSON, set the progress total
  (the direct `update_task_status` call stays, per spec §6 item 4), then
  the three restore calls, then the summary.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_db_import_tasks.py tests/test_api_import_routes.py -q`.
  Expected: all pass, including `check_restore_field_coverage() ==
  {"Show": set(), "Episode": set()}`. `_db_import` and `_work` must be
  ≤ 6.
- [ ] **Step 5: Commit.** `refactor(workers): table-driven backup restore, one function per section`

---

## Phase 2 — Medium

### Task 6: Scheduled-task table, shared status helpers, harness `_finish` (W7, W8, D5)

**Files:**
- Modify: `src/jidou/workers/scheduled_tasks.py`, `src/jidou/workers/_harness.py`
- Test: `tests/test_scheduled_tasks.py`, `tests/test_worker_harness.py` (append)

**Interfaces:**
- Produces:
  ```python
  # scheduled_tasks.py
  async def _run_scheduled(
      task_type: str, load_task: Callable[[], Any], *, skip_reason: Callable[[], str | None] | None = None,
  ) -> str
  # _harness.py
  async def _finish(session: AsyncSession, celery_task_id: str, result: WorkflowResult) -> str | None  # soft-failure message or None
  ```
  - `_run_scheduled` does the following:
    1. Calls `skip_reason()`. If it returns a message, logs it as a
       warning and returns `"skipped"`. This is how
       `RSS_CONFIG_REMOTE_PATH` being unset is handled.
    2. Generates the uuid.
    3. Claims the task. If claiming fails, logs
       `"Scheduled %s skipped: a %s task is already active"` and returns
       `"skipped"`.
    4. Calls `load_task()`, which does the lazy import.
    5. Calls `_dispatch_scheduled`.

    The two existing info-level skip messages ("Scheduled sync skipped:
    a sync task is already active" and "Scheduled RSS import skipped: an
    rss_import task is already active") differ in their articles and
    labels. Keep them byte-for-byte by passing the message in, or
    accept a change to log text; logs are not a contract. Pick one and
    state it in the PR.
  - `_try_claim_task` uses `progress.get_active_task(session, task_type)
    is not None` instead of its own count query. Delete the local
    `_ACTIVE_STATUSES`.
  - The harness's `_TERMINAL_STATUSES` becomes
    `progress.TERMINAL_STATUSES`.
  - Move `from sqlalchemy import delete` to the top-level imports (D5).

- [ ] **Step 1: Write the tests.**
  - `test_run_scheduled_skip_reason_short_circuits_before_claim`.
  - `test_finish_soft_failure_returns_message_and_marks_failed`.
  - `test_finish_success_emits_complete_only_when_still_completed`:
    `update_task_status` returns a row whose status is not COMPLETED
    (someone cancelled it concurrently). Assert no `"complete"`
    broadcast. This pins today's guard.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Verify.** `uv run pytest tests/test_scheduled_tasks.py tests/test_worker_harness.py tests/test_task_cancellation.py tests/test_rss_tasks.py -q`.
  Expected: all pass. `run_task_workflow` must be ≤ 7.
- [ ] **Step 5: Commit.** `refactor(workers): table-driven scheduled dispatch; shared task-status helpers`

### Task 7: Redundant code (D2, D3)

`tasks.py` / `fetch_trending_shows_task` (spec D1) is **kept** (roadmap
decision D3). Putting it to use is tracked in jamesbconner/Jidou#655, so this task does
not touch it.

**Files:**
- Modify: the 8 task modules with an unused `logger`, and the 10 `run_task_workflow(…, progress_total=0, …)` calls

- [ ] **Step 1: Remove the unused `logger` definitions and the explicit
  `progress_total=0` arguments.** Sync keeps `progress_total=5`.
- [ ] **Step 2: Verify.** `uv run pytest tests/test_workers.py tests/test_workers_architecture.py -q`.
  Expected: all pass.
- [ ] **Step 3: Commit.** `chore(workers): drop unused loggers and default progress_total arguments`

---

## Phase 3 — Low and closeout

### Task 8: Redis lock helper, library-root helper, shared long-task limits (W9, W10, W11)

**Files:**
- Modify: `src/jidou/services/redis_conn.py` (from services plan Task 9), `image_cache_tasks.py`, `src/jidou/services/path_resolution.py`, `import_tasks.py`, `celery_app.py`, `sync_tasks.py`
- Test: `tests/test_redis_conn.py`, `tests/test_path_resolution.py`, `tests/test_image_cache_tasks.py` (append)

**Interfaces:**
- Produces:
  ```python
  # services/redis_conn.py
  @asynccontextmanager
  async def redis_try_lock(url: str, key: str, ttl_seconds: int) -> AsyncIterator[bool]
      # SET key "1" NX EX ttl; yields acquired; DEL only if acquired; always closes the client
  # services/path_resolution.py
  def library_root(content_type: str | None, *, tv: str, anime: str, movie: str) -> str
      # "movie" -> movie, "anime" -> anime, anything else -> tv
  # celery_app.py
  LONG_TASK_LIMITS: Final[dict[str, int]] = {"time_limit": 25200, "soft_time_limit": 21600}
  ```
  - `resolve_show_local_path` uses `library_root` for its base
    directory. Its movie case still returns the bare root.
  - `import_tasks._host_root_for_content_type` becomes
    `library_root(content_type, tv=settings.local_tv_host_path, anime=…, movie=…)`.
  - `sync_all_task` and `path_import_task` use
    `@shared_task(bind=True, **LONG_TASK_LIMITS)`. Their explanatory
    comments move next to `LONG_TASK_LIMITS`, and the `visibility_timeout`
    comment refers to it by name.

- [ ] **Step 1: Write the tests.**
  - `test_redis_try_lock_not_acquired_does_not_delete`.
  - `test_redis_try_lock_releases_on_error`.
  - `test_library_root_mapping`, covering `None` → tv.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it.** `_purge_stale_images` becomes
  `async with redis_try_lock(settings.redis_url, _PURGE_LOCK_KEY, _PURGE_LOCK_TTL_SECONDS) as acquired:`,
  followed by today's body.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_redis_conn.py tests/test_path_resolution.py tests/test_image_cache_tasks.py tests/test_workers.py tests/test_workers_architecture.py tests/test_show_creation.py -q`.
  Expected: all pass. The visibility invariant from Task 1 still holds.
- [ ] **Step 5: Commit.** `refactor: shared Redis try-lock, library-root mapping and long-task limits`

### Task 9: Final ratchet, docs and graph

- [ ] **Step 1: Set `_WORKERS_MAX_COMPLEXITY = 8`.**
- [ ] **Step 2: Check the docs.**
  `grep -rn "mark_task_timed_out\|_build_sftp" docs/*.md`
  and fix any stale references.
- [ ] **Step 3: Run the full pre-push sequence** from Global Constraints.
  Expected: everything clean.
- [ ] **Step 4: Run `graphify update .`** and commit the result.
- [ ] **Step 5: Commit.** `chore(workers): final complexity ratchet (8) and docs refresh`

---

## Deferred to the merged app-wide plan

- A harness-level `set_progress_total` callback for the import workers
  (spec §6 item 4). It changes `WorkFn` for all 11 harnessed tasks.
- Aligning the API's SFTP connectivity test with `create_sftp_service`
  (spec §6 item 1).
- Re-pointing `ProgressFn` / `EventFn` in `_harness.py` at the
  orchestrators plan's `services/callbacks.OnProgress` / `OnEvent`, once
  both plans have landed.
- Moving `mark_task_timed_out` (this plan) together with the services
  plan's deferred move of `enqueue_task` / `TaskDispatchError` /
  `get_active_task` out of `progress.py`.
