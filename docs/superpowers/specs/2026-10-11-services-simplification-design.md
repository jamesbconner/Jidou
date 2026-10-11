# Services Layer Simplification — Analysis (Spec)

**Date:** 2026-10-11
**Scope:** `src/jidou/services/` only (36 modules, plus `__init__.py` and
2 prompt files; 8,535 lines in total).
**Status:** Analysis complete. The companion plan is
`docs/superpowers/plans/2026-10-11-services-simplification.md`. It is the
second of the per-layer analyses. The first was
`2026-10-11-api-simplification-design.md`. `orchestrators/`, `workers/`,
`models/`, `schemas/` and `frontend/` are still to be analyzed, and all
the plans will be merged before execution.

Measurements were taken at commit `71aa2e8`. Complexity numbers come from
ruff `C901` with `max-complexity=8`, plus `PLR0911`, `PLR0912` and
`PLR0915`. Dependency counts come from an AST import scan of
`src/jidou/**`.

---

## 1. Summary

Most of the services layer is in good shape. Most modules are small, have
one job and are pure functions or thin classes, and they come with good
docstrings and dedicated tests. There are four kinds of problems:

1. **The same mechanism is written several times.** There are three
   in-flight request deduplication ("single-flight") implementations, three copies of the SFTP
   directory-entry filter, five copies of "call the LLM, then parse and
   validate the JSON", four copies of "open a Redis client, use it, close
   it", and two copies of the YaRSS2 include/exclude regex rules.
2. **A few large functions with long if/elif ladders.** Twelve functions
   score above 8. The worst are `TMDBService._request` (17),
   `path_parser._parse_episode` (16), `path_parser.scan_show_directory`
   (15) and `LLMService.complete` (14).
3. **Two imports point up the layer stack.** `pubsub_subscriber` imports
   `jidou.api.websocket`, and `show_creation` imports two orchestrators
   inside function bodies to avoid an import cycle.
4. **Some dead code.** One public TMDB method has no callers in `src/`,
   two provider-dispatch `else` branches can never run, there is one dead
   assignment, and one TMDB method duplicates another.

## 2. Structural map of current dependencies

Inbound import counts by layer (`in=`), and outbound `jidou.*` edges:

```
                     ┌────────────── foundation (no jidou.services deps) ──────────────┐
                     │ llm_service (in=21)   tmdb ─► cache, rate_limiter (in=19)         │
                     │ progress (in=15) ─► models.task, config                           │
                     │ sftp_service (in=12) ─► file_filters                              │
                     │ path_transport (in=8)  episode_tracking (in=8)  sys_name (in=4)   │
                     │ cache, rate_limiter ─► config  llm_json  file_filters             │
                     │ path_resolution  alias_handling  episode_watching  settings_service│
                     └──────────────────────────────────────────────────────────────────┘
 composite services:
  episode_file_matching ─► episode_lookup, episode_group_mapping ─► tmdb,
                           episode_match_llm ─► llm_service, llm_json
                           path_parser ─► file_filters, path_transport
  filename_parser ─► llm_service, llm_json          rss_regex_suggestor ─► llm_service, llm_json, models.rss
  feed_entry_grouping ─► feed_fetch ─► cache, rate_limiter ;  ─► filename_parser
  tmdb_mapping ─► tmdb, sys_name, models.show       rss_stub ─► rss_config, models.rss
  synthetic_file / file_reconciliation ─► path_transport, models.downloaded_file
  show_creation ─► tmdb, tmdb_mapping, llm_service, path_resolution, sys_name, schemas.show_schema
                   ★ orchestrators.tmdb_orchestrator, ★ orchestrators.alias_orchestrator (lazy imports)
  pubsub_subscriber ─► ★ api.websocket.task_progress.manager ★

 consumers: api (routes) ── orchestrators ── workers ── main.py (pubsub_subscriber, llm_service)
```

Single-consumer modules, which could be merged into their caller if
wanted (no action planned): `episode_watching`, `feed_entry_grouping`,
`feed_subscription_match`, `file_reconciliation`, `rss_regex_matching`,
`rss_regex_suggestor`, `show_search` (all used only by `api`), and
`pubsub_subscriber` (used only by `main`).

### Layering violations

