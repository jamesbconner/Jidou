# Orchestrators Layer Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce cyclomatic complexity and duplication in
`src/jidou/orchestrators/` without changing externally observable
behavior. Specifically, these must not change: `DownloadedFile` /
`Episode` / `Show` state transitions, event messages and their order,
result dataclass values, HTTP status codes and `detail` text, or commit
boundaries.

**Architecture:** First, a shared event sink and named callback types.
Then the large `run()` methods become thin loops over per-item command
methods that return an outcome enum. Copied mechanisms move into private
helper modules (`_events.py`, `_show_provisioning.py`,
`_remote_inventory.py`). The web-layer leakage becomes domain exceptions,
mapped to HTTP in one handler. Before any of that, a complexity ratchet,
a layering guard, and tests that pin how each orchestrator reacts to a
failing event callback are put in place, so every later task is checked
against them.

**Tech Stack:** Python 3.13, SQLAlchemy 2 (async), FastAPI (only in the
exception handler), rapidfuzz, pytest (+ pytest-asyncio), ruff, mypy
(strict), uv.

**Spec:** `docs/superpowers/specs/2026-10-11-orchestrators-simplification-design.md`.
Read it first. Finding IDs (R*, O*, D*) and section numbers (§) refer to
it.

> **Status note:** This plan covers the orchestrators layer only. It will be
> merged with the API and services plans, and the plans for the remaining
> layers, before execution. Line numbers were correct at commit `62cb347`.
> Find code by its quoted text, not by line number.

## Global Constraints

- **No behavior change.** Every event `(level, message, ctx)` that is
  emitted, and the order of those events, stays byte-for-byte the same.
  So do result dataclass field values, `FileStatus` transitions,
  `error_message` text, and where `commit()` / `rollback()` / `flush()`
  are called. HTTP status codes and `{"detail": …}` bodies also stay the
  same; Task 9 moves where they are produced, not what they are.
- **Keep each orchestrator's event-failure behavior** (spec §6 item 1).
  Download, parse, route and scan swallow `on_event` errors. Sync, path
  import and RSS import/publish let them propagate. Task 1 pins this.
- **Never swallow `on_progress` errors.** The worker harness raises
  `TaskCancelledError` through `on_progress` on purpose.
- **No backward-compatibility shims.** When a name moves, update every
  importer and every `patch("…")` target in `tests/`. Do not re-export it
  from the old location.
- **Do not edit existing test assertions** to make a refactor pass. Only
  import paths, patch targets and fixture wiring may change. Task 9 is
  the one exception: tests that assert an `HTTPException` is raised
  inside an orchestrator change to assert the new domain exception, with
  the same `detail` string.
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

1. **A cancelled download batch** (the `BaseException` path around
   `asyncio.gather`). Expected: transfers that already finished are
   credited, and the rest are marked `ERROR "Download interrupted"`
   exactly once each. Pinned by the existing cancellation tests in
   `test_download_orchestrator.py`, and by Task 7's
   `test_record_transfer_is_shared_by_normal_and_cancel_paths`.
2. **A ROUTING retry where the staging file is gone and the destination
   size differs.** Expected: the file is marked `ERROR`, not `ROUTED`,
   and its `local_path` is put back to the staging path. Pinned by the
   existing route tests, and by Task 5's
   `test_route_one_retry_size_mismatch_is_failure`.
3. **Lost show-creation race inside path import.** Expected: the show
   is looked up again **by title** (spec §6 item 2), then
   `_sync_episodes_if_needed` runs, and the action is `"found"`. Pinned
   by Task 3's `test_insert_show_or_existing_uses_supplied_refind`, and
   the existing `test_path_import.py` race tests.
4. **The same TMDB episode id appears twice in one upsert batch** (an
   episode group listing the same episode in two sub-groups). Expected:
   one row; the second occurrence counts as `episodes_skipped`, which is
   what autoflush produces today. Pinned by Task 10's
   `test_duplicate_tmdb_id_in_batch_updates_single_row`.
5. **Event logging fails mid-run.** Expected: download, parse, route and
   scan finish with the same counts; sync and path import raise. Pinned
   by Task 1's `test_*_event_failure_*` tests.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tests/test_orchestrators/test_architecture.py` | Create | Complexity ratchet, the "no FastAPI import" guard, and the "no foreign private-name import" guard |
| `tests/test_orchestrators/test_event_failure_semantics.py` | Create | Pins whether each orchestrator swallows or propagates `on_event` errors |
| `src/jidou/services/callbacks.py` | Create | `OnEvent`, `OnProgress` type aliases (R2) |
| `src/jidou/orchestrators/_events.py` | Create | `EventSink`, `log_only_event` (R1, O4) |
| `src/jidou/orchestrators/_show_provisioning.py` | Create | `insert_show_or_existing`, `sync_episodes_best_effort`, `generate_aliases_best_effort` (R3) |
| `src/jidou/orchestrators/_remote_inventory.py` | Create | `RootListing`, `WalkOutcome`, `list_roots`, `walk_directories` (R4) |
| `src/jidou/orchestrators/errors.py` | Create | `OrchestratorError`, `NotFoundError`, `InvalidRequestError`, `UpstreamError` (O1, O2) |
| `src/jidou/services/fuzzy_match.py` | Create (Task 14) | `unambiguous_best_match` (R17) |
| `src/jidou/orchestrators/*.py` | Modify | As described per task |
| `src/jidou/services/episode_tracking.py`, `episode_lookup.py` | Modify | `link_file_to_episode` (R10), `count_show_episodes` (R9) |
| `src/jidou/main.py`, `src/jidou/api/routes/{files,shows,rss…}.py` | Modify (Task 9) | Exception handler; inject `tmdb` into `ManualMatchOrchestrator` |

## PR grouping

