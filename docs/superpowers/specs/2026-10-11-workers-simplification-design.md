# Workers Layer Simplification — Analysis (Spec)

**Date:** 2026-10-11
**Scope:** `src/jidou/workers/` only: 15 modules plus `__init__.py`,
2,154 lines in total.
**Status:** Analysis complete. The companion plan is
`docs/superpowers/plans/2026-10-11-workers-simplification.md`. This is
the fourth per-layer analysis, after the API, services and orchestrators
specs of the same date. Still to be analyzed: `models/`, `schemas/` and
`frontend/`.

Measured at commit `2e202f5`. Complexity numbers come from ruff `C901`
with `max-complexity=8`, plus the PLR checks. Reachability was checked by
grepping `src/` for every `@shared_task` name.

---

## 1. Summary

The workers layer is small, and most of it is already factored well.
`_harness.run_task_workflow` owns the whole `BackgroundTask` lifecycle:
creating the row, refusing a redelivered message, RUNNING, progress and
event callbacks, COMPLETED, FAILED or CANCELLED, and WebSocket
broadcasts. Every orchestrator-backed task goes through it.

The leftover complexity is **wrapper boilerplate around the harness**.
Each of the 11 harnessed tasks is three nested layers: a Celery
function, an `async` implementation, and a `_work` closure. Each copy
repeats the same entrypoint, the same settings-to-`SFTPService` block,
and a hand-written result-to-summary dict.

There are three real hotspots: `_db_import` (16), its inner `_work` (15),
and `run_task_workflow` (9). There is one unreachable task,
`fetch_trending_shows_task`. It is registered with Celery but nothing
schedules or dispatches it, and if it ran it would upsert TMDB trending
titles into the user's library `shows` table.

## 2. Structural map of current dependencies

```
celery_app.py ── include=[13 modules] ── beat: scheduled_sync_task, scheduled_rss_import_task, purge_stale_images_task

API dispatch (api/routes/tasks.py, import_routes.py, rss.py)
   │  apply_async(task_id=…) after services.progress.enqueue_task pre-creates the row
   ▼
*_tasks.py  @shared_task(bind=True) ─► asyncio.run(_impl(self.request.id, …)) ─► except SoftTimeLimitExceeded: mark_task_timed_out
   │
   └─► _impl ─► run_task_workflow(task_id, type, _work, progress_total=0, dry_run, running_message)
                    └─► _work(session, on_progress, on_event) ─► <Orchestrator>(…).run(…) ─► WorkflowResult(summary)

scheduled_tasks ─► _try_claim_task (own engine) ─► lazy import sync_tasks / rss_tasks ─► apply_async
image_cache_tasks ─► Redis SET NX lock ─► services.image_cache
tasks.py (fetch_trending_shows_task) ─► TMDBService.get_trending ─► INSERT … ON CONFLICT into shows   ★ unreachable
```

Workers reach outward to `services.progress` (12 modules),
`services.sftp_service` (6), `services.tmdb` (4),
`services.llm_service` (3), and one orchestrator each.

Places that bypass the harness's abstraction:

- `import_tasks` and `db_import_tasks` call `update_task_status`
  directly, to set `progress_total` once the input has been parsed.
- `import_tasks` calls `append_task_event` directly.
- `db_import_tasks` calls `check_task_cancelled` directly, once per row.

All of these work. They are noted because they are why
`patch("jidou.workers.import_tasks.update_task_status")` appears in 5
tests.

## 3. Redundant or repetitive code

| # | Pattern | Where | Target |
|---|---|---|---|
| W1 | Entrypoint: `try: return asyncio.run(_impl(self.request.id, …)) except SoftTimeLimitExceeded: asyncio.run(mark_task_timed_out(self.request.id)); raise` | 11 tasks in 10 modules | `_harness.run_harnessed(celery_task_id, coro_factory)` |
| W2 | `SFTPService(host=settings.sftp_host or "", port=…, username=…, password=…, key_path=…, known_hosts=None, max_workers=…, max_retries=…, retry_delay=…)` | download, scan, seed, sync, and `rss_tasks._build_sftp` (5 copies) | `services/sftp_service.create_sftp_service(settings)`, mirroring `create_llm_service` |
| W3 | Building a summary dict from a result dataclass field by field (`{"files_routed": r.files_routed, …, "dry_run": dry_run}`) | route, match, download, scan, seed, backfill, import (including the nested `show_results`) | `_harness.summarize(result, *, dry_run)` = `{**asdict(result), "dry_run": dry_run}`. Each summary is exactly the result's fields plus `dry_run` (checked field by field). Sync and RSS keep their hand-picked subsets. |
| W4 | A fresh engine plus session factory per `asyncio.run` loop, then `dispose()` | `_harness`, `scheduled_tasks` ×2, `tasks.py`, `services/progress.mark_task_timed_out` | `jidou/database.task_sessionmaker()`, an async context manager |
| W5 | Copying 40 Show columns and 17 Episode columns by name, alongside `_SHOW_HANDLED_COLUMNS` / `_EPISODE_HANDLED_COLUMNS`, which already list them | `db_import_tasks._build_show`, `_update_show`, `_build_episode`, `_update_episode` | Copy driven by the column sets: `_copy_columns(target, row, columns, *, keep_existing)`, with per-column defaults and converters |
| W6 | Three restore loops (check cancellation, skip-and-warn, look up, create or update, count) | `db_import_tasks._work` | `_restore_shows`, `_restore_episodes`, `_restore_watchlist` → `_RestoreCounts` |
| W7 | `_scheduled_sync` / `_scheduled_rss_import`: create a uuid, claim, lazily import the task, dispatch | `scheduled_tasks` | `_run_scheduled(task_type, load_task, *, precondition)` |
| W8 | Task-status sets defined again: `_TERMINAL_STATUSES` (harness) and `_ACTIVE_STATUSES` (scheduled); the "is a task of this type active?" count query | `_harness`, `scheduled_tasks` (both are already in `services/progress`) | `progress.TERMINAL_STATUSES` (services plan Task 14), `progress.get_active_task` |
| W9 | Redis lock: `SET NX EX` → work → `DEL` → `aclose` | `image_cache_tasks` | `services/redis_conn.redis_try_lock(...)`, built on the services plan's `redis_session` |
| W10 | "Content type → library root" mapping for host paths | `import_tasks._host_root_for_content_type` (host), `services/path_resolution.resolve_show_local_path` (container) | `path_resolution.library_root(content_type, *, tv, anime, movie)`, used by both |
| W11 | `time_limit=25200, soft_time_limit=21600` written out twice, each with a long comment, while the `visibility_timeout` comment in `celery_app` depends on them | `sync_tasks`, `import_tasks` | `celery_app.LONG_TASK_LIMITS`, plus a test that `visibility_timeout` is greater than every task's `time_limit` |

