# Orchestrators Layer Simplification — Analysis (Spec)

**Date:** 2026-10-11
**Scope:** `src/jidou/orchestrators/` only: 16 modules plus
`__init__.py`, 6,322 lines in total.
**Status:** Analysis complete. The companion plan is
`docs/superpowers/plans/2026-10-11-orchestrators-simplification.md`. This is
the third per-layer analysis, after
`2026-10-11-api-simplification-design.md` and
`2026-10-11-services-simplification-design.md`. Still to be analyzed:
`workers/`, `models/`, `schemas/` and `frontend/`.

Measured at commit `62cb347`. Complexity numbers come from ruff `C901`
with `max-complexity=8`, plus `PLR0911`, `PLR0912` and `PLR0915`.
Dependency counts come from an AST import scan of `src/jidou/**`.

---

## 1. Summary

The orchestrator layer is where the application's complexity
concentrates. It has 17 functions above complexity 8, against 12 in
services and 7 in the API. Eleven of them score 14 or more. The worst are:

- `DownloadOrchestrator.run` (28)
- `SeedOrchestrator.run` (26)
- `RouteOrchestrator.run` (24)
- `RssImportOrchestrator._upsert_subscriptions` (24)
- `ParseOrchestrator.run` (22)
- `PathImportOrchestrator._process_show_entries` (21)
- `ScanOrchestrator.run` (20)

The causes fall into four groups:

1. **The per-item pipeline is copied by hand in every pipeline
   orchestrator.** Download, parse, route, scan, seed, backfill and path
   import all do the same thing: select candidate rows, loop with
   progress, and inside the loop do a `try`, a status transition,
   counters, an event, and a commit. Each copy carries its own
   dry-run branch, so "work out what would happen" and "do it" are
   interleaved line by line.
2. **"Create a show from TMDB" exists in three versions.**
   `services/show_creation` (which the services plan moves into
   `orchestrators/`), `ManualMatchOrchestrator._resolve_show_by_tmdb_id`,
   and `PathImportOrchestrator._tmdb_create_show`. All three insert the
   row while handling a lost race against a concurrent insert, then
   sync episodes best-effort, commit, and generate aliases best-effort.
   Each makes different choices about rollback and re-raising.
3. **Small mechanisms are copied verbatim:**
   - the "swallow event-logging errors" emitter closure (×4);
   - the `OnEvent` / `OnProgress` callback type spelled out inline in
     16 signatures;
   - the TMDB→`Episode` field copy (×5);
   - the "list the SFTP roots, then deep-walk the new directories"
     discovery code (scan and seed);
   - the "fuzzy match with ties treated as ambiguous" helper
     (`rss_import`, and `services/rss_stub`).
4. **Web-layer leakage.** Two orchestrators import FastAPI and raise
   `HTTPException`, and a third raises its own error carrying an HTTP
   status code.

There is little dead code. The analysis found one unreachable condition
and one redundant recomputation (§5).

## 2. Structural map of current dependencies

Inbound users are shown as `◄`. `★` marks a dependency that breaks a layer
boundary.

```
workers/*_tasks ──► sync ──► tmdb_orch, scan, download, parse, route   (fixed 5-phase pipeline)
                ──► seed, path_import, rss_import, rss_publish, backfill
api/routes      ──► manual_match ★fastapi, show_rematch ★fastapi, feed_onboarding (★HTTP codes),
                    rss_publish (compose_config only), tmdb_orch, alias_orch

composition inside the layer:
  sync ──► scan · download · parse · route · tmdb_orch
  rss_publish ──► rss_import   (also imports the private name `_default_on_event`)
  manual_match ──► tmdb_orch, alias_orch (lazy import)
  path_import  ──► tmdb_orch, alias_orch (lazy import)
  show_rematch ──► tmdb_orch (lazy import), alias_orch (lazy import)
  scan, seed   ──► _bulk_existence
  services.show_creation ──► tmdb_orch, alias_orch (lazy imports; services plan L2 moves it here)

shared by most orchestrators:
  services: episode_lookup, episode_tracking, tmdb, tmdb_mapping, llm_service, sftp_service
  models:   DownloadedFile (9 modules), Show (11), Episode (7)
```

`tmdb_orchestrator` is the layer's hub, with 6 internal and external
importers. `alias_orchestrator` has 5 importers.