| PR | Branch | Tasks | Must run after |
|---|---|---|---|
| 1 | `refactor/orch-baseline-guards` | 1 | — |
| 2 | `refactor/orch-event-sink` | 2 | PR 1 |
| 3 | `refactor/orch-show-provisioning` | 3 | PR 2, **services plan PR 7** |
| 4 | `refactor/orch-scan-seed-inventory` | 4 | PR 2 |
| 5 | `refactor/orch-route-parse-commands` | 5, 6 | PR 2 |
| 6 | `refactor/orch-download-decompose` | 7 | PR 2 |
| 7 | `refactor/orch-sync-episode-link` | 8 | PR 5 |
| 8 | `refactor/orch-domain-errors` | 9 | PR 3, **API plan PR 8** |
| 9 | `refactor/orch-tmdb-upsert` | 10 | PR 2 |
| 10 | `refactor/orch-rss-import-publish` | 11 | PR 2 |
| 11 | `refactor/orch-path-import` | 12 | PR 3, **services plan PR 8** (`basename_any`) |
| 12 | `refactor/orch-low-cleanups` | 13, 14, 15 | all above; **services plan PRs 3 and 8** |

### Complexity ratchet rule

`_ORCH_MAX_COMPLEXITY` in `tests/test_orchestrators/test_architecture.py`
starts at **28** (Task 1) and ends at **10** (Task 15). Any task that
removes the current worst offender lowers it to the new maximum reported
by:

```bash
uv run ruff check src/jidou/orchestrators --select C901 \
  --config lint.mccabe.max-complexity=1 --output-format concise --no-cache \
  | sed -E 's/.*\(([0-9]+) > 1\).*/\1/' | sort -n | tail -1
```

The value only goes down. It never goes up.

---

## Phase 0 — Safety net

### Task 1: Ratchet, layering guards, event-failure characterization

**Files:**
- Create: `tests/test_orchestrators/test_architecture.py`, `tests/test_orchestrators/test_event_failure_semantics.py`

**Interfaces:**
- Produces: `_ORCH_MAX_COMPLEXITY = 28`,
  `_KNOWN_FASTAPI_IMPORTERS: frozenset[str]`,
  `_KNOWN_PRIVATE_IMPORTS: frozenset[tuple[str, str]]`. Task 9 empties
  the first set and Task 2 empties the second.

- [ ] **Step 1: Write the ratchet test.**
  `test_orchestrators_cyclomatic_complexity_ratchet` uses the same
  `subprocess.run([sys.executable, "-m", "ruff", "check", <dir>, "--select", "C901", "--config", f"lint.mccabe.max-complexity={_ORCH_MAX_COMPLEXITY}", "--output-format", "concise", "--no-cache"], check=False)`
  mechanism as the services plan's Task 1, and asserts
  `returncode == 0`.
- [ ] **Step 2: Write the two AST guards.** Walk every node of every
  `src/jidou/orchestrators/*.py` file.
  - `test_orchestrators_do_not_import_fastapi`: the set of module stems
    that import `fastapi` (or anything under it) `==` the allowlist:

    ```python
    # Task 9 empties this.
    _KNOWN_FASTAPI_IMPORTERS = frozenset({"manual_match_orchestrator", "show_rematch_orchestrator"})
    ```

  - `test_no_private_names_imported_across_orchestrators`: collect
    `(importer_stem, name)` for every `from jidou.orchestrators.<m> import <name>`
    where `<m>` does not start with `_` but `<name>` does. Assert the
    result `==` the allowlist:

    ```python
    # Task 2 empties this.
    _KNOWN_PRIVATE_IMPORTS = frozenset({("rss_publish_orchestrator", "_default_on_event")})
    ```

- [ ] **Step 3: Write the event-failure characterization tests.** For
  each orchestrator below, copy the setup of the named existing test,
  pass `on_event=AsyncMock(side_effect=RuntimeError("log down"))`, and
  assert the stated outcome:

  | New test | Copy setup from | Assert |
  |---|---|---|
  | `test_route_event_failure_is_swallowed` | `test_route_orchestrator.py::test_run_on_event_called_for_skip` | `run()` returns the same `RouteResult` the copied test produces |
  | `test_parse_event_failure_is_swallowed` | `test_match_orchestrator.py::test_on_event_called_on_unmatched` | `run()` returns the same `ParseResult` the copied test produces |
  | `test_download_event_failure_is_swallowed` | `test_download_orchestrator.py::test_on_event_called_in_dry_run` | `run()` returns; `files_downloaded` is unchanged from that test |
  | `test_scan_event_failure_is_swallowed` | `test_scan_orchestrator.py::test_on_event_called_for_shallow_listing_failure` | `run()` returns |
  | `test_sync_event_failure_propagates` | `test_sync_orchestrator.py::test_run_on_event_called_for_phase_results` | `pytest.raises(RuntimeError, match="log down")` |
  | `test_path_import_event_failure_propagates` | any `test_path_import.py` test that calls `run()` with `on_event` | `pytest.raises(RuntimeError, match="log down")` |

- [ ] **Step 4: Run.**
  `uv run pytest tests/test_orchestrators/test_architecture.py tests/test_orchestrators/test_event_failure_semantics.py -v`.
  Expected: everything passes against the current code. Check that the
  ratchet test bites: set it to 27, confirm it fails and names
  `DownloadOrchestrator.run`, then restore it.
- [ ] **Step 5: Commit.** `test(orchestrators): add complexity ratchet, layering guards, event-failure pins`

---

## Phase 1 — Shared mechanisms and worst hotspots (High)

### Task 2: `EventSink` and named callback types (R1, R2, O4)

**Files:**
- Create: `src/jidou/services/callbacks.py`, `src/jidou/orchestrators/_events.py`, `tests/test_orchestrators/test_events.py`
- Modify: every orchestrator signature that spells out the callback
  types (find them with
  `grep -rn "Callable\[\[str, str, dict\|Callable\[\[int, int, str\]" src/jidou`),
  `services/episode_match_llm.py`, `services/episode_file_matching.py`,
  `tests/test_orchestrators/test_architecture.py`

**Interfaces:**
- Produces, in `services/callbacks.py`:
  ```python
  OnEvent: TypeAlias = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]
  OnProgress: TypeAlias = Callable[[int, int, str], Awaitable[None]]
  ```
  `dict[str, Any]` is assignable from both `dict[str, object]` and
  `dict[str, Any]` call sites. Check this with mypy, not by eye.