## 4. Complexity hotspots

| Function | C901 | Replacement pattern | Target |
|---|---|---|---|
| `db_import_tasks._db_import` / `_work` | 16 / 15 | W5 + W6: a loop per section, with column copying driven by tables | ≤ 6 |
| `_harness.run_task_workflow` | 9 | Extract `_finish(session, task_id, result) -> str \| None` (the soft-failure vs COMPLETED branch) | ≤ 7 |

Final ratchet target for `src/jidou/workers`: **8**.

## 5. Dead or redundant paths

| ID | Item | Evidence | Action |
|---|---|---|---|
| D1 | `tasks.py` `fetch_trending_shows_task` / `_fetch_trending` | No reference in `src/` or `frontend/src` outside its own module. It is not in the beat schedule, not in the API's task dispatch, and not in import or RSS routes. Only `tests/test_workers.py` calls it. | Delete the module, its `include` entry and its tests. **If it is triggered by hand with `celery call`, keep it instead and say so in the PR.** |
| D2 | `logger = logging.getLogger(__name__)` that is never used | backfill, download, match, route, rss, scan, seed, sync task modules (8) | Remove |
| D3 | `progress_total=0` passed explicitly | 10 calls to `run_task_workflow` (the default is 0) | Remove the argument (sync keeps `5`) |
| D4 | `known_hosts=None` passed explicitly | 5 SFTP constructions | Gone with W2 |
| D5 | `from sqlalchemy import delete` inside a function body | `scheduled_tasks._delete_task_record` | Move it to the top-level imports |
| — | Lazy imports of `sync_tasks` / `rss_tasks` inside `scheduled_tasks` | They keep beat-only processes from importing orchestrators | **No action** |

## 6. Divergences worth a decision (not changed by this plan)

1. **The API's SFTP connectivity test** (`api/routes/config.py`) builds
   `SFTPService` differently from the workers. It sets `username or ""`
   and an explicit `remote_base_path`, and leaves out `max_workers`. W2
   covers the workers only.
2. **Restore update rules differ by column type.** An explicit `null`
   clears `file_tracked_at` / `watched_at`, but an explicit `null` (or a
   malformed value) for `air_date` leaves the existing date in place.
   `cached` and `tmdb_id` are never updated on an existing show, and a
   `null` `local_path` in a backup keeps the live value. W5 encodes
   these as explicit per-column rules and does not merge them.
3. **Overlap guards differ.** A scheduled dispatch that fails *deletes*
   its pending row, while API dispatch marks it FAILED. This is
   documented as deliberate in `_dispatch_scheduled`. The plan keeps it.
4. **Orchestrators that report their own progress total**
   (`import_tasks` and `db_import_tasks` call `update_task_status` with
   `progress_total=` directly). A harness-level
   `set_progress_total(total, message)` callback would remove this, but
   it would change the `WorkFn` signature for all 11 harnessed tasks. This is
   deferred.

## 7. Priorities

- **High:** W1 entrypoint, W4 task-scoped engine, W2/W3 factories and
  summaries, W5/W6 `db_import` decomposition.
- **Medium:** W7/W8 scheduled-task table using the shared status
  helpers, the harness hotspot, D1–D5.
- **Low:** W9 Redis lock helper, W10 library-root helper, W11 shared
  long-task limits plus the visibility-timeout invariant test.

## 8. Interaction with the other plans

- **Services plan Task 14** adds `progress.TERMINAL_STATUSES`; W8 uses
  it.
- **Services plan Task 9** adds `redis_conn.redis_session`; W9 builds on
  it.
- **Services plan, deferred item:** moving `enqueue_task` /
  `TaskDispatchError` / `get_active_task` out of `progress.py`. The
  workers plan moves `mark_task_timed_out`, whose only callers are
  workers, from `services/progress.py` into `workers/_harness.py`. The
  merged plan should do both moves together.
- **API plan Task 8** builds `TASK_REGISTRY` from the task names. D1
  removes a task that is not in that registry, so the two do not
  overlap.
- **Orchestrators plan Task 2** introduces `OnEvent` / `OnProgress` in
  `services/callbacks.py`. The harness's own `ProgressFn` / `EventFn`
  become aliases of those (plan Task 2).