| ID | Violation | Why it matters |
|---|---|---|
| L1 | `services/pubsub_subscriber.py` imports `jidou.api.websocket.task_progress.manager` | A service depends on the API layer. Tests have to patch a module global. |
| L2 | `services/show_creation.py` imports `TMDBOrchestrator` and `generate_aliases` inside function bodies | A service depends on orchestrators. The lazy imports exist only to avoid an import cycle. The function commits transactions and coordinates three subsystems, so it is really an orchestrator. |
| L3 | `rss_regex_suggestor.RegexSuggestionError(status_code, detail)` | HTTP status codes are chosen inside a service. **Deferred**: the fix touches `api/routes/rss.py`, which the API plan's Task 14 splits up. |

## 3. Redundant or repetitive code

| # | Pattern | Where | Target |
|---|---|---|---|
| S1 | In-flight request deduplication ("single-flight", the event + owner-election version) | `tmdb.TMDBService._request` (election capped at 2 rounds; waiters re-raise the owner's error), `llm_service.LLMService.complete` (no cap; failure means "cache still empty"; skipped when `bypass_cache=True`). A third variant, `feed_fetch.FeedFetchService.fetch_entries`, shares one `asyncio.Task` and is already minimal. | `services/single_flight.py: ElectedSingleFlight` with `max_rounds: int \| None`. TMDB and LLM adopt it. Feed fetch stays as it is. |
| S2 | "Call LLM → `None` check → `parse_llm_json` → dict check → coerce ints" plus hand-written `json_schema` dicts | `episode_match_llm` ×3, `filename_parser.parse_filename`, `rss_regex_suggestor._request`; 6 schema dicts in services, and `episode_parse` and `episode_match` have identical schemas | `llm_json.json_schema_format(name, properties)`, `llm_json.request_json_object(...) -> JsonCallResult`, `llm_json.coerce_optional_int(value)` |
| S3 | `media_type` validation copied 8 times; `get_show_seasons` duplicates `get_details("tv")` | `tmdb.py` | `_require_media_type(media_type, allowed)`; `get_details(..., bypass_cache=False)`, which `get_show_seasons` delegates to |
| S4 | Exponential-backoff retry loop | `tmdb._get_with_retry`, `sftp_service._execute_with_retry` | **No action.** The loops look alike but differ in what they retry, how many attempts they make, the errno cases where SFTP gives up at once, and the final log line. A shared helper would need about five hooks to cover both, and each loop is about 25 lines today. |
| S5 | SFTP `readdir` entry filter (skip `.`/`..`, check whether it is a directory, `is_valid_directory`, `fnmatch`, `is_valid_media_file`, `is_recently_modified`, build `RemoteFile`) | `sftp_service.list_remote_files`, `_collect_files_recursive`, `list_remote_children` | `_classify_entry(entry, parent, pattern) -> _EntryVerdict` |
| S6 | Per-call Redis client open/close; the `"task_progress"` channel name is defined twice | `cache._get_redis`, `rate_limiter._get_redis`, `progress.emit_progress`, `pubsub_subscriber.start`; `REDIS_CHANNEL` in `progress` and `pubsub_subscriber` | `services/redis_conn.py: redis_session(url, *, decode_responses)`, `TASK_PROGRESS_CHANNEL` |
| S7 | `select(Episode).where(show_id, …).order_by(id).limit(1)` written 3 times; one more copy without `order_by`/`limit` | `episode_lookup.resolve_episode` ×3; `episode_match_llm.llm_match_episode` (the risk from issue #313: `MultipleResultsFound` on duplicate rows) | `_first_episode(session, show_id, *criteria)`; `llm_match_episode` calls `resolve_episode` |
| S8 | The "LLM episode-list fallback" tail is copied 3 times | `episode_file_matching.match_entry_to_episode` | `_llm_list_fallback(..., default_season, default_episode)` |
| S9 | `x.replace("\\", "/").rsplit("/", 1)[-1]` | 3 times in services, 3 times in `orchestrators/path_import_orchestrator.py` | `path_transport.basename_any(path)` |
| S10 | `"synthetic-import://"` string literal | `synthetic_file`, `file_reconciliation`, and 5 code sites in `api/routes/shows.py` (plus docstrings) | `synthetic_file.SYNTHETIC_IMPORT_SCHEME`, `synthetic_remote_path()`, `is_synthetic_remote_path()` |
| S11 | YaRSS2 include/exclude rules (`include` must match, `exclude` must not; empty `include` selects nothing) | `rss_regex_matching.evaluate_regex`, `feed_subscription_match._CompiledRule.accepts` | `rss_regex_matching.CompiledFilter` (`accepts(title)`) |
| S12 | The terminal-status set is built inline twice; "select BackgroundTask by celery id" is written 3 times | `progress.update_task_status`, `create_task_record`, `check_task_cancelled` | `TERMINAL_STATUSES` constant, `_select_task(celery_task_id, *, refresh)` |
| S13 | LIKE-escaping copied; alias normalization (`strip().lower()`) copied | `show_lookup` (inline) and `show_search._escape_like`; `show_lookup` and `alias_handling.sanitize_alias` | Public `show_search.escape_like`; `show_lookup` uses `sanitize_alias` |
| S14 | Boolean settings getters that differ only by key | `settings_service.get_show_adult_content`, `get_similar_titles_enabled`, `get_similar_titles_include_external` | `_get_bool(session, key)` |
| S15 | `_UNSET = object()` sentinel defined twice | `episode_tracking`, `episode_watching` | **No action.** Two lines; sharing them would add an import for no gain. |

## 4. Complexity hotspots

| Function | C901 | Other | Replacement pattern | Target |
|---|---|---|---|---|
| `tmdb.TMDBService._request` | 17 | PLR0912/0915 | Single-flight object (S1). The election loop moves out of the method. | ≤ 8 |
| `path_parser._parse_episode` | 16 | 11 returns | **Ordered rule table** (Chain of Responsibility): `_EPISODE_RULES: tuple[_EpisodeRule, ...]`; each rule is a pattern plus an extractor. The compact-code heuristic stays as a separate last-resort function. | ≤ 5 |
| `path_parser.scan_show_directory` | 15 | PLR0912 | Extract `_iter_media_files(root, recursive)` (the walk with symlink-cycle pruning) and `_entry_from_stem(...)`, which `parse_line` also uses. | ≤ 6 |
| `llm_service.LLMService.complete` | 14 | PLR0912/0915 | Single-flight (S1) + **Strategy** for providers: a `{provider: bound call}` table replaces the `if`/`elif`/`else` ladder; `_strip_thinking()` | ≤ 8 |
| `pubsub_subscriber._listen` | 12 | — | Extract `_handle_message(message)`; the init guard runs once, before the loop | ≤ 6 |
| `episode_file_matching.match_entry_to_episode` | 11 | 7 returns | `_llm_list_fallback` (S8) | ≤ 8 |
| `episode_match_llm.llm_match_episode` | 11 | 9 returns | `request_json_object` (S2) + `resolve_episode` (S7) | ≤ 7 |
| `sftp_service._collect_files_recursive` | 10 | — | `_classify_entry` (S5) | ≤ 6 |
| `show_creation.get_or_create_show_from_tmdb` | 10 | — | Move to an orchestrator (L2); `_existing_show(...)` is copied twice; `_sync_episodes_best_effort(...)` | ≤ 7 |
| `rss_stub.ensure_rss_stub` | 9 | — | Pure `pick_unlinked_subscription(subs, title)` | ≤ 5 |
| `sftp_service.list_remote_children` | 9 | — | `_classify_entry` (S5) | ≤ 5 |
| `feed_fetch.FeedFetchService._follow_redirects` | 9 | — | **No change.** This is an SSRF and redirect guard. The code is flat and reviewed, and it is security-sensitive. | 9 (sets the final ratchet) |
| `episode_match_llm.llm_parse_episode` / `llm_pick_candidate` | <9 | 7–8 returns | `request_json_object` (S2) | fewer returns |

Final ratchet target for `src/jidou/services`: **9**. The only function
left at 9 is `_follow_redirects`.

## 5. Dead or duplicate paths

| ID | Item | Evidence | Action |
|---|---|---|---|
| D1 | `TMDBService.get_episode_details` | No callers in `src/`. Only `tests/test_tmdb.py` uses it. | Delete it and its tests. |
| D2 | `else: raise RuntimeError("Unsupported LLM provider")` in `test_connection`, and `else: logger.warning(...); return None` in `complete` | `is_available()` rules out `NONE`, and every other enum member is handled above | Removed by the Strategy table. A unit test pins exhaustiveness. |
| D3 | `pubsub = None` (dead assignment) and the `_redis is None` guard that is re-checked on every reconnect | `pubsub_subscriber._listen` | Remove the assignment; run the guard once. |
| D4 | `TMDBService.get_show_seasons` | Same request as `get_details(tmdb_id, "tv")`. Its only caller is `TMDBOrchestrator`, but about 10 orchestrator tests mock it by name. | Keep the name as a one-line delegate to `get_details(..., bypass_cache=...)`, so there is one request path and no test churn. |

## 6. Divergences worth a decision (not changed by this plan)

These look like duplication, but each copy behaves differently. Merging
them would change behavior, so the plan keeps each one as it is and
lists it here:

1. **Media extension lists.** `path_parser._MEDIA_EXTENSIONS` (9 types)
   leaves out `.iso`, `.av1` and `.ogm`, which are in
   `file_filters.MEDIA_EXTENSIONS` (12 types). As a result, bulk path
   import rejects files that a local directory scan (which uses
   `file_filters`) accepts.
2. **SxE regex caps.** `filename_parser._SE_PATTERNS` allows a 3-digit
   episode in `NxNNN`, but `path_parser._SxE_PATTERN` allows only 2
   digits.
3. **Quality tokens.** `filename_parser._QUALITY_PAT` and
   `path_parser._COMPACT_QUALITY` are separate lists of resolutions.
4. **Single-flight semantics.** On repeated failure, TMDB fails fast after
   2 election rounds, while the LLM service keeps electing new owners
   forever. TMDB also deduplicates `bypass_cache` calls; the LLM service
   does not. S1 keeps both behaviors through constructor parameters.
5. **YaRSS2 filter edge cases.** `evaluate_regex` truncates titles to 300
   characters and raises on an invalid pattern. `SubscriptionMatcher`
   does not truncate, and it drops an invalid pattern with a warning. An
   invalid *exclude* pattern therefore excludes nothing. S11 shares only
   the `accepts` rule.
6. **`llm_pick_candidate` with a non-dict JSON reply** reports "could not
   pick a candidate", while the other two LLM helpers report "returned
   non-object JSON". S2 keeps every caller's event text.

The one deliberate behavior change in this plan is **S7**. When duplicate
`(show, season, episode)` rows exist, `llm_match_episode` currently raises
`MultipleResultsFound`. After S7 it returns the row with the lowest id,
the same way the rest of `resolve_episode` already handles duplicates
(issue #313). This is a bug fix, it has its own test, and it is called
out in the PR body.

## 7. Priorities

- **High** (shared mechanisms and the worst hotspots): S1 single-flight
  for TMDB and LLM, S2 structured LLM calls, S7/S8 episode matching, the
  `_parse_episode` and `scan_show_directory` refactor, S5 SFTP entry
  filter.
- **Medium** (layering and smaller shared helpers): S6 + L1 Redis
  helper and pubsub dependency injection, L2 show creation moved to an
  orchestrator, S11 YaRSS2 filter, S9/S10 + `rss_stub` picker, S3 + D1 +
  D4 TMDB surface.
- **Low:** S12/S13/S14 small internal cleanups.
- **No action, on purpose:** S4 and S15. See their rows in §3.
- **Deferred to the merged app-wide plan:** L3 typed suggestion
  exceptions (after the API plan's `rss.py` split); moving
  `enqueue_task`/`TaskDispatchError`/`get_active_task` from `progress.py`
  into the API plan's new `services/task_dispatch.py`; the §6 decisions;
  `alias_orchestrator`'s own `json_schema` and LLM boilerplate (it can use
  S2 once orchestrators are analyzed); renaming `cache.py`'s
  `jidou:tmdb_cache:*` key space, which `feed_fetch` now shares.

## 8. Interaction with the API plan

- The API plan's Task 8 creates `services/task_dispatch.py`, and its
  Task 13 splits `routes/shows.py`. S10 touches 7 literals in `shows.py`,
  so the services plan's Task 12 must run **after** API Task 13 and edit
  the split files. The plan says which files.
- Both plans add a complexity ratchet. This plan uses a separate test
  module (`tests/test_services_architecture.py`), so the two never
  conflict when merged.