- Produces, in `orchestrators/_events.py`:
  ```python
  class EventSink:
      def __init__(self, callback: OnEvent | None, *, swallow_errors: bool) -> None: ...
      async def __call__(self, level: str, msg: str, ctx: dict[str, Any] | None = None) -> None: ...


  async def log_only_event(level: str, msg: str, ctx: dict[str, Any] | None = None) -> None: ...
  ```
  - `callback is None` → no-op.
  - When `swallow_errors=True`, catch `Exception` and log
    `"Event logging failed; continuing"` with `exc_info=True`. This is
    today's text.
  - `log_only_event` is today's `rss_import._default_on_event`, moved
    and renamed.
  - An `EventSink` instance is itself an `OnEvent`, so it can be passed
    straight to the services helpers' `on_event=`.

- [ ] **Step 1: Write `test_events.py`.**
  - `test_sink_without_callback_is_noop`.
  - `test_sink_forwards_arguments`.
  - `test_sink_swallow_true_logs_and_continues`: a raising callback, and
    `caplog` contains `"Event logging failed; continuing"`.
  - `test_sink_swallow_false_propagates`.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement both modules.** Then make these replacements:
  - The four `_emit` closures in download, parse, route and scan become
    `EventSink(on_event, swallow_errors=True)`.
  - `PathImportOrchestrator._emit` becomes
    `EventSink(on_event, swallow_errors=False)`, stored in `__init__`.
  - `rss_import` and `rss_publish` use
    `on_event or log_only_event` and delete their own `_OnEvent`
    aliases.
  - All callback signatures use `OnEvent` / `OnProgress`.
  - The two services `OnEvent` aliases are replaced by imports from
    `services/callbacks.py`.
  - `_KNOWN_PRIVATE_IMPORTS` becomes empty.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_orchestrators tests/test_path_import.py tests/test_rss_import_orchestrator.py tests/test_rss_publish_orchestrator.py tests/test_seed_orchestrator.py tests/test_episode_match_llm.py tests/test_episode_file_matching.py -q`
  and `uv run mypy src/`. Expected: all pass, including Task 1's
  event-failure pins.
- [ ] **Step 5: Commit.** `refactor(orchestrators): shared EventSink and OnEvent/OnProgress types`

### Task 3: Show-provisioning primitives (R3)

**Files:**
- Create: `src/jidou/orchestrators/_show_provisioning.py`, `tests/test_orchestrators/test_show_provisioning.py`
- Modify: `src/jidou/orchestrators/show_creation_orchestrator.py` (created by services plan Task 10), `manual_match_orchestrator.py`, `path_import_orchestrator.py`

**Interfaces:**
- Produces:
  ```python
  async def insert_show_or_existing(
      session: AsyncSession,
      show: Show,
      *,
      refind: Callable[[], Awaitable[Show | None]],
  ) -> tuple[Show | None, bool]:
      """add + flush; on IntegrityError: rollback, return (await refind(), False). (show, True) on success."""


  async def sync_episodes_best_effort(
      session: AsyncSession,
      tmdb: TMDBService,
      show: Show,
      *,
      reraise_db_errors: bool,
      rollback_on_failure: bool,
  ) -> Exception | None:
      """TMDBOrchestrator(session, tmdb).sync_show_episodes(show); returns the swallowed error, if any."""


  async def generate_aliases_best_effort(
      session: AsyncSession,
      tmdb: TMDBService,
      llm: LLMService | None,
      show: Show,
      *,
      reraise_db_errors: bool,
      rollback_on_failure: bool,
  ) -> Exception | None:
      """generate_aliases(show, tmdb, llm=llm) then session.flush(); returns the swallowed error, if any."""
  ```
  - `reraise_db_errors=True` re-raises `SQLAlchemyError` before the
    generic handler runs.
  - `rollback_on_failure=True` awaits `session.rollback()` on a
    swallowed error.
  - None of these functions log. Callers keep their own log, `on_event`
    and HTTP text.

- [ ] **Step 1: Write the tests.**
  - `test_insert_show_or_existing_returns_created_on_success`.
  - `test_insert_show_or_existing_uses_supplied_refind`: `flush` raises
    `IntegrityError`; assert `rollback` was awaited, `refind` was
    awaited, and the result is `(refound, False)`.
  - For each helper, a 2×2 parametrized test over `(reraise_db_errors,
    rollback_on_failure)` with a `SQLAlchemyError` and with a
    `RuntimeError`. Assert what is raised or returned, and whether
    `rollback` was awaited.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it, then convert the three callers.** The
  flags reproduce each caller's current behavior (spec §6 item 2):

  | Caller | `refind` | episode sync flags | alias flags |
  |---|---|---|---|
  | `get_or_create_show_from_tmdb` | by `tmdb_id`, then `ensure_episode_group_map` | `reraise_db_errors=True, rollback_on_failure=False` | `False, False` |
  | `manual_match._resolve_show_by_tmdb_id` | by `tmdb_id` (raise if `None`, as today), then fill `local_path`/`content_type` and flush | `True, False` | `True, False` |
  | `path_import._tmdb_create_show` | `_db_find_show(title)` | `False, True` (episodes always synced: TV only) | `False, True` |

  `manual_match` also gets
  `_fill_missing_show_fields(show, payload) -> None` for the "set
  `local_path`/`content_type` if missing" block, which appears twice.
  Keep every log line and `_emit` call at its current position relative
  to the primitive calls.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_orchestrators/test_show_provisioning.py tests/test_show_creation.py tests/test_orchestrators/test_manual_match_orchestrator.py tests/test_path_import.py tests/test_files_routes.py tests/test_shows_routes.py tests/test_feed_onboarding_orchestrator.py -q`.
  Expected: all pass. `_resolve_show_by_tmdb_id` must be ≤ 8 and
  `_tmdb_create_show` ≤ 10. Task 12 brings the latter to ≤ 8.
- [ ] **Step 5: Commit.** `refactor(orchestrators): shared show-provisioning primitives`