None of the lazy imports inside this layer are needed. There is no import
cycle between orchestrators. The only cycle was `services.show_creation`
↔ orchestrators, and the services plan's Task 10 removes it.

### Layering violations

| ID | Violation | Where |
|---|---|---|
| O1 | Orchestrators import `fastapi.HTTPException` | `manual_match` (4 raises: 422, 404, 422, 404), `show_rematch` (2 raises, both 502) |
| O2 | A domain error carries an HTTP status code | `FeedOnboardingError(status_code, detail)` (404 or 422). `api/routes/rss.py` re-raises it as `HTTPException` |
| O3 | Services are constructed inside orchestrators instead of being injected | `ManualMatchOrchestrator` calls `TMDBService()` twice. Those instances bypass the shared, cached one the routes inject. |
| O4 | A module imports another module's private name | `rss_publish` imports `_default_on_event` from `rss_import` |
| O5 | A prompt file is read from another layer's folder | `alias_orchestrator` reads `services/prompts/alias_normalize.txt` |

## 3. Redundant or repetitive code

| # | Pattern | Where | Target |
|---|---|---|---|
| R1 | Event-emitter closure that swallows errors (`if on_event: try: await on_event(...) except: log`); `PathImportOrchestrator._emit` is a version that does **not** swallow | `download.run`, `parse.run`, `route.run`, `scan.run` (identical); `path_import._emit` | `orchestrators/_events.py: EventSink(callback, *, swallow_errors)` |
| R2 | The callback type `Callable[[str, str, dict \| None], Awaitable[None]]` and `Callable[[int, int, str], Awaitable[None]]` spelled out inline | 16 signatures across 9 orchestrators, plus `_OnEvent` ×2 (rss) and `OnEvent` ×2 (services) | `services/callbacks.py: OnEvent, OnProgress`. These go in services, the lowest layer that uses them. |
| R3 | Show provisioning from TMDB: insert with race recovery, sync episodes best-effort, commit, generate aliases best-effort | `show_creation_orchestrator` (after services Task 10), `manual_match._resolve_show_by_tmdb_id`, `path_import._tmdb_create_show` | `orchestrators/_show_provisioning.py`: `insert_show_or_existing`, `sync_episodes_best_effort`, `generate_aliases_best_effort`. These are primitives with explicit flags, not a single policy object, because the three callers really do differ (see §6). |
| R4 | SFTP discovery: shallow-list every root, then batch deep-walk the directories and split successes from failures | `scan.run` phases 1 and 4, `seed.run` phases 1 and 2 | `orchestrators/_remote_inventory.py: list_roots`, `walk_directories` |
| R5 | Chunked `IN()` existence query. Seed copies it because it also needs each row's status. | `_bulk_existence.chunked_existing_paths`; `seed.run` inline loop | `_bulk_existence.chunked_existing_statuses` |
| R6 | "Record a new file, or count it as skipped" loop | `scan.run`, twice (top-level files and files in walked directories) | `ScanOrchestrator._record_new_files` |
| R7 | Copying TMDB episode fields onto an `Episode` (create and update) | `tmdb_orch.sync_show_episodes` ×2, `_refresh_active_group_episodes` ×2, `apply_episode_group` ×1 | `_EPISODE_DETAIL_FIELDS`, `_new_episode(...)`, `_refresh_episode(...)` |
| R8 | One `SELECT … WHERE tmdb_id = ?` per episode (N+1) inside the upsert loops | `sync_show_episodes`, `_refresh_active_group_episodes` | Load all rows for the batch's ids once into a `{tmdb_id: Episode}` map, and add each new row to the map as it is created |
| R9 | `select(func.count()).select_from(Episode).where(show_id)` | `tmdb_orch` ×2, `path_import` ×2 | `services/episode_lookup.count_show_episodes` |
| R10 | "Adopt episode": set `file.episode_id = ep.id` and, if `parsed_season` is missing, fill it from the episode | `parse.run`, `sync._fill_missing_episodes`, `manual_match._assign` | `services/episode_tracking.link_file_to_episode(file, ep)` |
| R11 | Success/failure bookkeeping after a transfer is written out twice: once on the normal path and once on the cancellation path. Marking interrupted downloads is also written twice. | `download.run` | `_record_transfer(...)`, `_mark_interrupted(...)`, `_persist_best_effort()` |
| R12 | "Mark routed, then track the episode" is written 3 times | `route.run` (retry branch, already-at-destination branch, after a move) | `RouteOrchestrator._mark_routed` |
| R13 | `select(Episode).where(Episode.id == file.episode_id)` | `route.run`, `route._update_episode_tracking` | `session.get(Episode, id)` |
| R14 | The "could not resolve feed" warning is written 3 times; building `extra_config` is written twice | `rss_import._upsert_subscriptions` | `_warn_unresolved_feed(...)`; split into `_promote_stub`, `_create_subscription`, `_apply_update` |
| R15 | "Do it for real and emit X, or emit `[DRY RUN] …`" branches (6 pairs); the stop/restart of Deluge spans 70 lines of `try`/`finally` | `rss_publish.run` | `_deluge_paused(result)`, an async context manager |
| R16 | `TMDBSyncResult(shows_synced=0, episodes_upserted=0, episodes_skipped=0)` | `sync.run` ×4 | `TMDBSyncResult.empty()` |
| R17 | Fuzzy match on `token_set_ratio ≥ 85` where a tie for best score counts as ambiguous | `rss_import._fuzzy_show_id`, `services/rss_stub` (the picker from services plan Task 12) | `services/fuzzy_match.unambiguous_best_match` |
| R18 | Hand-written `json_schema` dict | `alias_orchestrator._ALIAS_RESPONSE_FORMAT` | `llm_json.json_schema_format` (services plan Task 5). **Not** `request_json_object`, because the alias parser deliberately also accepts a bare JSON list. |

