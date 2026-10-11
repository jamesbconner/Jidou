# API Layer Simplification — Analysis (Spec)

**Date:** 2026-10-11
**Scope:** `src/jidou/api/` only (18 modules, 6,453 lines, 103 endpoints).
**Status:** Analysis complete. The companion plan is
`docs/superpowers/plans/2026-10-11-api-simplification.md`. The same analysis
is still to be done for `services/`, `orchestrators/`, `workers/`,
`models/`, `schemas/` and `frontend/`, and the plans will be merged after
that.

---

## 1. Summary

The API is a modular monolith with clean edges and a bloated middle.
`routes/shows.py` (2,387 lines, 35 endpoints) and `routes/rss.py` (1,167
lines, 23 endpoints) hold 55% of the code. They also contain most of the
database queries written directly in route handlers and most of the
copy-pasted code. Cyclomatic complexity is low except in 7 functions. True
dead code is rare: every private helper has 2 or more references, and
`vulture` flagged only decorator-registered route handlers, which are false
positives.

## 2. Structural map of current dependencies

```
main.py ──(Depends(verify_api_key) on all routers except health/images/ws)
  ├─ health.py ─────────────► config, database.engine, redis.asyncio   ← Docker HEALTHCHECK (/api/health)
  ├─ websocket/task_progress
  └─ routes/
      ├─ shows.py ──► 6 models · 7 schemas · 17 services · 3 orchestrators
      │    └─ owns module-global `_tmdb = TMDBService()` + `get_tmdb()`
      ├─ rss.py ────► ★ api.routes.shows.get_tmdb ★ · 3 models · 10 services · 2 orchestrators · workers
      ├─ files.py ──► 2 models · 5 services · manual_match_orchestrator
      ├─ orphans.py ► 4 models · episode_tracking
      ├─ watchlist.py ► 3 models · rss_stub
      ├─ admin.py ──► 5 models · cache · workers.celery_app (18 raw select() calls)
      ├─ tasks.py ──► 7 worker modules, lazy-imported inside the handler
      ├─ import_routes.py ► 2 worker modules · progress
      ├─ dashboard / export / settings / config / images ► thin
      └─ dependencies.py ► LLMService (app.state), FeedFetchService (module global), verify_api_key
```

Router prefixes: `/shows`, `/rss`, `/files`, `/orphans`, `/watchlist`,
`/admin`, `/config`, `/settings`, `/dashboard`, `/import`, `/export`,
`/images`. `tasks` has no prefix. Everything is mounted under `/api` in
`main.py`.

### Places that break the boundary rules in `.claude/CLAUDE.md`

- **Route-to-route coupling.** `rss.py:14` imports `get_tmdb` from
  `routes/shows.py`.
- **Three different service-lifetime patterns.** `_tmdb` is a module global
  in a route file, `_feed_fetch_service` is a module global in
  `dependencies.py`, and `LLMService` lives on `app.state`.
- **Database access in handlers.** Raw `select()` counts: `shows.py` 65,
  `rss.py` 19, `admin.py` 18, `files.py` 11, `watchlist.py` 9,
  `orphans.py` 7.
- **Domain rules in handlers.** Rules such as "episode must belong to the
  file's show" and "episode already tracked" are enforced in route
  handlers instead of services.

## 3. Redundant or repetitive code