### Task 4: Scan/seed discovery (R4, R5, R6)

**Files:**
- Create: `src/jidou/orchestrators/_remote_inventory.py`, `tests/test_orchestrators/test_remote_inventory.py`
- Modify: `_bulk_existence.py`, `scan_orchestrator.py`, `seed_orchestrator.py`, `tests/test_bulk_existence.py` (append)

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class RootListing:
      files: list[RemoteFile]
      dirs: list[RemoteFile]
      failed_roots: int

  @dataclass(frozen=True)
  class WalkOutcome:
      walked: list[tuple[str, RecursiveListResult]]
      failures: list[tuple[str, BaseException]]

  async def list_roots(
      sftp: SFTPService, remote_paths: Sequence[str], *,
      before_each: Callable[[int, int, str], Awaitable[None]] | None = None,
      on_error: Callable[[str, Exception], Awaitable[None]] | None = None,
  ) -> RootListing
  async def walk_directories(sftp: SFTPService, dir_paths: list[str]) -> WalkOutcome  # empty input → no SFTP call

  # _bulk_existence.py
  async def chunked_existing_statuses(session: AsyncSession, paths: list[str], chunk_size: int = EXISTENCE_CHUNK) -> dict[str, str]
  ```
  - `list_roots` awaits `before_each(idx, total, root)` before each
    listing. On an exception it calls
    `logger.exception("Failed to list remote path %s; skipping", root)`
    (today's text in both orchestrators), then
    `await on_error(root, exc)`, then continues.
  - Scan passes
    `before_each=lambda i, t, p: on_progress(i, t, f"Scanning {p}")`
    when `on_progress` is set, and an `on_error` that emits today's
    error event. Events stay in order because the callback runs inline.
  - Seed passes a `before_each` that logs
    `"Listing remote path %d/%d: %s"`.
  - `walk_directories` returns
    `WalkOutcome(walked=[], failures=[])` for an empty list, with no SFTP
    call, matching today's `if new_dirs:` / `if all_top_level_dirs:`
    guards.
  - In `chunked_existing_statuses`, the values are
    `str(row.status)`, which is today's seed behavior.
- Produces, as private methods:
  - `ScanOrchestrator._record_new_files(files, existing, dry_run, sink) -> tuple[int, int]`
    returns `(created, skipped)`.
  - `ScanOrchestrator._mark_walked_directories(walked, dry_run, sink) -> int`.
  - `SeedOrchestrator._insert_seeded_batches(...)` and
    `_mark_directories(...)`.

- [ ] **Step 1: Write the tests.**
  - `test_list_roots_splits_files_and_dirs_and_counts_failures`.
  - `test_list_roots_calls_before_each_before_listing` (record call
    order).
  - `test_walk_directories_empty_makes_no_sftp_call`.
  - `test_chunked_existing_statuses_chunks` (`chunk_size=2`, 5 paths,
    `execute` awaited 3 times).
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it, and rewrite both `run()` methods** as
  short sequences of these calls. Keep scan's "directories already
  known are filtered *before* walking" step and seed's "walk every
  directory" step. Keep seed's guarantee that directories are marked
  only after the files are committed, and its comment.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_orchestrators/test_scan_orchestrator.py tests/test_orchestrators/test_scan_seed_integration.py tests/test_seed_orchestrator.py tests/test_bulk_existence.py tests/test_orchestrators/test_remote_inventory.py -q`.
  Expected: all pass. Both `run()` methods must be ≤ 8.
- [ ] **Step 5: Commit.** `refactor(orchestrators): share SFTP discovery between scan and seed`

### Task 5: Route as a per-item command (R12, R13, D1)

**Files:**
- Modify: `src/jidou/orchestrators/route_orchestrator.py`
- Test: `tests/test_orchestrators/test_route_orchestrator.py` (append)

**Interfaces:**
- Produces (private):
  ```python
  class RouteOutcome(Enum):
      ROUTED = auto(); FAILED = auto(); SKIPPED_NO_COMMIT = auto()  # dry-run counts as ROUTED
  async def _route_one(self, file: DownloadedFile, show: Show, *, dry_run: bool, sink: EventSink) -> RouteOutcome
  async def _effective_season(self, file: DownloadedFile, *, is_movie: bool) -> int | None   # uses session.get(Episode, id)
  def _unique_destination(dest: Path, current_local_path: str | None) -> Path               # module-level, pure
  async def _mark_routed(self, file: DownloadedFile, dest: Path, show_id: int) -> None      # local_path, status, error_message, tracking
  ```
  `run` becomes: select the rows, then for each row
  `await on_progress(...)`, `outcome = await self._route_one(...)`,
  `counts[outcome] += 1`. Then the final log line and the result. The
  per-file `flush()`/`commit()` placement stays where it is today (inside
  `_route_one`).
  - The "no `local_path` configured" branch: in a real run it commits
    `ERROR` and returns `FAILED`; in a dry run it returns
    `SKIPPED_NO_COMMIT` and counts nowhere. This matches today: a dry
    run neither increments `files_failed` nor commits.
  - `_route_one` must still `continue`-equivalent (return early) without
    the final flush/commit in the two branches that skip it today: the
    dry-run return, and the retry branch, which commits itself.

- [ ] **Step 1: Write the pure-function test.** `test_unique_destination_appends_counter`:
  with `a.mkv` and `a.1.mkv` existing in `tmp_path`, the result is
  `a.2.mkv`. With `current_local_path == str(dest)`, `dest` is returned
  unchanged.
- [ ] **Step 2: Write `test_route_one_retry_size_mismatch_is_failure`.**
  Reuse the setup of the existing retry test and give the destination a
  different size. Assert the outcome is `FAILED`, `file.status ==
  ERROR`, and `file.local_path` is the original staging path.
- [ ] **Step 3: Run.** Expected: both fail with AttributeError.
- [ ] **Step 4: Implement.** Delete the always-true `if not dry_run:`
  (D1). Replace both `select(Episode).where(Episode.id == …)` queries
  with `await self.session.get(Episode, file.episode_id)`. In
  `_update_episode_tracking`, keep the `populate_existing` semantics the
  same: `get` returns the identity-map instance, just as the `select`
  did. Confirm with the existing tracking tests.
