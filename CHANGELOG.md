# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- **The metadata refresh schedule is editable on the Settings page.** The Schedules card on Settings → Services now has a **Metadata Refresh** row (the same enabled badge, hours and next-run line as Full Sync and RSS Import) with controls for **Enabled**, **Run at (UTC hours)** and **Shows per run** (1–500). Changes apply from the next full hour with no restart. The `SHOW_METADATA_REFRESH_SCHEDULE_ENABLED`, `_SCHEDULE_HOURS` and `_LIMIT_PER_RUN` environment variables are now only the starting values, used until something is saved; the interval and lookback variables stay environment-only. Full Sync and RSS Import are unchanged: environment variables, restart required.
  - Beat can't change its crontab at runtime, so it now ticks **every hour** and the task checks the saved enabled flag and hours, skipping quietly (no task-history row) when not due.
  - `GET`/`PATCH /api/settings` gain `metadata_refresh_schedule_enabled`, `metadata_refresh_schedule_hours` (validated, stored sorted and de-duplicated, e.g. `"16, 4"` becomes `"4,16"`) and `metadata_refresh_limit_per_run` (1–500). The response reports the value the job will actually use, so a hand-edited invalid value is not shown as if it worked.

## [0.4.9] — 2026-10-17

Fixes show metadata going stale after a show is added: a show that ended or was renewed afterwards kept its old TMDB status and next/last episode, so the RSS subscription recommendations could suggest turning off a returning show's subscription.

### Fixed
- **Stale show metadata no longer drives wrong RSS recommendations.** Show metadata (`status`, `in_production`, `next_episode_to_air`, `last_episode_to_air`, season/episode counts, ratings and the other TMDB-owned columns) used to be written only when a show was created, matched or rematched, so a show that ended or was renewed afterwards kept a stale status. That made `GET /api/rss/subscriptions/recommendations` suggest turning off the subscription of a show TMDB now reports as "Returning Series". A new job refreshes a capped batch of the most suspect shows live from TMDB, bypassing the response cache, and writes only TMDB-owned columns: `local_path`, aliases, poster overrides and the active episode group are never touched.
  - Migration `f6a7b8c9d0e1` adds `shows.metadata_refreshed_at` (nullable). Existing shows start as "never refreshed" and are picked first. A database restore also leaves it NULL.
  - Shows are chosen by priority: contradictory data (a stored "next episode" already in the past), never refreshed, the latest season finished since the last refresh, zero votes, airing shows due (7 days), unknown status (30 days), then ended/cancelled/released shows (90 days). RSS-subscribed shows rank first within each group. Shows whose last air date is older than 5 years are skipped, and a show is never refreshed twice within 24 hours.
  - New task type `refresh_show_metadata` (`POST /api/tasks/trigger`), scheduled daily at 04:00 UTC, **enabled by default**. Settings: `SHOW_METADATA_REFRESH_SCHEDULE_ENABLED`, `_SCHEDULE_HOURS`, `_LIMIT_PER_RUN` (default 10), `_STALE_DAYS` (30), `_AIRING_DAYS` (7), `_ENDED_DAYS` (90), `_LOOKBACK_YEARS` (5). The limit is per run, not per day.
  - `POST /api/shows/{show_id}/refresh-metadata` refreshes one show on demand.
  - A show TMDB no longer has (404) is stamped as refreshed and reported as failed, so it does not crowd out other shows on every run.
- **Show Detail has a Refresh Metadata button** for refreshing one show immediately. Calls `POST /api/shows/{id}/refresh-metadata` and shows a pending state and any error next to the button. It invalidates the show and Dashboard caches, since a refresh can change the title, poster and status shown on cards.

### Changed
- **Show Detail sidebar is less cluttered.** Remove Show, Add/Edit RSS and Refresh Metadata stay visible. Fix Match, Set Type, Manage Aliases and Change Images moved into a single **Action** menu. Sidebar buttons are `w-36` (was `w-28`) so "Refresh Metadata" fits.
- **New `Menu` UI component** (`components/ui/Menu.tsx`): an accessible menu button (arrow keys, Home/End, Escape returns focus, closes on outside click or Tab).
- `Button` accepts a `ref` in its prop type (React 19 already passed it through at runtime).
- `TMDBService.get_external_ids`, `get_episode_groups` and `fetch_show_metadata` accept `bypass_cache`.
- Shows created or rematched from a full TMDB fetch, and shows backfilled, are stamped with `metadata_refreshed_at`. A show created from search-card fields only (TMDB details failed) is left unstamped so the job picks it up first.

## [0.4.8] — 2026-10-12

Wave 5 completes the simplification roadmap. It carries out the 20 approved decision follow-ups (DF-1 … DF-20), which change behaviour on purpose, and closes the program with a documentation and verification pass (XL-3). Each DF item first added a test pinning the new behaviour and showed it failing on the old code; every existing assertion that encoded the old behaviour is named in its PR. Items touching the database were also checked against a real PostgreSQL 16 database.

