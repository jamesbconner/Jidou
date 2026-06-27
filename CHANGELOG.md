# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Initial project skeleton with Python 3.13, hatchling, ruff, mypy, pytest, and uv tooling.

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