- [ ] **Step 5: Verify.** `uv run pytest tests/test_orchestrators/test_route_orchestrator.py tests/test_orchestrators/test_sync_orchestrator.py tests/test_orchestrators/test_event_failure_semantics.py -q`.
  Expected: all pass, with `run` ≤ 6 and `_route_one` ≤ 10.
- [ ] **Step 6: Commit.** `refactor(orchestrators): route one file per command; dedupe mark-routed`

### Task 6: Parse as a per-item command (D2)

**Files:**
- Modify: `src/jidou/orchestrators/parse_orchestrator.py`
- Test: `tests/test_orchestrators/test_match_orchestrator.py` (append)

**Interfaces:**
- Produces (private):
  ```python
  class ParseOutcome(Enum):
      MATCHED = auto(); UNMATCHED = auto(); FAILED = auto()
  async def _parse_one(self, file: DownloadedFile, *, dry_run: bool, llm_active: bool, sink: EventSink) -> ParseOutcome
  async def _preview_one(self, file: DownloadedFile, parsed: FilenameParseResult, season: int | None, episode: int | None, *, apply_gate: bool, sink: EventSink) -> ParseOutcome   # dry-run branch
  async def _apply_match(self, file: DownloadedFile, show: Show, season: int | None, episode: int | None, *, show_name: str | None, content_type: str | None, llm_active: bool, sink: EventSink) -> None
  def _ensure_show_local_path(self, show: Show) -> None   # can_auto_path rule + debug/warning logs, unchanged
  ```
  `_parse_one` owns the `try/except` that turns an exception into
  `ERROR` and the failure event. `run` tallies the outcomes and does the
  final commit, log line and result.

- [ ] **Step 1: Write `test_matched_by_uses_run_level_llm_availability`.**
  Use an LLM mock whose `is_available` returns `True`. Assert it is
  called exactly once per `run()`, not once per file, and that every
  matched file has `matched_by == MatchedBy.LLM` (D2).
- [ ] **Step 2: Run.** Expected: fails (it is called 1 + N times today).
- [ ] **Step 3: Implement it.** The dry-run branch moves verbatim into
  `_preview_one`. The confidence-gate branch stays in `_parse_one`. The
  match branch becomes `_apply_match` (alias-add guard, content-type
  backfill, `_ensure_show_local_path`, events).
- [ ] **Step 4: Verify.** `uv run pytest tests/test_orchestrators/test_match_orchestrator.py tests/test_orchestrators/test_sync_orchestrator.py tests/test_orchestrators/test_event_failure_semantics.py -q`.
  Expected: all pass, with `run` ≤ 6 and `_parse_one` ≤ 10.
- [ ] **Step 5: Commit.** `refactor(orchestrators): parse one file per command; compute LLM availability once`

### Task 7: Download decomposition (R11)

**Files:**
- Modify: `src/jidou/orchestrators/download_orchestrator.py`
- Test: `tests/test_orchestrators/test_download_orchestrator.py` (append)

**Interfaces:**
- Produces (private methods on `DownloadOrchestrator`):
  ```python
  async def _dry_run_preview(self, base_where: ColumnElement[bool], on_progress: OnProgress | None, sink: EventSink) -> DownloadResult
  async def _claim_batch(self, base_where: ColumnElement[bool], max_workers: int, sink: EventSink) -> list[tuple[DownloadedFile, Path]]  # marks DOWNLOADING, flush, commit
  async def _record_transfer(self, file: DownloadedFile, local_path: Path, size: int, sink: EventSink, *, log_mismatch: bool) -> bool  # hash + verify + status + event; True on success
  async def _record_failure(self, file: DownloadedFile, error: BaseException, sink: EventSink) -> None
  async def _mark_interrupted(self, pending: list[tuple[DownloadedFile, Path]], sink: EventSink) -> int  # returns count newly failed
  async def _persist_best_effort(self) -> None  # flush+commit; on Exception log the existing "Could not persist interrupted statuses…" warning
  ```
  Running totals live in a small private dataclass `_Tally(downloaded:
  int = 0, failed: int = 0, bytes: int = 0)`, which is turned into a
  `DownloadResult` at the end. `log_mismatch=True` on the normal path
  only: today only the normal path writes
  `logger.error("%s: %s", mismatch, …)`.