### Added
- **`GET /api/shows/index`** (#737, DF-18): a lightweight show index (`ShowIndexEntry`: `id`, `tmdb_id`, `title`, `sys_name`, `aliases`, `media_type`, `content_type`, `local_path`) for pickers and lookups. On 3,000 shows it returns 602 KB in 45 ms instead of 3.78 MB in 314 ms. `useLibraryIndex` and the subscription editor use it. `GET /api/watchlist` accepts `?show_id=`, so Show Detail checks watchlist membership without fetching up to 10,000 entries.
- **Duplicate files are flagged** (#738, DF-13). Migration `e5f6a7b8c9d0` adds `downloaded_files.duplicate_of_file_id` (a foreign key to `downloaded_files.id`, `ON DELETE SET NULL`, indexed). When parse links a file to an episode that already has a non-synthetic file in `MATCHED`, `ROUTING` or `ROUTED`, it sets the column and emits a warning event. Both files are kept, and routing is unchanged. `FileRead` gains `duplicate_of_file_id`, `GET /api/files` gains `duplicates_only`, and the Files page shows a "Duplicate" badge with a filter.
- **CI type-drift check** (#732, DF-19). `make.py export-openapi <file>` writes the OpenAPI spec without starting a server. The CI frontend job regenerates the types with `openapi-typescript@7.13.0` and fails if they differ from `frontend/src/types/api-generated.ts`.

### Changed (behaviour and contract)
- **Unknown request fields are rejected** (#739, DF-20). JSON request bodies (28 schemas and their nested models) now extend `RequestModel` (`extra="forbid"`), so an unknown field returns 422 `extra_forbidden` instead of being ignored. `RegexHintSample` is split, and `RegexHintSampleRequest` is used for requests. Multipart import uploads are unchanged. The frontend already sent only declared fields.
- **Episode numbers up to 4 digits** (#727, DF-6):
  - Every explicit-marker pattern accepts 1–4 digits: `SxxEyyyy`, `NxNNNN`, `Episode N`, `Ep N`, `- N`, `N - Title`.
  - Bare numbers accept 4 digits only after excluding release years (1900 to the current year + 2) and resolution tokens.
  - Owner rulings: the dash markers (`- N`, `N - Title`) also skip release years and the 4-digit resolutions 1080, 2160 and 4320. The 3-digit tokens 480, 576 and 720 still parse as episodes, as before. The word markers and the `SxxE`/`NxN` markers have no exclusion.
  - The resolution and quality tokens live in one place (`file_filters.RESOLUTION_TOKENS` / `QUALITY_TOKENS`). `DD5.1x264` is no longer read as season 1, episode 264.
- **Event-logging failures never abort work** (#725, DF-7). Sync, path import, RSS import and RSS publish swallow and log a failed event write instead of failing the task. The LLM episode matcher logs `"Event logging failed; continuing"`.
- **Race recovery by `tmdb_id`** (#728, DF-8). When a concurrent create wins, path import now finds the show again by `tmdb_id` instead of by title, so a different show with the same title is never picked. Manual match now also ensures the episode-group map.
- **One name-agreement rule** (#731, DF-9). Parse and path import use `alias_handling.names_agree`: equality against the title or any alias that ignores case and punctuation, and never a substring match. Punctuation variants such as "Daredevil Born Again" now count as an alias match.
- **Duplicate exact titles are ambiguous** (#735, DF-12). When two or more shows match a title exactly, RSS import and the RSS stub picker no longer link either one, the same as a fuzzy tie.
- **Changing a file's show clears old tracking** (#724, DF-2). `PATCH /api/files/{id}` with a new `show_id` and no `episode_id` now clears the old episode's tracking when no other file still references it.
- **Redis is required in admin health** (#730, DF-3). An unconfigured Redis now makes `/api/admin/health` report `{"ok": false, "configured": false, "error": "REDIS_URL not set"}`, matching `/api/health`. The HTTP status and response shape are unchanged, and the UI shows "Degraded".
- **One 503 dispatch message** (#721, DF-1). `POST /api/tasks/trigger` answers a broker failure with `detail="Task broker unavailable"` (was `"Failed to dispatch task to broker"`), like every other dispatch route.
- **Sync warns about a missing show** (#734, DF-11): `"Show id=<n> not found; TMDB phase skipped"`.
- **Typed TMDB sub-objects** (#729, DF-17). `genres`, `networks`, `last_episode_to_air` and `next_episode_to_air` are typed as `TmdbGenre`, `TmdbNetwork` and `TmdbEpisodeRef` (`extra="allow"`). JSON output is unchanged, and a wrong-typed stored value still reads back. The matching `Omit<>` overrides in `api.ts` are removed.
- **More media extensions** (#720, DF-5). The path parser uses the scanner's extension list, so `.iso`, `.av1` and `.ogm` lines are accepted.
- **File responses are loaded eagerly** (#733, DF-4). Every route that returns `FileRead` loads `show` and `episode` up front, and the relationships are `lazy="raise"`. Eleven responses that returned `null` for a linked `show`/`episode` now include it.

The OpenAPI snapshot and `api-generated.ts` were regenerated by DF-3, DF-13, DF-17, DF-18 and DF-20.

### Changed (refactors, no behaviour change)
- **Show creation** (#722, DF-16) takes a frozen `ShowSeed` built at the route boundary, instead of calling `model_dump()` on an HTTP schema.
- **SFTP connection test** (#723, DF-14) builds its service with `create_sftp_service(settings, remote_base_path=...)`.
- **Worker harness** (#726, DF-15). Work functions receive `set_total(total, message)`, and the import workers stop updating the task row directly.
- **`local_path` auto-population** (#736, DF-10) is one helper, `path_resolution.auto_local_path_for`.
- **Program closeout** (#740, XL-3). `docs/architecture.md` and `docs/developer.md` describe the layer boundaries, the layering guards, the complexity ratchets, the `alembic check` gate, OpenAPI snapshot and type regeneration, and `RequestModel`. `docs/setup.md` and `docs/developer.md` state that frontend work needs Node 24 (`.nvmrc`).
- **Complexity ratchets** are unchanged: API 10, services 9, orchestrators 9, workers 8, ESLint 25.

## [0.4.7] — 2026-10-12

Wave 4 of the simplification roadmap finishes the lower-priority cleanups in every layer. It moves shared helpers into one place, makes request vocabularies typed, splits the remaining large frontend components, and removes dead or redundant frontend types. As in earlier waves, every item first added characterization tests that passed on the unchanged code. The model change was also checked against a real PostgreSQL 16 database, where the schema dumps were identical. There is one approved behaviour change, listed below; everything else is unchanged.

### Changed (behaviour and contract)
- **Request vocabularies are typed** (#716, approved B4). These request fields now accept only `"tv"` or `"movie"` (a `Literal`):
  - `ShowCreate.media_type`
  - `RematchRequest.media_type`
  - `FileMatchRequest.tmdb_media_type`

  `FileMatchRequest.content_type` now uses the `ContentType` enum. A rematch with an invalid `media_type` now returns 422 instead of 502. For an invalid value in the other fields, the 422 error `type` changes from `string_pattern_mismatch` to `enum`/`literal_error`. Valid requests behave exactly as before. The OpenAPI snapshot and `api-generated.ts` were regenerated.

### Changed (refactors, no behaviour change)
- **Orchestrators** (#715):
  - Show rematch imports its collaborators at module level.
  - RSS import and the RSS stub picker share one fuzzy matcher, `services/fuzzy_match.py`. A 120,000-case old-against-new comparison was identical.
  - The alias response schema is defined once.
  - One DEBUG line now comes from `jidou.services.fuzzy_match` and no longer includes the score.
- **Workers** (#713):
  - The image-cache purge uses a new `redis_try_lock` helper.
  - Library roots resolve through one `library_root` helper.
  - The sync and import tasks share `LONG_TASK_LIMITS`. The Celery task options are identical.
- **Models** (#714):
  - `database.py` and `alembic/env.py` register mappers with one `import jidou.models`.
  - 45 redundant `nullable=True` arguments on optional columns are removed.

  The generated DDL is unchanged, and `alembic check` is clean.
- **Frontend** (#717, #718):
  - The remaining large components are split into smaller pieces: ShowDetail, Shows, FeaturesTab, ResolveFileModal, AddShowFromFeedPane, Files, RSS, LinkFileModal, RematchModal, ServiceRow, ScanLocalFilesModal and FeedFormModal.
  - Dead API types are removed, and `ContentType` aliases the generated type.
  - Overrides that the generated schema now provides are replaced by aliases.
  - `docs/developer.md` gains a "Frontend structure" section.
- **Build** (#712): `frontend/.dockerignore` keeps host `node_modules` and build output out of the Docker build context. This fixes a `vite build` failure in the frontend image. CI now runs `npm run build`.
- **Complexity ratchets:**

  | Layer | Before | After |
  |---|---|---|
  | ESLint | 51 | 25 |

  API stays at 10, services at 9, orchestrators at 9 and workers at 8.

## [0.4.6] — 2026-10-12

Wave 3 of the simplification roadmap splits the two largest route modules, moves show creation into the orchestrator layer, and gives orchestrators shared building blocks and one HTTP error handler. As in earlier waves, every item first added characterization tests that passed on the unchanged code. The orchestrator items were also compared old against new on a real PostgreSQL 16 database. The few observable changes are listed below; everything else is unchanged.

### Changed (behaviour and contract)
- **Response vocabularies are typed enums** (#703, contract change). These fields now use the existing enums:
  - `FileRead.matched_by` and `FileRead.ignored_reason`
  - the dashboard's two `content_type` fields
  - `OrphanRead.tracked_source`
  - `RssConfigDiff.snapshot_type`

  OpenAPI gains `$ref` components (`MatchedBy`, `IgnoredReason`, `TrackedSource`, `SnapshotType`), and `api-generated.ts` was regenerated. JSON values are unchanged.
- **HTTP errors from orchestrators come from one handler** (#708, #710). The domain errors (`NotFoundError`, `InvalidRequestError`, `UpstreamError`, `ServiceUnavailableError`) now live in an import-free `jidou/errors.py`, and `main.py` maps them to status codes. Regex suggestion uses them too, so its 422 and 503 responses no longer need a route-level re-raise. Status codes, bodies and `detail` strings are unchanged.
- **Manual match uses the shared TMDB service** (#708) instead of creating its own. Results are unchanged; identical concurrent requests are now combined into one call.
- **Minor text changes:**
  - The description of `POST /api/shows` in OpenAPI now names the function's new module (#705).
  - The duplicate-`tmdb_id` race now logs the shared "already exists" DEBUG line.

### Changed (refactors, no behaviour change)
- **API** (#701). The shows and RSS route modules are split by sub-resource:
  - `tmdb_proxy`, `shows`, `show_episodes`, `show_local_files`
  - `rss_feeds`, `rss_subscriptions`, `rss_publish`, `_rss_common`

  Paths, operationIds and the OpenAPI spec are identical, and 42,210 sample requests are routed exactly as before.
- **Services** (#704, #705, #706):
  - TMDB media-type validation lives in one helper, and the dead `get_episode_details` is removed (decision D1).
  - Small helpers are shared in `progress`, `settings_service` and `show_lookup`.
  - Show creation moves to `orchestrators/show_creation_orchestrator.py`, which empties the services upward-import allowlist.
  - New shared helpers: a YaRSS2 filter (`compile_pattern` / `CompiledFilter`), an `rss_stub` picker, synthetic-import helpers and `basename_any`.
- **Orchestrators** (#702, #707, #709):
  - Sync runs as explicit phases, and `link_file_to_episode` is a shared helper.
  - Show-provisioning primitives in `_show_provisioning.py` are shared by show creation, manual match and path import.
  - Path import is decomposed into smaller steps.
- **Workers** (#700). Scheduled tasks are table-driven, the harness gains `_finish`, and unused loggers and default arguments are removed. The trending task is kept (#655).
- **Complexity ratchets lowered:**

  | Layer | Before | After |
  |---|---|---|
  | services | 10 | 9 |
  | orchestrators | 21 | 9 |
  | workers | 9 | 8 |

  API stays at 10 and ESLint at 51.

## [0.4.5] — 2026-10-12

Wave 2 of the simplification roadmap splits each layer's largest functions and components into smaller, tested pieces. Every item first added characterization tests that passed on the unchanged code. The orchestrator and worker items were also compared old-vs-new against a real PostgreSQL 16 database. The few behaviour changes are listed below; everything else is unchanged.

### Changed (behaviour)
- **Episode lookup indexes** (#684, approved B3). Two non-unique indexes on `episodes`, `(show_id, season_number, episode_number)` and `(show_id, absolute_episode_number)`, built concurrently. The downgrade drops them.
- **Task dispatch reports a broken worker module** (#680). If a worker module fails to import when `POST /api/tasks/trigger`, `import_text` or `import_database` dispatches it, a task row is recorded as `failed` and the route answers 503, instead of a 500 with no row.
- **ShowDetail opens one modal at a time** (#683, owner-approved). If a background request (creating an RSS stub, or starting a rematch) finishes while another modal is open, the open modal stays and keeps any typed input; the late one is dropped.
- **Settings PATCH flushes once** (#691). A PATCH that changes several settings now writes them in one flush instead of one per field. Values, order and responses are unchanged.
- **Unknown task statuses are rejected** (#693). `TaskList` no longer coerces an unrecognised `status` to `pending`; it raises a validation error. `BackgroundTask.status` has been enum-typed since #666, so stored rows can't hit this.
- **OpenAPI component names** (#697, contract change only). The two `ShowBrief` components are now `FileShowBrief` and `WatchlistShowBrief`. JSON values are unchanged; `frontend/src/types/api-generated.ts` was regenerated in the same PR.
- **TMDB episode sync batches its lookups** (#695). Episodes are looked up once per season or episode-group batch, not once per episode. TMDB calls, progress ticks and results are unchanged. If a write fails, the database error text now describes the batch's multi-row INSERT.

### Changed (refactors, no behaviour change)
- **Models** (#676, #681). `content_type`, `tracked_source` and `snapshot_type` are typed enums; the column DDL is unchanged. Each `Show` column records where its value comes from (`key`, `tmdb`, `user`, `derived`), and the metadata backfill and database import read from that.
- **API** (#680, #685, #686, #691, #694). Task dispatch lives in `services/task_dispatch.py`; file relinking in `services/file_relink.py`; the Discover feed in `services/discover_feed.py`; and the admin and `/health` checks share `services/health_probes.py`. The settings PATCH is table-driven. Status codes and `detail` strings are unchanged.
- **Services** (#675, #679, #688). `path_parser` uses an ordered rule table and one media-file walker. SFTP listings share a single entry classifier. Redis connections go through `services/redis_conn.py`, and the pub/sub subscriber no longer imports the API layer: its broadcast function is passed in.
- **Workers** (#687, #692). Workers share one SFTP factory (`create_sftp_service`) and one `summarize` helper for task summaries. Database import is table-driven; an export and re-import round trip is byte-identical.
- **Orchestrators** (#677, #682, #689, #696). Scan and seed share a remote-inventory module. Route and parse handle one file per command, with typed outcomes. `DownloadOrchestrator.run` and the RSS import/publish flows are split into small steps; event order, SFTP calls, counts and commits are unchanged.
- **Schemas** (#693). An `ORMModel` base owns `from_attributes`, and the settings bounds come from `settings_service`. A test checks that `TaskType` lists exactly the worker task types.
- **Frontend** (#678, #683, #690, #698). Settings and Shows are split into per-tab components; the parent page still owns state and queries, so request timing and retained filters are unchanged. ShowDetail's twelve modal flags are now one typed union. ResolveFileModal is split into `useResolveCandidates`, `CandidateList` and `ResolveConfirm`. The temporary Settings `no-restricted-imports` override is removed.
- Complexity ratchets lowered: API 15 → 10, services 16 → 10, orchestrators 26 → 21, workers 16 → 9, ESLint 92 → 51.

## [0.4.4] — 2026-10-12

Wave 1 of the simplification roadmap builds the shared foundations each layer's later refactors depend on. Apart from the two fixes below, behaviour is unchanged; each PR was checked against `main` for identical requests, responses, error messages and timeout handling.

### Fixed
- **Duplicate episode rows no longer break LLM episode matching** (#673). When the database holds two rows for the same episode, `llm_match_episode` now picks the lowest-id row (as the rest of `resolve_episode` already did) instead of raising `MultipleResultsFound` (issue #313).
- **Settings no longer refetches `/config` on every visit** (#672). It shares the 60-second cache the other six screens already used, and duplicate refetches of the same query are dropped.

### Changed
- **One home for task statuses** (#666). `ACTIVE_TASK_STATUSES` / `TERMINAL_TASK_STATUSES` live in `models/task.py`; `BackgroundTask.status` is typed. A `str_enum` helper declares the string enums (column DDL unchanged).
- **Orchestrators share one event sink** (#667). `orchestrators/_events.py` (`EventSink`) and `services/callbacks.py` (`OnEvent`, `OnProgress`) replace per-orchestrator event closures; each orchestrator keeps its existing "propagate or swallow" behaviour, now pinned by tests for every orchestrator including RSS import and publish.
- **Single-flight external calls** (#668). `services/single_flight.py` (`ElectedSingleFlight`) now dedupes concurrent identical TMDB requests and LLM completions in one tested place. LLM provider dispatch is one branch; an unknown provider still returns no result without making a network call.
- **Structured LLM calls** (#673). `services/llm_structured.py` gives the four LLM call sites (episode matching, filename parsing, regex suggestion, the connection ping) one prompt → JSON → validate path; the prompts sent are byte-identical. Episode lookup logic is consolidated.
- **API dependencies and lookups** (#665, #669). `get_tmdb` lives in `api/dependencies.py`; `api/lookups.py` replaces the hand-written get-or-404 blocks in five route modules with identical 404 messages.
- **Schemas** (#670). Dead schemas (`import_schema`, `EpisodeRead`, `FileList`, `TaskProgress`, `WatchlistList`) are gone; the eleven regex request fields share `RegexPattern` (with bounded variants so length errors read exactly as before).
- **Worker harness** (#671). One `run_harnessed` entrypoint replaces the per-task timeout handling; `mark_task_timed_out` moves into `workers/_harness.py`; tasks use a task-scoped engine (`task_sessionmaker`) that is always disposed.
- **Frontend hooks boundary** (#672). `useConfig`, `useTaskUntilDone` and shared invalidation helpers replace inline queries; pages and components can no longer import the API client directly (lint-enforced, including relative imports).
- Complexity ratchets lowered: API 16 → 15, services 17 → 16, orchestrators 28 → 26.
- A timing-dependent frontend test (`AddShowFromFeedPane`) now waits for the edited request deterministically.

## [0.4.3] — 2026-10-12

Wave 0 of the simplification roadmap (`docs/superpowers/plans/2026-10-12-simplification-roadmap.md`) adds guards only: tests and CI gates that pin current behaviour before any layer is refactored. No user-visible behaviour changes.

### Added
- **API contract guards** (#657, #662). An OpenAPI snapshot test (`tests/fixtures/openapi_snapshot.json`) fails on any unreviewed schema change; regenerate it with `JIDOU_UPDATE_OPENAPI_SNAPSHOT=1` and justify the change in the PR. A route-shadowing guard checks all 104 served routes (walking FastAPI's included routers in match order), so a parameterised route can never silently capture a literal one. Characterization tests pin the task-dispatch and settings-PATCH hotspots.
- **Complexity ratchets** for each layer: API 16 (#657), services 17 (#658), orchestrators 28 (#659), workers 16 (#661), and ESLint `complexity` 92 for the frontend (#663). Each limit is today's worst function; later waves lower them, never raise them.
- **Layering guards.** Services may not import from the API, orchestrators or workers (#658); orchestrators may not import FastAPI or another module's private names (#659); every worker task module must be in Celery's `include` list, and no task's time limit may exceed the broker visibility timeout (#661).
- **Golden tests** pin the `path_parser._parse_episode` rules (#658), each orchestrator's behaviour when event logging fails (#659), and the worker task summaries (#661).
- **`alembic check` in CI** (#660). The models now declare the five indexes and constraints the migrations already created (the `aliases` GIN index, the unique stub-subscription index, `rss_feeds.remote_key`, the episode tracking index and `background_tasks.celery_task_id`), so model/migration drift fails CI. No migration and no database change.

### Changed
- `frontend/src/api/client.ts`: the four copies of the "non-OK response → `ApiError`" block now share one `ensureOk` helper (#663). Errors are unchanged: same status, parsed `detail` and fallback message, and successful responses are untouched.
- The Python snippets in the simplification plan documents are `ruff format`-clean, so `ruff format --check .` passes on `main` again (#656).

## [0.4.2] — 2026-10-11

### Fixed
- **Nav connection badge no longer sticks on "Reconnecting…" after a task finishes.** An intentional socket close fired `onclose` asynchronously and reported `closed`, overwriting the `idle` state set on cleanup. `onclose` now ignores closes the client requested itself; real network drops still show "Reconnecting…" and retry.

## [0.4.1] — 2026-10-11

### Fixed
- **Browse no longer lists subscribed shows under "Not subscribed".** A group is now "Subscribed" when an active, published subscription on that feed has include/exclude regexes that match the group's titles (the same filter YaRSS2 applies), falling back to a subscription linked to the matched library show. Previously it required the parsed name to exactly match a library alias/title, which failed for every show on trackers whose titles read `Name - TV Series [year] :: Web | MKV | ...`. Those titles now parse to the bare show name and a real episode number (instead of a name carrying the format suffix and an episode taken from `AAC 2.0`).

## [0.4.0] — 2026-10-10

### Added
- **Browse a feed's live entries from the RSS page.** A new **Browse** action on each Feeds-tab row fetches the feed URL server-side (read-only, nothing is saved) and lists what it currently publishes, grouped by the show name parsed from the release titles. Each group shows its season/episode range, whether the show is already in your library, and whether a subscription on that feed already exists. Backed by `GET /api/rss/feeds/{id}/entries`, which caps responses at 5 MiB / 200 entries and a 30 s total deadline, re-validates every redirect, connects only to the address it validated (no DNS rebinding), refuses link-local/multicast/reserved and cloud-metadata targets, shares one in-flight fetch per feed, caches results for 5 minutes (`?refresh=true` bypasses), and never logs, labels or returns the feed URL beyond its host — private-tracker passkeys can sit in the path or the query string.
- `FEED_RATE_LIMIT_PER_SECOND` (default `0.5`) — shared budget for outbound feed fetches, separate from the TMDB and image limits.
- `feedparser` runtime dependency for lenient RSS/Atom parsing.
- **Add a show and its subscription from a feed group in one step.** The Browse modal gains **Add…** on groups that aren't subscribed yet: pick the library or TMDB show, review the suggested filter and its match count against the feed's current titles, and create both the show and the subscription together (`POST /api/rss/feeds/{id}/add-show`, which also supports `dry_run`). The feed's parsed name is taught as a show alias, an unlinked import stub is adopted instead of duplicated, and the call is idempotent. Subscriptions are created disabled unless you tick **Enable now**.
- **Regex suggestions from a feed group's real release titles.** `POST /api/rss/feeds/{id}/suggest-regex` shows the LLM the titles the feed actually publishes for a show (so the pattern follows the feed's spelling, not just the catalogue title) and reports which of them the suggestion selects; `POST /api/rss/feeds/{id}/test-regex` previews a hand-edited filter the same way without calling the LLM. An empty include pattern selects nothing, as in YaRSS2, and the preview says so.

### Changed
- Adding a show from TMDB (`POST /api/shows`) now goes through a shared `services/show_creation.py`, so the RSS onboarding flow reuses the same upsert, metadata fetch, episode sync and alias generation. Behaviour of the endpoint is unchanged.
- The subscription regex suggester now lives in `services/rss_regex_suggestor.py` (shared by the existing `POST /api/rss/subscriptions/{id}/suggest-regex`, whose behaviour is unchanged).
- **Regex suggestions no longer impose a generic quality preference on feeds that supply their own guidance.** The suggester used to always tell the model to match 1080p BluRay/WEB-DL releases and exclude FRENCH/GERMAN/INTERNAL/CAM/TS tags, which fought a feed's regex samples and exclude hint. Those defaults now apply only when the feed has no regex include samples, no exclude hint (an empty hint counts), and no real release titles; otherwise the feed's own evidence is authoritative. Feeds without hints behave as before. Re-suggesting on a feed with hints may now return a different pattern than it used to.

## [0.3.2] — 2026-10-10

### Fixed
- **Resolving a file by hand now adds the parsed name as a show alias.** A manual match (Files page → Resolve or Rematch) saves the file's parsed show name as a user alias of the chosen show, so later files with the same name match automatically instead of landing in Unmatched again. Names that already equal the show's title are skipped. The alias helper now lives in `services/alias_handling.py`, shared with the parse pipeline.

## [0.3.1] — 2026-10-10

### Fixed
- **Resolve modal: library matches now sit above the TMDB search.** The "In your library" section was rendered between the "Search TMDB" controls and the TMDB results, splitting them apart. It now comes first, so the TMDB label, links and results stay together.

## [0.3.0] — 2026-10-10

### Added
- **Local library search API.** `GET /api/shows/search` now searches the local library by title, alias, `sys_name`, and folder name (the last component of `local_path`, so a remake's `Show (2019)` folder is found), ranked exact > prefix > substring with a `matched_on` field. The Shows page's Library search and the file Rematch modal use it instead of a title-only client-side filter.

### Changed
- **TMDB endpoints moved under `/api/shows/tmdb/`.** `GET /api/shows/search`, `/trending`, and `/discover` are now `GET /api/shows/tmdb/search`, `/tmdb/trending`, and `/tmdb/discover`, alongside the existing `/tmdb/{tmdb_id}`. `/api/shows/search` now means the local search above.

### Fixed
- **Local library search no longer returns a 500.** `GET /api/shows/search` failed for every query once any show had `aliases` stored as a JSON `null` (Postgres: "cannot extract elements from a scalar"). Non-array alias values are now treated as empty.
- **Resolve modal no longer proposes a new folder for a show you already have.** The Files page Resolve modal now lists matching shows from your library (by title, alias, system name, or folder name) above the TMDB results, and assigns the file to the existing show and folder. Picking a TMDB result whose show is already tracked does the same, so a remake's `Show (2019)` folder is no longer shadowed by a suggested `Show` folder. Closes #644.

## [0.2.1] — 2026-10-09

### Fixed
- **RSS regex suggestions no longer use `\s` for spaces.** The suggester's system prompt now states the convention: spaces in a title are written as a bare `.`, and punctuation (commas, quotes, semicolons, colons, exclamation and question marks) as `.*`, with an example. Previously the LLM defaulted to `\s` even when every feed sample used periods.

## [0.2.0] — 2026-10-09

### Added
- **RSS page: Key filter.** A new dropdown on the Subscriptions tab narrows the list to stubs (subscriptions with no remote key yet) or to subscriptions that already have one. Like the other RSS filters, the choice is remembered.
- **RSS feeds: sample name + hint pairs.** Each feed can hold up to 3 pairs of a real release title and the regex that matches it. The LLM regex suggester shows them as worked examples, so suggestions follow the feed's real token order. Existing include hints were migrated into the first slot.

### Changed
- **Show Details: cleaner top of page.** Removed the redundant "← Back to Shows" link (use the navbar's Shows link or browser back) and the extra space above the banner, so it now sits flush under the navbar.
- **RSS feeds: exclude hint is used as-is.** A feed's exclude pattern is now returned verbatim as the suggested exclude regex instead of being offered to the LLM as a style guide.

### Fixed
- **Re-suggest returns a new regex.** The Suggest-regex dialog's Re-suggest button previously replayed a cached answer. It now bypasses the cache and tells the LLM which patterns were already rejected.

## [0.1.4] — 2026-10-03

### Fixed
- **The running version is now visible.** `GET /api/health` and `GET /api/admin/health` report the app `version`, the Settings → Services card shows it next to the health badge, and the OpenAPI schema (`/docs`) advertises the real version instead of FastAPI's default `0.1.0`.

## [0.1.3] — 2026-10-03

### Changed
- **Dependency upgrades.** Python: `redis` 6.4.0 → 8.1.0 (major), `hiredis` 3.4.2, `httpx2` 2.13.1, `hypothesis` 6.168.2, `ruff` 0.16.9, `urllib3` 2.8.0, `virtualenv` 21.7.13. Frontend: `@tanstack/react-query` (+devtools) 5.104.0, `@typescript-eslint/*` 8.70.1, `vite` 8.3.1, `vitest` (+coverage) 5.0.2, `jsdom` 30.1.1, `prettier` 3.9.9, `brace-expansion` 1.1.21. `eslint` 10 is deferred (failing upgrade).

## [0.1.2] — 2026-10-03

### Fixed
- **RSS subscription edit modal now honours unsaved changes.** "Suggest via LLM" uses the regex hints of the feed currently selected in the form (`POST /api/rss/subscriptions/{id}/suggest-regex` accepts an optional `{"feed_id": ...}` body) instead of the last-saved feed, and ticking **Enabled in config** on a new subscription immediately unlocks **Active** — no more save-and-reopen.
- **Newly listed seasons no longer stay hidden behind the TMDB cache.** Show Detail → **Sync Episodes** (`POST /api/shows/{id}/sync-episodes`) now bypasses the TMDB response cache, as the calendar sync already did. Separately, a season-details response with no episodes yet (TMDB lists a new season before populating it) is cached for 1 hour instead of the multi-day default, so scheduled syncs pick up the episodes once TMDB fills them in.

## [0.1.1] — 2026-09-12

Everything below shipped after 0.1.0. Grouped by area rather than by commit — see `git log` for individual changes.

### Dashboard added to Optional Pages; app landing page changed to Shows
- The Dashboard page now has its own on/off switch under **Settings → Features → Optional Pages**, alongside Calendar and Discover (`dashboard_page_enabled` in `app_settings`, defaulting to on). Disabling it hides the nav link the same way Calendar/Discover do.
- Since Dashboard could no longer permanently occupy the app's root route while also being toggleable, Dashboard moved from `/` to its own `/dashboard` path, and `/` now redirects to `/shows` — Shows is the new default landing page.

### Settings page reorganized into four tabs
- Split the crowded **General** tab into **General** (read-only env-backed configuration), **Features** (everything you visually/functionally customize), **Services** (health checks/connection tests, TMDB cache, sync/RSS schedules), and **Data** (unchanged: import/export, SFTP baseline, metadata backfill) — no persisted-settings changes, purely a layout split to reduce scroll depth on the page users actually adjust most often.
- Within Features, cards are grouped by the page each setting affects rather than by mechanism: **Show Detail** (banner style + Similar Titles carousel — previously split across separate "Appearance" and "Recommendations" cards, even though both only affect the show detail page), **Dashboard** (adult content, recently-added carousels, artwork — trimmed to only settings that actually affect the Dashboard page), and **Optional Pages** (Calendar/Discover on-off switches, which were previously miscategorized under "Dashboard" despite only controlling nav links to unrelated pages).
- The General tab's single flat **Configuration** card was broken into discrete cards — Application, Database, Redis, TMDB, LLM, SFTP, Media Paths, and Image Cache — and now also surfaces previously-hidden config: TMDB rate limit/cache TTL, LLM cache TTL, SFTP remote/noscan paths, per-content-type media host paths, and the image cache backend/host path/retention settings (`GET /api/config` gained `image_cache_backend`, `image_cache_host_path`, `image_cache_expiration_enabled`, `image_cache_retention_days`; the rest were already returned by the API but unused by the UI).
- Fixed the new Image Cache card showing the host path identical to the container path: `docker-compose.yml`'s `jidou-api` service forwarded `IMAGE_CACHE_HOST_PATH` into the bind-mount source but never into the container's own environment (unlike `LOCAL_TV_HOST_PATH`/etc., which already did both), so `settings.image_cache_host_path` always fell back to its own default instead of the user's configured value.

### Similar Titles on Show Detail
- New **Similar Titles** carousel on the Show Detail page (`GET /api/shows/{id}/similar`) — merges TMDB `/recommendations` and `/similar` for the show, dedupes, and drops the show itself. Titles already in the library link straight to their detail page; the rest carry the same one-click **Add + Watchlist** action as Discover (create + watchlist + RSS stub), now extracted into a shared `useAddDiscoverResult` hook so the two surfaces stay identical. The assembled list is cached 24h keyed by `(show_id, tmdb_id, count, include_external)`; an empty result caused by a TMDB outage is not cached.
- Three runtime toggles under **Settings → Features → Show Detail** (stored in `app_settings`, no migration): enable/disable the carousel, how many titles to fetch (`similar_titles_count`, 1–40, clamped), and whether to include titles not yet in the library (`similar_titles_include_external`) — off limits the carousel to shows already tracked.
- Bug fixes from Bugbot review: `useAddDiscoverResult`'s `add` is a stable `useCallback` so memoized card lists don't reset the carousel's scroll on unrelated Show Detail re-renders; `similar_titles_count` / `similar_titles_include_external` are folded into the `useSimilarShows` query key so saving either setting refetches instead of showing the stale list; and the backend cache key includes the show's `tmdb_id` so a rematch can't serve the previous TMDB identity's titles for the rest of the TTL.

### Airing calendar: sync missing shows
- New **Sync missing** button on the Calendar page (`POST /api/shows/calendar/sync-missing`) re-fetches TMDB metadata, bypassing the response cache, for every show with a `missing` episode in the visible range — the common cause is a TMDB schedule slip after the stored `air_date` was already written, not a genuinely absent file. Skips shows with **Ignore Missing Eps** set or with no active, published RSS subscription, since neither would ever auto-download the episode anyway.

### Manual TMDB episode-group selection
- Some shows have more than one TMDB numbering scheme (e.g. a combined-episode broadcast order). New **Use Alternate Grouping** action on Show Detail lists available groupings (`GET /api/shows/{id}/episode-groups`) and switches to one (`POST /api/shows/{id}/episode-groups/{group_id}/apply`), replacing the show's episode list; previously tracked episodes with no equivalent in the new grouping become orphaned tracking records instead of silently losing their tracked/watched state.

### Missing Episodes tab
- New **exact-1**, **whole-season**, and **low-owned** quick filters, alongside a rename/reorder of the existing columns for readability and a split into separate Episodes/Seasons columns.
- Total and matched episode/season counts added; orphaned-episode counts are now split by file-tracked vs. watched-only.

### Manual episode-to-file linking follow-ups
- The untracked-episode file picker ("Match File") now surfaces orphaned files in *any* non-transient status (`routed`, `matched`, `error`), not just `unmatched` — a file displaced by another one getting misrouted onto its slot keeps its prior status rather than resetting, so it was invisible to the old `status=unmatched`-only query. The redundant "Fix Eps"-only path for untracked episodes was folded into the same picker.
- New `missing` `FileStatus`, set by a **Scan Local Files** reconciliation pass when a tracked file's on-disk path vanishes (renamed/moved/deleted outside the app), and cleared automatically if the file reappears. New `POST /api/files/verify-paths` lets pickers filter out vanished candidates immediately rather than waiting for the next scan.
- Fixed two Bugbot-flagged issues: path-existence checks on stored paths now decode the JSON/DB-safe transport form first (a literal `%` in a filename was wrongly flagged missing), and host/catalog paths from path-import (which never resolve inside the container) are excluded from reconciliation and picker candidates entirely.

### Discover / Search Shows detail modal
- The shared detail modal (Discover cards and the Search Shows TMDB tab) gained its own **Add** action, so adding a show no longer requires closing the modal first.
- Fixed the recommendation-reason text getting cut off unreadably, and the description rendering under the image instead of under the title.

### Watchlist preview modal
- Clicking a Watchlist row (other than its title link, status select, or Remove button) now opens a quick-look modal with the show's poster, overview, rating, and next unwatched episode, without navigating away from the list.

### Visual refresh
- Replaced the indigo/blue-N accent palette with a new **ocean** accent across the app, then iterated the base neutral palette twice (Graphite Tide, then Stone & Pine) before landing on the current one; fixed a hard-to-read active-tab color in dark mode along the way.

### Frontend performance
- Routes are now lazy-loaded (`React.lazy()` per page) instead of statically imported in `App.tsx`, so each page ships in its own chunk — e.g. Dashboard's `recharts` dependency (~380KB) no longer bloats every other route. A `Suspense` boundary sits around just the page content, so the nav frame stays mounted across navigations. A stale chunk reference after a new deploy now triggers one automatic reload instead of a dead page (Chrome and Safari phrase the underlying error differently; both are matched).

### UI polish
- Modal forms with a fixed-column grid now collapse responsively on narrow viewports instead of overflowing.
- Fixed a `ModalCloseButton` left-margin conflict and touch-target sizing flagged by Bugbot review; scoped `TaskProgressBar`'s CSS transition to `width`/`background-color` instead of `all`.

### Movies: flat routing and direct file linking
- Movies now route to a shared root (`LOCAL_MOVIE_PATH/filename.mkv`) instead of a per-title subfolder — `resolve_show_local_path()` no longer creates `LOCAL_MOVIE_PATH/Movie Name/` for every movie. A movie that still needs its own folder can get one via an explicit `local_path` override on the Show Detail page.
- New **Fix Match** button on a linked movie file opens `ScanLocalMovieFileModal` in a new replace mode — pick or type the correct on-disk file — instead of the episode-oriented `RematchModal`, which reassigned the show rather than the file. `link-movie-file` gained a `replace=true` mode that unlinks the existing file before linking the new one.
- `scan-local-movie-file` is now non-recursive (movies typically share one flat root) and excludes files already linked to *any* show, not just this one, so already-tracked sibling movies don't show up as false candidates.
- Bug fixes from Bugbot review on the above: any untracked file in a shared-root scan can now be linked (previously only the alphabetically-first one could); sibling Link buttons disable once one row links, and a single in-flight-request guard closes a race where two rows could link concurrently; `link-movie-file`'s "already linked elsewhere" check now matches by on-disk path across every `DownloadedFile` (not just synthetic-import rows), and re-linking a previously-unlinked path no longer silently no-ops on an orphaned row.
- Removed the redundant status badge from the movie file row on Show Detail — the Fix Match button already signals when the file is actionable.

### Files page
- Ignored files are now hidden by default under "All statuses" — a new **Show ignored** toggle (`show_ignored` query param on `GET /files`, applies only when status is unset) brings them back. Show Detail's own file panels pass `show_ignored=true` so a show-scoped ignored file still appears there.
- Added **Per Page** / **Max Records** controls matching the Tasks page, and status/pagination/toggle choices now persist to `localStorage` the way the Shows page does.

### Missing Episodes tab filters
- The Missing Episodes tab (Shows page → **Data**) gained content type, status, genre, language, minimum-missing-count, and watchlist-only filters, plus a **Clear filters** button, with filter state persisted independently from the Library tab's filter bar.

### Search Shows metadata modal
- Clicking a poster in the Search Shows modal's TMDB tab now opens a detail popup (title, overview, rating, year) instead of doing nothing, so you can confirm a match before adding it. Reuses the existing Discover detail modal rather than a near-duplicate component.

### RSS Feeds table
- URL, default locations, regex hints, and remote key now show as compact set/unset checkmarks (full value on hover) instead of cluttering the table — except the remote key ID, which reverted back to showing the number directly since a checkmark didn't convey a value useful for cross-referencing the remote YaRSS2 config. Regex hints are now visible in the table for the first time (previously edit-modal only).

### RSS config diff
- New **Diff** button on the RSS page (next to Download) answers "what would change if I published right now?" without touching the remote server — `GET /api/rss/diff` composes the current DB state via the same `RssPublishOrchestrator.compose_config` a real publish uses, then unified-diffs it against the most recent stored snapshot. Both sides are pretty-printed before diffing since the on-disk format is single-line compact JSON.
- Bugbot catch: `run()` now stores a `post_publish` snapshot of exactly what it just uploaded. Without it, the latest snapshot right after a publish was still the `pre_publish` state from *before* that publish, so the diff (and `/rss/download`'s "latest snapshot" lookup) kept comparing against stale state and re-surfaced the just-published changes as still pending.

### RSS dummy-feed reappearing after deletion
- Fixed a bug where a stray "Dummy Feed (error in config was detected)…" feed (YaRSS2's own placeholder for a subscription referencing a nonexistent feed key) kept reappearing after being deleted in Jidou. `build_sub_dict` only ever *set* a subscription's `rssfeed_key` when it had a currently-linked feed with a remote_key — it never cleared a stale one already sitting in `extra_config` from an earlier real config round-trip, so an unlinked (or re-linked to a not-yet-published) subscription kept republishing a dangling reference. YaRSS2 synthesizes the dummy-feed placeholder for any such broken reference, and Jidou's next import faithfully re-created it as a real feed row. `build_sub_dict` now pops any stale `rssfeed_key` when the subscription has no currently-valid feed link.

### Tasks page
- New **Delete** pill button on completed/failed/cancelled task cards (`DELETE /api/tasks/{id}`, blocked while a task is pending/running — cancel first).

### Bug fixes
- Local file scan (`scan_show_directory`, used by **Scan Local Files**) silently skipped symlinked season directories — `Path.rglob` doesn't descend into symlinks on any current Python version, unlike the SFTP scanner which resolves them. Switched to `os.walk(followlinks=True)`, with (device, inode) tracking to prune any symlink that cycles back to an already-visited directory rather than hanging the walk.
- "Episodes synced" confirmation message on Show Detail now renders immediately after the Sync Episodes button that produced it, instead of after both action buttons.

### Internal refactors
- Migrated the frontend from Tailwind CSS v3 to v4 (`@tailwindcss/vite`, `@import "tailwindcss"`, dropped `tailwind.config.ts` in favor of v4's automatic content detection) — completes an upgrade a Dependabot PR couldn't safely land alone because the version bump alone broke the production build (CI's frontend job never ran `npm run build`, only `tsc`/`eslint`/`vitest`). Added the upgrade tool's compatibility rule for v4's `currentColor` default on bare `border`/`divide-y` utilities to avoid a visual regression across several components that relied on the old `gray-200` default.

### Watched tracking
- New `watched`/`watched_at` fields on `Episode` (mirrors the existing `file_tracked`/`file_tracked_at` pattern) — tracks what you've actually seen, independently of `file_tracked` (Jidou has the file) and watchlist status (viewing intent for the show as a whole). Closes #400.
- Per-episode toggle switch on the Show Detail episode list, plus bulk mark/unmark for a whole season or the whole show (`POST`/`DELETE /shows/{show_id}/episodes/watched`, optionally scoped by `season_number`).
- Progress bar under the show overview on Show Detail, and a thin bottom-of-poster overlay on the Shows-page grid card (`ShowList.watched_episode_count`).
- Backup/restore and export cover the new fields — caught by the existing `check_restore_field_coverage` regression test, which fails any future column added to `Episode`/`Show` without a matching restore-side change.
- Episode row cleanup (issue-driven): removed the "Matched"/"Imported"/"Tracked" status pills from the episode list — that detail is already on the Files page — and restyled the row actions (**Fix Match**, **Match File**, **Fix Eps**) as pill buttons instead of underlined text links. Closes #403.

### Discover page
- `GET /api/shows/discover` — a personalized feed seeded from TMDB recommendations for the user's most recently updated `watching`/`completed` watchlist shows, deduped, with shows already in the library excluded and trending TV/movies filling out thin results (cold start falls back to plain trending). Cached 24h, keyed by the current seed show set. Closes #229.
- New Discover page and nav entry, with one-click "Add + Watchlist" per result and a detail modal (poster, overview, rating, "View show"/"View on TMDB" links).
- `seeded_from` on each result names the watchlist shows a recommendation came from — no LLM call involved.

### Dashboard: movies split out
- `GET /api/dashboard/recent-movies` — movies get their own dashboard carousel instead of being mixed into (or filtered out of) "Recently Added Shows"; `recent-shows` now always excludes `content_type="movie"` rows server-side. Closes #255.
- New `dashboard.recent_movies_enabled` setting (default `true`), toggleable from Settings, mirroring the existing `recent_episodes_enabled` pattern.

### Manual episode-to-file linking
- **Match File** action on untracked Show Detail episode rows (issue-driven UX gap): pick an existing unmatched `DownloadedFile` scoped to the show, or type a path Jidou hasn't seen yet — validated on disk, then linked via the new `POST /shows/{show_id}/episodes/{episode_id}/link-file` endpoint. The "type a path" mode uses a content-type picker (mirroring `EditPathModal`) instead of a raw container path.
- **Scan Local Files** — `POST /shows/{show_id}/scan-local-files` walks a show's own `local_path`, runs each file through the shared matching pipeline, and returns `matched`/`unmatched`/`conflict` proposals for review before confirming via `link-file`. Reuses the same regex/episode-group/LLM matching path-import uses, extracted into `services/episode_file_matching.py` so the two features can't drift apart.

### Non-UTF-8 / legacy-encoded filenames
- Scanning a show's local directory (or the show's own directory name) no longer crashes or silently returns nothing when a filename or directory name has a raw Latin-1/cp1252 byte instead of proper UTF-8 (a common signature of libraries authored by older Windows/NAS tooling). Fixed across several passes: stopped the JSON-encoding crash, made the byte-exact path round-trip through `link-file` instead of just being displayable, recovered the actual accented character for display (cp1252 fallback) instead of a `�` placeholder everywhere a tracked/original filename is shown, and finally recovered a show's own on-disk directory even when its raw bytes don't literally match the clean UTF-8 string stored in `Show.local_path`.
- New `services/path_transport.py` (`encode_path_bytes`/`decode_path_bytes`) is the shared mechanism behind the fix — see [Architecture](docs/architecture.md#filesystem-paths-with-non-utf-8-bytes).

### Excluding non-media files from matching
- New `SFTP_NOSCAN_PATHS` config — files under a configured remote path are still discovered/downloaded (never re-fetched) but routed straight to a new terminal `ignored` status instead of entering parse/match/route. For documentaries, theatre recordings, workout videos, etc. mixed into otherwise normal TV/movie downloads.
- `POST /files/{id}/ignore` — manual escape hatch for a stray `unmatched`/`error` file a noscan path didn't catch.

### Poster overrides and image caching
- Manual poster picker (Show Detail → **Change Poster**): pick independently which TMDB poster (English or textless) is used on the Shows-page grid card vs. the Show Details header. Stored on `list_poster_path`/`detail_poster_path` so a TMDB metadata resync never silently overwrites the choice.
- Show Details header switched from a 16:9 backdrop crop to a proper 2:3 poster.
- All poster/backdrop images now proxy through `GET /api/images/{size}/{filename}`, which caches bytes to disk on first request instead of the frontend hotlinking `image.tmdb.org` directly. Registered unauthenticated (plain `<img src>` can't send `X-API-Key`, and the images aren't sensitive). A daily Celery beat task purges cached files past a configurable retention window.
- Image fetches now use their own rate limiter (`IMAGE_RATE_LIMIT_PER_SECOND`, default 5/s) instead of sharing the 1-per-2s TMDB metadata limiter — `image.tmdb.org` is a separate CDN host, so poster loading no longer queues behind sync traffic.

### Show metadata backfill
- Fixed a gap where adding a show via TMDB search/trending ("Add Show", Discover, Watchlist) only ever stored the sparse search-card fields — no genres, external IDs, episode groups. `POST /shows` now fetches full TMDB details the same way path-import and manual-match already do, with a fallback to the sparse fields if the fetch itself fails.
- New `backfill_show_metadata` task (Settings page trigger, dry-run supported) re-fetches and repairs already-affected shows without touching `sys_name` or local file organization.

### Show Detail and Shows page UX
- Watchlist status/queue-position controls and an inline TMDB link moved onto the Show Detail metadata line, instead of a separate flow — shared `WatchlistStatusSelect`/`watchlistStatus.ts` extracted so Show Detail and the Watchlist page use the same vocabulary.
- Actions on Show Detail split into labeled **Show Info** / **Episodes & Files** groups; the RSS control moved from a passive header badge into the header's actual Add/Edit RSS button.
- Shows page sort order and all filter selections now persist across navigation (`localStorage`), not just reloads.
- Shared UI style primitives (`components/ui/Modal`, `Button`, `Card`, `Badge`) replace hand-typed Tailwind strings across all 19 modals, cards, and badges — fixes visible drift in overlay opacity/z-index and gives every modal focus-trap + Escape-to-close consistently (previously only 10 of 19 had it).

### Bug fixes
- Download staging paths mirrored the *entire* remote SFTP path under the staging root, including the deeply-nested, common prefix shared by every file on the SFTP source (e.g. a seedbox path like `/data/sdaa1/myuser/path/to/files/anime/`). On Windows this routinely pushed the staged path past the ~260-character limit and broke transfers, even though only the sub-path *within* the configured `SFTP_REMOTE_PATHS` root (e.g. a show subdirectory) carries any useful information. `DownloadOrchestrator` now strips the longest matching configured scan root before mirroring, so `/data/sdaa1/myuser/path/to/files/anime/ep.mkv` under staging root `k:\staging` lands at `k:\staging\anime\ep.mkv` instead of reproducing the full remote path. Falls back to the old full-mirror behavior for a path outside every configured root (or when no roots are configured), so nothing breaks for already-in-flight files.
- Follow-up to the per-file Scan logging above: on a library with hundreds/thousands of already-downloaded files, every scan emitted an "Already known: X" event per already-tracked file, drowning out the handful of genuinely new discoveries in noise. `ScanOrchestrator` now only emits per-item events for newly discovered files, directory-walk outcomes, and errors — already-known files are silently counted into `files_skipped` instead. The Scan phase summary line (both in `sync` and the standalone `scan` task) now reports that count too, e.g. "Scan: 3 new file(s) discovered, 1204 already known".
- The `sync` task's log only ever showed per-file detail for the Route phase ("Routed 'X' → path"); Scan/Download/Parse collapsed to a single one-line phase summary ("Scan: 9 new file(s) discovered") even though `ScanOrchestrator`, `DownloadOrchestrator`, and `ParseOrchestrator` all already emit the same structured per-item `on_event` callback `RouteOrchestrator` does. `SyncOrchestrator.run()` was simply never forwarding `on_event` to those three — only to Route. Now forwarded to all four phases, so a real sync run shows per-file "discovered"/"downloaded"/"matched"/"unmatched" lines the same way routing already did.
- Shows-page "Recently Aired" sort (`last_aired_desc`) reads `Show.last_air_date` directly, but that column was only ever set at initial import or during a full manual "Rematch" — the routine background episode sync (`TMDBOrchestrator.sync_show_episodes`, run by `sync_all_shows`/the `tmdb` task) never touched it. An actively-airing show could pick up brand-new episodes every sync and still sort as if nothing had aired in months. `sync_show_episodes` now refreshes `last_air_date` from the newest already-aired episode in each synced set (future/unaired episodes are ignored, and a show with nothing aired yet keeps whatever value it already had instead of being reset to null).
- `match` task (`ParseOrchestrator`) now retries `UNMATCHED` files alongside `DOWNLOADED` ones, matching the documented `unmatched → matched` state transition that the query never actually implemented. Previously, downloading a show unknown to Jidou (e.g. a new 500-episode series) left every file `UNMATCHED` permanently once a show was later added/resolved — a plain re-run of `match` now sweeps them all up instead of requiring manual per-file resolution. A successful re-match also clears the stale `error_message` left over from the earlier failed attempt.
- `sync_all_task` (scan → download → match → route) now gets the same extended 6h soft / 7h hard time budget `path_import_task` already had — the default 50-minute soft limit was sized for a single phase and routinely killed real backlogs mid-run.
- Fixed a production crash (`MissingGreenlet`) when a show's TMDB sync failed mid-loop: `TMDBOrchestrator.sync_all_shows()` now rolls back per-show via a `SAVEPOINT` instead of a session-wide `rollback()`, which was expiring every other already-loaded show and triggering an out-of-greenlet lazy reload on the next iteration. Also excludes movies from that sync loop — they have no TMDB `/tv/{id}` season structure to sync.

### RSS / YaRSS2 integration
- New `RssFeed` and `RssSubscription` models; full CRUD API (`/api/rss/feeds`, `/api/rss/subscriptions`), each subscription linkable to a show with optional include/exclude regex filters.
- `rss_import` task — downloads the remote YaRSS2 config and reconciles it into the DB (fuzzy show linking, stub promotion, feed-link resolution via `rssfeed_key`).
- `rss_publish` task — composes the DB state back into a YaRSS2 config and uploads it; optionally stops/restarts Deluge over SSH around the publish with configurable delays so the client doesn't read a half-written file.
- Config snapshots (`GET /api/rss/snapshots`) retained on every publish for diffing/audit.
- LLM-assisted regex suggestions (`POST /api/rss/subscriptions/{id}/suggest-regex`), hardened against prompt injection.
- Subscription health-check Recommendations tab; RSS page with feed/subscription tabs, bulk active-flag patching, and a preview/download of the composed config.
- Active RSS subscription badge on show cards; one-click RSS stub creation from a show or the watchlist.

### Path import overhaul
- Per-file show-name confirmation (issue #282) — each file's own LLM-extracted show name is cross-checked against the directory-resolved show; a confirmed disagreement splits that file off and resolves it independently instead of silently mismatching it.
- `shows-only` and `episodes-only` import modes for partial re-imports.
- Absolute-episode-number fallback for season > 1 misses and ambiguous compact season/episode codes (e.g. `One Piece 212`), tried before falling back to the LLM.
- `assign-import` endpoint to reassign an already-imported episode's tracked filename to a different episode without re-creating file records.
- Ten-pattern episode-number regex (`path_parser.py`), including bare `Title NN` filenames with bonus-content-marker guarding (`NCED`/`OP`/`SP`/etc.).

### SFTP scan redesign (issue #355)
- Scanning no longer recursively walks the entire remote library on every run. A shallow listing finds top-level directories; each directory is deep-walked and marked `ScannedDirectory` **once**, then skipped on every later scan. Cut scan time from ~14 minutes to seconds on a populated library.
- Directory-marking is gated on walk completeness — a partial walk (I/O failure, or files still mid-upload) is retried on the next scan rather than being permanently (and wrongly) marked known.
- `seed` task/SEEDED file status — one-time baseline that marks all pre-existing SFTP files as seeded so they're never mistaken for new downloads; also backfills `ScannedDirectory` rows so the first real scan after seeding doesn't re-walk everything.
- Bulk chunked existence checks replace an N+1 per-file query during scanning.

### Task observability
- Structured, append-only per-item event log (`on_event`) now emitted by every task — Scan, Download, and Match (issue #361) join Route and path-import, which already had it. Every file/directory processed produces an event, not just failures.
- Task list exposes `result_summary` and `dry_run`; Tasks page shows a live/replayable event log per task and a working **Max records** cap on the task list (previously the control updated the label but not the actual fetch).
- Scheduled auto-sync via Celery beat, with overlap guarding so a scheduled run never races a manually-triggered one.

### Dashboard, calendar, and library UX
- Dashboard "Recently Added" carousels for shows and episodes (sort by tracked-date or release date, filter by content type/genre), each independently toggleable from Settings.
- Airing calendar page (issue #220), toggleable from Settings.
- Adult-content visibility is a server-enforced setting, not a client filter — hidden rows never leave the API.
- Manual episode matching UI on the Files page (issue #46): **Fix Show** / **Fix Eps** actions, an inline episode picker, and a rematch flow (`begin-rematch`) for already-matched files.
- Files page pagination, filename search, and a raised list cap (1000) to support show-scoped file lookups.
- Show alias auto-generation from TMDB alternative titles plus optional LLM normalization, preserving user-added aliases (`POST /api/shows/{id}/aliases/regenerate`).
- Absolute/cour season-numbering mismatches resolved via TMDB `episode_groups` (#332).

### Infrastructure and security
- Static `X-API-Key` authentication, enforced at the router level, injected automatically by the nginx proxy for browser traffic.
- TMDB response cache centralized in Redis (shared across API and worker processes) with per-endpoint TTL overrides.
- Routed media can mount via a Docker CIFS volume driver instead of a Windows bind mount, as an opt-in override — not a hard dependency.
- Route-task duplicate-dispatch race fixed — concurrent route triggers no longer double-move the same file.
- LLM prompt-injection hygiene sweep across all LLM call sites (#329).
- All Alembic migrations squashed into a single `0001_initial` baseline; subsequent migrations (index on `episodes.air_date`, `scanned_directories` table) build on top of it.

### Internal refactors
- Celery worker harness eliminating per-task boilerplate; shared episode-resolution, LLM-JSON-parsing, and show-lookup services extracted out of the orchestrators that used to duplicate them; dead `MatchOrchestrator` removed; backend status/type enums surfaced in the OpenAPI schema so frontend types no longer need hand-widening.

## [0.1.0] — 2026-06-27

### Added

#### Core pipeline
- **SFTP scanning** — `scan` Celery task discovers media files on a remote SFTP server using `asyncssh`; incremental listing with glob filtering and skip logic for recently-modified files.
- **File download** — `download` Celery task transfers staged files from SFTP to `LOCAL_STAGING_PATH` with per-file progress callbacks streamed to the UI via WebSocket.
- **Filename parsing** — heuristic regex-based extraction of title, season, episode, year, and quality tags from raw filenames (`parse_orchestrator`).
- **Episode matching** — multi-stage match pipeline: LLM-assisted (OpenAI / Anthropic / Ollama / LM Studio) → heuristic regex → manual UI fallback. Matched-by source stored per file (`llm`, `heuristic`, `manual`).
- **File routing** — `route` Celery task moves matched files from staging to the correct library folder (`LOCAL_TV_PATH`, `LOCAL_ANIME_PATH`, `LOCAL_MOVIE_PATH`) based on `content_type`.
- **Full sync pipeline** — `sync` task chains scan → download → match → route in a single background operation.
- **`DownloadedFile` status FSM** — `discovered` → `downloading` → `downloaded` → (`unmatched` | `matched`) → `routing` → (`routed` | `error`).

#### Show management
- **TMDB integration** — search, trending, and full-detail endpoints backed by a rate-limited (0.5 req/s), cached (24 h TTL) `TMDBService`; in-flight deduplication across concurrent requests.
- **Show library** — add/view/edit/delete shows; `sys_name` auto-derived from title; `content_type` auto-inferred from TMDB genre and language metadata.
- **Episode sync** — `POST /shows/{id}/sync-episodes` pulls the latest episode list from TMDB; auto-invoked on show creation.
- **Show rematch** — re-links a show to a different TMDB entry; migrates tracked episode data by matching on `(season_number, episode_number)`; orphans unresolvable episodes to the DQ surface.
- **Show paths** — `PUT /shows/{id}/paths` sets the show's local filesystem path used for routing suggestions.
- **Show aliases** — `PUT /shows/{id}/aliases` manages alternate title lookups.
- **Show detail page** — episode list with `file_tracked` indicator per episode, backdrop image, TMDB metadata, and inline rematch modal.

#### Episode tracking
- `Episode.file_tracked`, `file_tracked_at`, `tracked_filename`, `tracked_source` — per-episode record of which local file confirms coverage and how it was matched.
- Tracking fields set automatically by the match pipeline, manual match endpoint, and orphan resolve endpoint.
- Tracking fields preserved when a show is re-matched (migrated to the new episode list where `(S, E)` aligns).

#### Data Quality surface
- **`OrphanedTrackingRecord` model** — persists episode tracking data that cannot be migrated during a show rematch because the `(season_number, episode_number)` pair has no equivalent in the new TMDB entry.
- Two orphan categories: `tracked_source="import"` (no `DownloadedFile`, tracking written directly to Episode on resolve) and `tracked_source="match"` (file exists, `downloaded_file_id` links to it, resolved by patching `episode_id`).
- **`GET /api/orphans`** — list all orphaned records with show title.
- **`GET /api/orphans/show/{show_id}`** — list orphans for a specific show.
- **`DELETE /api/orphans/{id}`** — dismiss without resolving.
- **`POST /api/orphans/{id}/resolve`** — resolve by linking to a target episode; validates same-show membership and non-tracked target.
- Per-show DQ amber badge on library cards (missing path, unset content type, no episodes, orphan records).
- Filterable Data Quality tab on the Shows page.
- `OrphanResolveModal` — UI for picking the correct episode from a show's episode list.
- Orphans auto-dismissed when `POST /files/{id}/match` confirms an episode, or when `PATCH /files/{id}` changes `show_id`.

#### Watchlist
- Per-show tracking with status (`planned`, `watching`, `completed`, `on_hold`, `dropped`) and optional notes.
- Drag-to-reorder using `dnd-kit`; `PATCH /watchlist/reorder` persists new positions atomically.
- Watchlist status displayed on show library cards.

#### Background task infrastructure
- `BackgroundTask` model tracks Celery task progress in PostgreSQL (`celery_task_id`, `task_type`, `status`, `progress_current`, `progress_total`, `progress_message`, `result_summary`, `dry_run`).
- Real-time progress streamed via WebSocket (`/ws`) using Redis PubSub; `ConnectionBadge` component shows live WebSocket state.
- Tasks page: list, filter, cancel, and re-trigger tasks.
- `dry_run` flag supported on all background tasks.

#### Import / Export
- **Text file import** — `POST /api/import/text` ingests a newline-delimited list of show titles with TMDB lookup and episode sync; background task with live progress.
- **Database export** — `POST /api/export/database` serialises the full library to a downloadable JSON file.
- **Database import** — `POST /api/import/database` restores or merges a previously exported JSON file.

#### Admin and observability
- **Dashboard** — pipeline status donut (files by status with colour coding), file ingestion bar chart (last 30 days), stat cards for total shows, tracked episodes, DQ issues, and active tasks.
- **`GET /api/admin/stats`** — aggregate counts including DQ totals.
- **`GET /api/admin/stats/files-timeline`** — daily file ingestion counts.
- **`GET /api/admin/stats/pipeline-status`** — file counts per pipeline status.
- **`GET /api/admin/cache`** — inspect TMDB response cache entries and hit rates.
- **`POST /api/admin/cache/flush`** — evict the in-memory TMDB cache.
- **`GET /api/admin/health`** — deep health check: DB connectivity, Redis PING, TMDB reachability, SFTP connectivity, LLM connectivity.

#### Settings / Configuration
- **Settings page** — displays non-sensitive runtime config; one-click connection tests for TMDB, SFTP, Redis, and LLM.
- **`GET /api/config`** — returns sanitised config (passwords redacted).
- **`POST /api/config/test/tmdb|sftp|redis|llm`** — live connectivity probes with latency reporting.

#### LLM service
- Multi-provider abstraction (`LLMService`) supporting OpenAI, Anthropic, Ollama, and LM Studio via a single interface.
- Response caching keyed on `(prompt, model, provider)` with configurable TTL.
- Graceful degradation: failures return `None` and log a warning; LLM unavailability never blocks the rest of the pipeline.

#### SFTP service
- `SFTPService` using `asyncssh` with retry logic (exponential backoff), concurrent batch download (`max_workers`), and per-file progress callbacks.
- File filtering: `is_valid_media_file`, `is_valid_directory`, `is_recently_modified` helpers.

#### Database migrations
- `0001` — initial schema: `shows`, `episodes`, `downloaded_files`, `background_tasks`, `watchlist_entries`.
- `0002` — add `file_tracked_at` to `episodes`.
- `0003` — add `tracked_filename` and `tracked_source` to `episodes`.
- `0004` — add `orphaned_tracking_records` table.

#### Developer experience
- CI pipeline (GitHub Actions): lint (`ruff`), format check, type check (`mypy` strict), security scan (`bandit`), test (`pytest`), frontend lint and build.
- `make.py` / `jidou-make` CLI for common dev tasks: `lint`, `format`, `types`, `security`, `test`, `check`, `clean`, `install`.
- `pre-commit` hooks mirror CI checks locally.
- Test suite of 384+ Python tests with ≥85% coverage, using `AsyncMock` session fixtures and no real database dependency in unit tests.