## 4. Complexity hotspots

| Function | C901 | Replacement pattern | Target |
|---|---|---|---|
| `DownloadOrchestrator.run` | 28 | Split by phase: `_dry_run_preview`, `_claim_batch`, `_transfer_batch`. Per-file bookkeeping goes in `_record_transfer` (R11). | ≤ 10 |
| `SeedOrchestrator.run` | 26 | `_remote_inventory` (R4) + `chunked_existing_statuses` (R5) + `_insert_seeded_batches` + `_mark_directories` | ≤ 8 |
| `RouteOrchestrator.run` | 24 | **Per-item command.** `_route_one(file, show) -> RouteOutcome` returns an enum, and `run` tallies the outcomes with a `Counter`. Supporting helpers: `_unique_destination`, `_mark_routed` (R12), `_effective_season`. | ≤ 10 |
| `RssImportOrchestrator._upsert_subscriptions` | 24 | Split into three phases (R14) | ≤ 8 |
| `ParseOrchestrator.run` | 22 | Per-item command: `_parse_one(file) -> ParseOutcome`, plus `_apply_match` and `_ensure_show_local_path` | ≤ 10 |
| `PathImportOrchestrator._process_show_entries` | 21 | `_unresolved_result`, `_ensure_local_path`, `_track_entry -> EntryOutcome`, `_emit_summary` | ≤ 10 |
| `ScanOrchestrator.run` | 20 | `_remote_inventory` (R4) + `_record_new_files` (R6) + `_mark_walked_directories` | ≤ 8 |
| `ManualMatchOrchestrator._resolve_show_by_tmdb_id` | 17 | R3 primitives + `_fill_missing_show_fields` | ≤ 8 |
| `SyncOrchestrator.run` | 17 | `_sync_tmdb_phase(...) -> tuple[TMDBSyncResult, TMDBOrchestrator \| None]`, `TMDBSyncResult.empty()` (R16), `_emit_phase_summary` | ≤ 8 |
| `PathImportOrchestrator._tmdb_create_show` | 14 | `_pick_tmdb_candidate(...) -> tuple[dict, str]` + R3 primitives | ≤ 8 |
| `RssPublishOrchestrator.run` | 14 | `_deluge_paused` (R15) + `_backup` / `_publish` steps | ≤ 8 |
| `route._season_dir_name`, `sync._fill_missing_episodes`, `path_import.run`, `backfill.run`, `show_rematch._restore_tracking_and_relink`, `tmdb_orch.sync_show_episodes` | 9 | Most fall to 9 or less as a side effect of R7, R8 and R10. `_season_dir_name` is a pure function with thorough tests, so it is left alone. | ≤ 9 |

Final ratchet target for `src/jidou/orchestrators`: **10**.

## 5. Dead or redundant paths