- [ ] **Step 1: Write `test_record_transfer_is_shared_by_normal_and_cancel_paths`.**
  Patch `DownloadOrchestrator._record_transfer` with
  `wraps=`. Drive one normal batch and one cancelled batch (reuse the
  existing cancellation test's setup). Assert it was awaited once per
  successfully completed transfer in **both** paths.
- [ ] **Step 2: Run.** Expected: fails with AttributeError.
- [ ] **Step 3: Implement it.** The `gather_cleanup_done` flag and the
  two `except BaseException` blocks keep their structure. Only their
  bodies become calls to the helpers. Keep the comments about
  `SKIP LOCKED`, about releasing locks before transfer, and about
  emitting progress after the commit.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_orchestrators/test_download_orchestrator.py tests/test_orchestrators/test_sync_orchestrator.py tests/test_orchestrators/test_event_failure_semantics.py -q`.
  Expected: all pass, with `run` ≤ 10.
- [ ] **Step 5: Commit.** `refactor(orchestrators): decompose DownloadOrchestrator.run`

---

## Phase 2 — Medium

### Task 8: Sync phases and `link_file_to_episode` (R10, R16)

**Files:**
- Modify: `src/jidou/orchestrators/sync_orchestrator.py`, `tmdb_orchestrator.py` (`TMDBSyncResult.empty`), `parse_orchestrator.py`, `manual_match_orchestrator.py`, `src/jidou/services/episode_tracking.py`
- Test: `tests/test_episode_tracking.py`, `tests/test_orchestrators/test_sync_orchestrator.py` (append)

**Interfaces:**
- Produces:
  ```python
  # services/episode_tracking.py
  def link_file_to_episode(file: DownloadedFile, ep: Episode) -> None
      # file.episode_id = ep.id; if file.parsed_season is None and ep.season_number is not None:
      #     file.parsed_season = ep.season_number
  # tmdb_orchestrator.py
  @classmethod
  def empty(cls) -> "TMDBSyncResult"   # shows_synced=0, episodes_upserted=0, episodes_skipped=0
  # sync_orchestrator.py (private)
  async def _sync_tmdb_phase(self, show_id: int | None, dry_run: bool) -> tuple[TMDBSyncResult, TMDBOrchestrator | None]
  ```
  - Use `link_file_to_episode` in `sync._fill_missing_episodes`, in
    `parse` (when `ep is not None`), and in `manual_match._assign` (when
    `ep is not None`).
  - Each caller keeps its own extra steps:
    `dismiss_orphans_for_file` in parse and manual match;
    `mark_episode_tracked` in manual match.
  - `route._update_episode_tracking` does **not** backfill the season,
    so it does not use the helper.

- [ ] **Step 1: Write the tests.**
  - `test_link_file_to_episode_backfills_missing_season_only`: the
    season is filled when it is `None` and left alone when it is set.
  - `test_tmdb_sync_result_empty`.
  - `test_sync_tmdb_phase_missing_show_returns_empty_and_orchestrator`:
    pins spec §6 item 5 as it is today.
- [ ] **Step 2: Run.** Expected: fails (ImportError / AttributeError).
- [ ] **Step 3: Implement it.** `run` becomes `_sync_tmdb_phase`, the
  TMDB summary event, then four `phase → summary event` blocks. Leave
  them as explicit calls: spec §7 explains why there is no pipeline
  list. Each block uses
  `_dry_run_suffix(dry_run: bool, *, tmdb: bool = False) -> str`, which
  returns `" (skipped — dry run)"` for TMDB and `" (dry run)"` for the
  others, or `""` when not a dry run.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_orchestrators tests/test_episode_tracking.py -q`.
  Expected: all pass. `SyncOrchestrator.run` must be ≤ 8.
- [ ] **Step 5: Commit.** `refactor(orchestrators): sync TMDB phase helper, TMDBSyncResult.empty, link_file_to_episode`

### Task 9: Domain errors and an injected TMDB service (O1, O2, O3)

**Files:**
- Create: `src/jidou/orchestrators/errors.py`, `tests/test_orchestrators/test_errors.py`
- Modify: `manual_match_orchestrator.py`, `show_rematch_orchestrator.py`, `feed_onboarding_orchestrator.py`, `src/jidou/main.py`, the route modules that construct these orchestrators (find them with `grep -rn "ManualMatchOrchestrator(\|FeedOnboardingError" src/jidou/api`), and their tests (exception type only), `tests/test_orchestrators/test_architecture.py`

**Interfaces:**
- Produces:
  ```python
  class OrchestratorError(Exception):
      def __init__(self, detail: str) -> None: ...  # self.detail = detail


  class NotFoundError(OrchestratorError): ...  # → 404


  class InvalidRequestError(OrchestratorError): ...  # → 422


  class UpstreamError(OrchestratorError): ...  # → 502
  ```
  `main.py` defines
  `async def orchestrator_error_handler(request: Request, exc: OrchestratorError) -> JSONResponse`
  and registers it for `OrchestratorError`. It returns
  `JSONResponse({"detail": exc.detail}, status_code=_STATUS[type(exc)])`,
  with `_STATUS: dict[type[OrchestratorError], int] = {NotFoundError: 404, InvalidRequestError: 422, UpstreamError: 502}`.
  That is the same body shape `HTTPException` produces.
- Mapping. All `detail` strings stay byte-for-byte the same:

  | Site | Today | After |
  |---|---|---|
  | `manual_match` "Show has no local_path configured; …" | 422 | `InvalidRequestError` |
  | `manual_match._resolve_show_by_id` "Show not found" | 404 | `NotFoundError` |
  | `manual_match` "local_path is required when creating…" | 422 | `InvalidRequestError` |
  | `manual_match` `f"TMDB lookup failed: {exc}"` | 404 | `NotFoundError` |
  | `show_rematch` "Failed to fetch TMDB details" | 502 | `UpstreamError` |
  | `show_rematch` "TMDB episode sync failed; rematch aborted" | 502 | `UpstreamError` |
  | `FeedOnboardingError(404, "Show not found")` | 404 | `NotFoundError` |
  | `FeedOnboardingError(422, …)` ×2 | 422 | `InvalidRequestError` |

  `FeedOnboardingError` is deleted, and so is the route's
  `except FeedOnboardingError` → `HTTPException` re-raise.
- O3: `ManualMatchOrchestrator.__init__(self, session, llm, tmdb: TMDBService)`.
  The files route passes its injected `tmdb`, from `get_tmdb`. Both
  `TMDBService()` constructions are deleted.

- [ ] **Step 1: Write `test_errors.py`.** For each subclass, mount a
  minimal FastAPI app with the production handler (import the handler
  function from `main.py`), have a route raise the exception, and
  assert the status code and `response.json() == {"detail": "x"}`.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it.** Update the orchestrator unit tests that
  use `pytest.raises(HTTPException)` to the new class; their `.detail`
  assertions do not change. Do **not** change the route-level tests in
  `test_files_routes.py`, `test_shows_routes.py` or
  `test_rss_feed_add_show_route.py`. They prove the status codes and
  bodies are the same. Empty `_KNOWN_FASTAPI_IMPORTERS`.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_orchestrators tests/test_files_routes.py tests/test_shows_routes.py tests/test_rss_feed_add_show_route.py tests/test_feed_onboarding_orchestrator.py tests/test_api_contract.py -q`.
  `test_api_contract.py` exists once API plan PR 1 has merged.
  Expected: all pass, and the OpenAPI snapshot is unchanged.
- [ ] **Step 5: Commit.** `refactor: domain errors for orchestrators, one HTTP mapping; inject TMDB into manual match`

### Task 10: TMDB episode upsert (R7, R8, R9)

**Files:**
- Modify: `src/jidou/orchestrators/tmdb_orchestrator.py`, `path_import_orchestrator.py`, `src/jidou/services/episode_lookup.py`
- Test: `tests/test_orchestrators/test_tmdb_orchestrator.py`, `tests/test_episode_lookup.py` (append)

**Interfaces:**
- Produces:
  ```python
  # tmdb_orchestrator.py (private)
  _EPISODE_DETAIL_FIELDS: Final = ("overview", "runtime", "episode_type", "still_path")
  def _new_episode(show_id: int, data: dict[str, Any], season: int, number: int, *, with_absolute: bool) -> Episode
  def _refresh_episode(ep: Episode, data: dict[str, Any], *, renumber: tuple[int, int] | None, with_absolute: bool) -> None
  async def _episodes_by_tmdb_id(self, tmdb_ids: list[int]) -> dict[int, Episode]   # one IN() query
  # services/episode_lookup.py
  async def count_show_episodes(session: AsyncSession, show_id: int) -> int
  ```
  - `name`, `air_date` and the `name` fallback (`ep_data.get("name",
    existing.name)` on update, `""` on create) are handled explicitly
    in the two helpers, as today.
  - `renumber` is set only on the episode-group path, which also
    rewrites `season_number` and `episode_number`.
  - `with_absolute` is `True` on both episode-group paths.
  - Each upsert loop calls `_episodes_by_tmdb_id` **once per season /
    group batch**. It inserts every newly created `Episode` into the
    returned dict, so a repeated id in the same batch updates the row
    just created, as autoflush does today (Review Focus 4).
  - `count_show_episodes` returns `0` where the scalar is `None`.

- [ ] **Step 1: Write the tests.**
  - `test_duplicate_tmdb_id_in_batch_updates_single_row`: one season
    payload lists `tmdb_id=7` twice. Assert one `Episode` is added,
    `episodes_upserted == 1` and `episodes_skipped == 1`.
  - `test_upsert_issues_one_lookup_query_per_season`: count
    `session.execute` calls for a 2-season show with 3 episodes each.
    Expect 2 lookups.
  - `test_count_show_episodes_none_is_zero`.
- [ ] **Step 2: Run.** Expected: fails (counts differ / ImportError).
- [ ] **Step 3: Implement it.** Replace the 4 count queries
  (`tmdb_orch` ×2, `path_import` ×2) with `count_show_episodes`.
  `apply_episode_group` uses `_new_episode` only, since it deletes all
  episodes first.
- [ ] **Step 4: Verify.** `uv run pytest tests/test_orchestrators/test_tmdb_orchestrator.py tests/test_orchestrators/test_show_rematch_orchestrator.py tests/test_path_import.py tests/test_episode_lookup.py tests/test_calendar_sync_missing_route.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** `perf(orchestrators): batch episode lookups in TMDB upserts; share field mapping`

### Task 11: RSS import and publish (R14, R15)

**Files:**
- Modify: `src/jidou/orchestrators/rss_import_orchestrator.py`, `rss_publish_orchestrator.py`
- Test: `tests/test_rss_import_orchestrator.py`, `tests/test_rss_publish_orchestrator.py` (append)

**Interfaces:**
- Produces (private), in `rss_import`:
  ```python
  @dataclass
  class _LinkIndex:
      show_by_lower_title: dict[str, int]
      stubs_by_show_id: dict[int, RssSubscription]
      stubs_by_lower_name: dict[str, RssSubscription]

  async def _warn_unresolved_feed(self, remote_key: str | None, name: str, sub: dict[str, object], feed_key_to_id: dict[str, int], *, on_update: bool) -> None
  async def _promote_stub(self, stub: RssSubscription, sub_dict: dict[str, object], index: _LinkIndex, feed_key_to_id: dict[str, int], result: RssImportResult) -> None
  async def _create_subscription(self, sub_dict: dict[str, object], index: _LinkIndex, feed_key_to_id: dict[str, int], result: RssImportResult) -> None
  async def _apply_update(self, db_row: RssSubscription, merged: dict[str, object], index: _LinkIndex, feed_key_to_id: dict[str, int], result: RssImportResult) -> None
  ```
  `on_update=True` selects the "could not resolve feed on update — "
  wording. Every warning string stays byte-for-byte the same.
- Produces (private), in `rss_publish`:
  ```python
  @asynccontextmanager
  async def _deluge_paused(self, result: RssPublishResult) -> AsyncIterator[bool]
  ```
  - It yields `False` if stopping failed and `run` should return early.
    This replaces the `return result` inside today's `try`.
  - It runs the restart sequence in its `finally`, exactly as today:
    the delay, the event, the command, and appending the error.
  - The dry-run branches stay inside it.
  - `run` is then: reconcile → re-parse → `async with
    self._deluge_paused(result) as ok:` → if `ok`, `_backup` and
    `_publish`.

- [ ] **Step 1: Write `test_publish_restarts_deluge_when_backup_upload_raises`.**
  `upload_bytes` raises on the backup call. Assert the restart command
  still ran and the exception propagated. This pins today's
  `try`/`finally` behavior through the refactor.
- [ ] **Step 2: Run.** Expected: passes today. It guards the refactor.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Verify.** `uv run pytest tests/test_rss_import_orchestrator.py tests/test_rss_publish_orchestrator.py tests/test_rss_tasks.py tests/test_rss_routes.py -q`.
  Expected: all pass. `_upsert_subscriptions` must be ≤ 8 and
  `RssPublishOrchestrator.run` ≤ 8.
- [ ] **Step 5: Commit.** `refactor(orchestrators): split RSS subscription upsert; Deluge pause as a context manager`

### Task 12: Path import decomposition

**Files:**
- Modify: `src/jidou/orchestrators/path_import_orchestrator.py`
- Test: `tests/test_path_import.py` (append)

**Interfaces:**
- Produces (private):
  ```python
  class _EntryOutcome(Enum):
      TRACKED = auto(); ALREADY_TRACKED_HERE = auto(); TRACKED_PREVIOUSLY = auto(); UNMATCHED = auto()
  async def _unresolved_result(self, label: str, action: str, entries: list[ParsedPathEntry]) -> ShowImportResult
  async def _ensure_local_path(self, show: Show, *, set_local_path: bool, has_entries: bool) -> None
  async def _track_entry(self, show: Show, label: str, entry: ParsedPathEntry, claimed: set[int]) -> _EntryOutcome
  async def _emit_summary(self, show: Show, result: ShowImportResult) -> None
  def _pick_tmdb_candidate(show_dir: str, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]  # module-level; (best, exact)
  ```
  - `TRACKED_PREVIOUSLY` covers "the episode was already
    `file_tracked`": it counts nowhere, but the flag is still set, as
    today.
  - `_process_show_entries` tallies the outcomes into the existing
    `ShowImportResult` counters and path lists.
  - `_tmdb_create_show` uses `_pick_tmdb_candidate`, then
    `llm_pick_candidate` when there is no exact match, then Task 3's
    primitives.
  - The filename-extraction lines use `basename_any` (services plan
    Task 12).

- [ ] **Step 1: Write `test_pick_tmdb_candidate_prefers_normalized_exact`.**
  Candidates are `["Daredevil: Born Again", "Daredevil"]` and
  `show_dir` is `"Daredevil"`. Assert the result is `("Daredevil", True)`.
  When nothing matches exactly, assert it is `(first, False)`.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Verify.** `uv run pytest tests/test_path_import.py tests/test_api_import_routes.py tests/test_db_import_tasks.py -q`.
  Expected: all pass. `_process_show_entries` must be ≤ 10 and
  `_tmdb_create_show` ≤ 8.
- [ ] **Step 5: Commit.** `refactor(orchestrators): decompose path-import show processing`

---

## Phase 3 — Low and closeout

### Task 13: Remove the intra-layer lazy imports (D3)

**Files:**
- Modify: `manual_match_orchestrator.py`, `path_import_orchestrator.py`, `show_rematch_orchestrator.py`, and the tests that patch the source module of an import that becomes top-level

**Interfaces:**
- No new names.

- [ ] **Step 1: Move the imports to the top of each module.** Run
  `uv run python -c "import jidou.main"` to prove there is no import
  cycle.
- [ ] **Step 2: Retarget the patches.** Run `uv run pytest -q`. Every
  failure here is a `patch("jidou.orchestrators.alias_orchestrator.generate_aliases")`
  or `patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator")`
  that used to reach the code because of the lazy import. Retarget each
  one to the *importing* module, for example
  `jidou.orchestrators.show_rematch_orchestrator.generate_aliases`.
  At `62cb347` there were 31 such patch sites across 5 test files.
  Retarget only the ones that fail. Assertions do not change.
- [ ] **Step 3: Verify.** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 4: Commit.** `refactor(orchestrators): top-level imports now that no cycle exists`

### Task 14: Shared fuzzy matcher and alias schema (R17, R18)

**Files:**
- Create: `src/jidou/services/fuzzy_match.py`, `tests/test_fuzzy_match.py`
- Modify: `src/jidou/orchestrators/rss_import_orchestrator.py` (`_fuzzy_show_id`), `src/jidou/services/rss_stub.py` (`pick_unlinked_subscription`, from services Task 12), `src/jidou/orchestrators/alias_orchestrator.py`

**Interfaces:**
- Produces:
  ```python
  FUZZY_THRESHOLD: Final = 85
  def unambiguous_best_match(query: str, candidates: Sequence[str], *, threshold: int = FUZZY_THRESHOLD) -> int | None
      # index of the single best token_set_ratio(query.lower(), c.lower()) >= threshold; None if none or tied
  ```
  - Callers keep their own exact-match step (spec §6 item 6) and call
    this only for the fuzzy step.
  - `alias_orchestrator._ALIAS_RESPONSE_FORMAT` becomes
    `json_schema_format("show_aliases", {"aliases": {"type": "array", "items": {"type": "string"}}})`.
    The bare-list fallback in `_llm_aliases` stays.

- [ ] **Step 1: Write the tests.**
  - `test_unambiguous_best_match`: a clear winner → its index; two
    candidates tied at the top → `None`; everything below 85 → `None`.
  - `test_alias_schema_unchanged`: equality against a literal copy of
    today's `_ALIAS_RESPONSE_FORMAT`, pasted before Step 3.
- [ ] **Step 2: Run.** Expected: fails with ImportError.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Verify.** `uv run pytest tests/test_fuzzy_match.py tests/test_rss_import_orchestrator.py tests/test_rss_stub_service.py tests/test_alias_orchestrator.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.** `refactor: one unambiguous fuzzy matcher; alias schema via json_schema_format`

### Task 15: Final ratchet, docs and graph

**Files:**
- Modify: `tests/test_orchestrators/test_architecture.py`, `docs/architecture.md` (only if it names moved symbols)

- [ ] **Step 1: Set `_ORCH_MAX_COMPLEXITY = 10`.** If ruff reports
  anything above 10, finish that function's task. Do not raise the
  limit.
- [ ] **Step 2: Check the docs.**
  `grep -rn "FeedOnboardingError\|_default_on_event\|HTTPException" docs/*.md`
  and fix any stale references.
- [ ] **Step 3: Run the full pre-push sequence** from Global Constraints.
  Expected: everything clean.
- [ ] **Step 4: Run `graphify update .`** and commit the result.
- [ ] **Step 5: Commit.** `chore(orchestrators): final complexity ratchet (10) and docs refresh`

---

## Deferred to the merged app-wide plan

- Spec §6 decisions: event-failure policy, race-recovery lookup key,
  name-agreement rules, `local_path` auto-population, and logging when
  `sync` is given a missing `show_id`.
- O5: a neutral `jidou/prompts/` package for all LLM prompt files.
- A pipeline-stage protocol for `SyncOrchestrator`, if the per-phase
  summaries are ever standardized.
- Route the services plan's deferred L3 (`RegexSuggestionError`) through
  Task 9's `OrchestratorError` handler.
