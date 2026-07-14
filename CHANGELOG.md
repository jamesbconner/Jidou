# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

Everything below shipped after 0.1.0 and has not been tagged yet. Grouped by area rather than by commit — see `git log` for individual changes.

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