| # | Pattern | Where | Target |
|---|---|---|---|
| R1 | Show lookup-or-404 (`select(Show).where(Show.id == …)` → `scalar_one_or_none()` → `raise 404 "Show not found"`) | 28 sites: `shows.py` ×25, `rss.py` ×2 (body `payload.show_id`), `orphans.py` ×1, `watchlist.py` ×1 (body). One `shows.py` site (`link_movie_file`) adds `.with_for_update()` | `api/lookups.py: get_or_404`, `get_show_or_404` |
| R2 | Other entity lookup-or-404 | `_get_feed_or_404` (rss), `_get_episode_or_404` (shows), inline `DownloadedFile` / subscription / orphan lookups | Same `get_or_404` |
| R3 | `_get_episode_or_404` and `_get_show_episodes_or_404` both repeat the show-exists check | `shows.py` | Build both on R1 |
| R4 | Task-dispatch boilerplate: `uuid4` → `_dispatch` closure → `enqueue_task` → `TaskDispatchError` → 503 | `tasks.py`, `import_routes.py` ×2, `rss.py` ×2 | `services/task_dispatch.py` |
| R5 | Two health checks with different response shapes and different Redis rules | `health.py` (`/api/health`, the Docker probe; Redis required) and `admin.py:system_health` (`/api/admin/health`, used by the frontend `useAdmin.ts`; Redis optional when `REDIS_URL=""`) | `services/health_probes.py` (shared probe runner). Both response shapes stay as they are |
| R6 | `if field in model_fields_set` ladders | `settings.py:update_settings` (10 identical blocks), `files.py:patch_file` | Table-driven map (settings); `services/file_relink.py` (files) |
| R8 | Local-file scan flow duplicated | `shows.py` `scan-local-files` and `scan-local-movie-file` | **Deferred** to the app-wide plan |
| R9 | Link file ↔ episode invariants spread across files | `files.py:patch_file`, `orphans.py` ×2, `shows.py` ×4 | This plan: `patch_file` only. Other sites have swap/restore semantics and are **deferred** |

**Corrections to the first pass of this analysis:**

- **R7 is dropped.** I had proposed one IntegrityError-mapping helper, but
  `watchlist.py`'s `except IntegrityError` is race recovery (re-select the
  existing row), not pgcode → HTTP mapping. Only one real mapping site
  exists, so it becomes a local helper in `files.py`.
- **The admin Redis "not configured" branch is not dead.** It runs when
  `REDIS_URL` is explicitly set to `""`, and it is covered by
  `test_health_redis_not_configured_does_not_make_unhealthy`.

## 4. Complexity hotspots

Measured with ruff `C901` (threshold 8) and the `PLR0912`/`PLR0915`
branch and statement checks.

| Function | Complexity | Replacement pattern | In this plan? |
|---|---|---|---|
| `files.py` `patch_file` | 16 | Service extraction (`file_relink`) + domain exceptions | Yes |
| `shows.py` `discover_shows` | 14 | Pipeline: seed stage, then trending-fill stage, in `services/discover_feed.py` | Yes |
| `tasks.py` `trigger_task` | 13 | Registry / dispatch table | Yes |
| `shows.py` `get_similar_shows` | 11 | Pure merge/rank function in a service | Deferred |
| `settings.py` `update_settings` | 11 | Table-driven field → key map | Yes |
| `admin.py` `system_health` | 10 (55 statements) | Probe runner (Template Method) | Yes |
| `shows.py` `link_movie_file` | 10 | Covered by deferred R9 | Deferred |

## 5. Divergences worth a decision (not changed by this plan)

- `/api/health` treats Redis as required (returns 503), while
  `/api/admin/health` treats it as optional. The plan keeps both rules
  unchanged and only shares the probe mechanics.
- In `patch_file`, changing `show_id` without `episode_id` nulls
  `episode_id` but never calls `clear_if_unreferenced` on the old episode.
  That can leave stale `file_tracked` state on an episode of the old show.
  The plan keeps this behavior exactly (Review Focus #4), and it should be
  fixed or decided separately.
- `trigger_task` returns `"Failed to dispatch task to broker"` on 503,
  while the import and rss routes return `"Task broker unavailable"`. The
  plan keeps each string.

## 6. Priorities

- **High:** DI consolidation (move `get_tmdb`), lookup helpers (R1–R3),
  `file_relink` (R6/R9 for `patch_file`), task dispatch (R4).
- **Medium:** split `shows.py` / `rss.py` by sub-resource, health probes
  (R5), discover feed service.
- **Low:** table-driven settings.
- **Deferred to the app-wide plan:** R8, the rest of R9,
  `get_similar_shows`, a `StatsQueryService` for the queries in `admin.py`
  and `dashboard.py`.