| ID | Item | Action |
|---|---|---|
| D1 | `route.run`: `if not dry_run:` sits right after `if dry_run: … continue`, so it is always true | Remove the condition (Task 5) |
| D2 | `parse.run`: `matched_by` re-evaluates `self.llm is not None and self.llm.is_available()`, which is already computed once as `llm_active` | Use `llm_active` (Task 6). `is_available()` is a pure configuration check, so the result is the same. |
| D3 | Intra-layer lazy imports in `manual_match`, `path_import` and `show_rematch` | Make them top-level (Task 13), after services plan Task 10 removes the only real cycle |
| — | Re-checks of `parsed_season`/`parsed_episode` that are already filtered in SQL (`show_rematch`), and `if sid is None: continue` (`sync`) | **No action.** They narrow types for mypy and are commented as such. |

## 6. Divergences worth a decision (not changed by this plan)

1. **What happens when event logging fails.** Download, parse, route and
   scan swallow `on_event` exceptions. Sync, path import, RSS
   import/publish and the services LLM helpers let them propagate. In
   the worker harness, `on_event` writes to the database through a
   separate session. A database hiccup there therefore aborts a sync or
   a path import, but not a download. `EventSink` keeps each module's
   current choice through `swallow_errors=`.
2. **Race recovery in show provisioning.** `path_import` looks the show
   up again **by title** after an `IntegrityError`; the other two look
   it up by `tmdb_id`. `manual_match` does not call
   `ensure_episode_group_map` after recovering from the race. On alias
   failure, `path_import` rolls back, `manual_match` re-raises
   `SQLAlchemyError`, and `show_creation` only logs. R3 makes each of
   these choices an explicit argument instead of merging them.
3. **Name-agreement rules.** `parse._is_exact_alias_match` compares with
   `sanitize_alias`, exactly. `path_import._agrees_with_show` compares
   punctuation-stripped titles and the alias list. The difference
   between them is "Daredevil: Born Again" against "Daredevil Born
   Again".
4. **Auto-populating `local_path`.** `parse` only does it when
   `content_type` is known or the show is a movie. `path_import` always
   does it (it defaults to TV). `show_creation` uses its own
   `auto_local_path`.
5. **`sync.run(show_id=…)` for a show that does not exist** returns an
   empty TMDB result without any event or log line.
6. **The two fuzzy matchers resolve exact matches differently** (R17).
   `rss_import` builds a `{title.lower(): id}` dict, so among shows with
   the same title the last one wins. `rss_stub` scans the list and the
   first exact match wins. R17 shares only the fuzzy, tie-is-ambiguous
   step.

## 7. Priorities

- **High:** R1/R2 event sink and callback types (every later task
  depends on them), R3 show provisioning, per-item commands for route,
  parse and download, R4/R5/R6 scan and seed discovery.
- **Medium:** O1/O2/O3 domain errors and injected TMDB, R7/R8/R9 TMDB
  episode upsert, R16 sync phases with R10, R14/R15 RSS import and
  publish, splitting up `path_import`.
- **Low:** R17 shared fuzzy matcher, R18 alias schema, D3 lazy imports.
- **Deferred to the merged plan:** the §6 decisions; O5 (moving the
  alias prompt next to its consumer, or moving every prompt to a
  neutral `jidou/prompts/` package); a "pipeline stage" protocol that
  would let `SyncOrchestrator` build its phases from a list. The plan
  stops at helper extraction because the five phases have different
  constructor arguments, and each one's summary event is worded
  differently.

## 8. Interaction with the other plans

- **Services plan Task 10** moves `get_or_create_show_from_tmdb` into
  `orchestrators/show_creation_orchestrator.py`. This plan's Task 3
  builds on that file, so it must run after services PR 7.
- **Services plan Tasks 5 and 12** create `json_schema_format` and the
  `rss_stub` picker. This plan's Task 14 (R17/R18) needs both, so the
  last PR runs after services PRs 3 and 8.
- **API plan.** Task 9 (domain errors) adds an exception handler in
  `main.py` and removes the `try/except FeedOnboardingError` in the RSS
  route. If the API plan's Task 14 has already split `rss.py`, edit the
  split file that contains that route. The HTTP status and the
  `{"detail": …}` body are unchanged, so the API plan's OpenAPI snapshot
  is not affected.
- **Services plan Task 12** creates `basename_any`, which this plan's
  path-import task (Task 12) uses. So the path-import PR runs after
  services PR 8.
