# Architecture

Design decisions, system structure, and the reasoning behind key choices in Jidou.

---

## System overview

```
┌─────────────────┐   HTTP/WS    ┌─────────────────────────────────────┐
│  React Frontend │ ──────────── │  FastAPI (port 8192)                │
│  (Nginx :3100)  │              │  ├── /api/shows   /api/files        │
└─────────────────┘              │  ├── /api/watchlist  /api/tasks     │
                                 │  ├── /api/admin  /api/config        │
                                 │  ├── /api/import  /api/export       │
                                 │  ├── /api/images  (unauthenticated) │
                                 │  └── /ws  (WebSocket)               │
                                 └────────────┬────────────────────────┘
                                              │
                         ┌────────────────────┼──────────────────┐
                         │                    │                  │
                   ┌─────▼──────┐    ┌────────▼───────┐   ┌──────▼──────┐
                   │ PostgreSQL │    │  Redis         │   │ Celery      │
                   │ (models,   │    │  (broker,      │   │ Worker      │
                   │  history)  │    │   cache,       │   │ (scan,      │
                   └────────────┘    │   rate limiter,│   │  download,  │
                                     │   PubSub)      │   │  match,     │
                                     └────────────────┘   │  route,     │
                                                          │  sync,      │
                                                          │  import)    │
                                                          └─────────────┘
```

**Key constraints:**
- The API runs on port **8192** (not 8000, which conflicts with common local dev servers).
- The frontend never calls TMDB directly — all external API traffic is proxied through the backend where rate limiting is enforced.
- Redis serves three roles: Celery message broker, TMDB response cache, and the token bucket for rate limiting.

---

## Layer separation

Jidou follows a strict four-layer architecture:

### 1. Models (`src/jidou/models/`)
SQLAlchemy ORM models defining the database schema. No business logic — only column definitions, relationships, and enums.

### 2. Services (`src/jidou/services/`)
Stateless clients for external systems: TMDB API, SFTP server, LLM providers, Redis rate limiter, task progress tracking. Each service is a class with a clear interface; the concrete implementation is injected at construction time.

Services are intentionally narrow. `TMDBService` only knows how to call TMDB; it does not know about shows or episodes. `SFTPService` only knows how to list and download files; it does not know about the database.

### 3. Orchestrators (`src/jidou/orchestrators/`)
Multi-step workflows that coordinate multiple services and models. An orchestrator is the only layer that holds workflow logic: sequencing, error handling, dry-run enforcement, and logging.

For example, `ParseOrchestrator` fetches DOWNLOADED files from the database, extracts show name/season/episode via a regex heuristic and optionally `LLMService`, looks up the matching show and episode, then writes the match result back to the database. It doesn't care how TMDB works and doesn't call SFTP.

### 4. Routes (`src/jidou/api/routes/`)
Thin FastAPI handlers. Each handler:
1. Validates the request (via Pydantic schemas).
2. Opens a database session (via `Depends(get_session)`).
3. Delegates to an orchestrator or service.
4. Returns a response (via Pydantic response models).

Route handlers contain no business logic. If a handler is more than ~30 lines, the logic belongs in an orchestrator.

---

## Background task design

Celery tasks in `src/jidou/workers/` are intentionally thin: they receive a task ID, mark the task as running, delegate to an orchestrator, then mark the task as completed or failed. All logic lives in the orchestrator.

A shared harness, `run_task_workflow()` (`src/jidou/workers/_harness.py`), wraps every task's `_work` closure with two callbacks: `on_progress` (current/total/message) and `on_event` (level/message/context). Orchestrators call `on_event` for every item they process — success, skip, or failure — not just for errors; every orchestrator (Scan, Download, Match/Parse, Route, path-import) follows the same internal pattern: an `_emit()` closure that wraps the callback in a try/except so a logging failure can never break the task itself.

Progress and events are written to the `background_tasks` table (`event_log` is an append-only JSONB column) by the orchestrators, and then published to a Redis PubSub channel. The FastAPI WebSocket handler subscribes to that channel and forwards events to connected browser clients.

This means:
- The API and worker can be on different machines (they share only the database and Redis).
- Progress is not lost if a browser disconnects — the event log is stored in the database and replayed on reconnect.

**Time limits are sized per task, not one blanket default.** Most Celery tasks inherit the app-wide 50-minute soft / 60-minute hard `SoftTimeLimitExceeded` limit, which is fine for a single-phase task. Multi-phase tasks that chain several I/O- or LLM-bound stages together — `sync_all_task` (scan → download → match → route) and `path_import_task` — get an explicit 6h soft / 7h hard override instead, since a real backlog routinely exceeds the default window well before it's actually stuck.

---

## SFTP scan design — shallow listing plus lazy deep walk

`ScanOrchestrator` does **not** recursively walk the entire remote library on every run. This was a deliberate redesign (issue #355) after profiling showed a full recursive walk taking minutes on a populated library, most of it re-listing directories that hadn't changed since the last scan.

Instead, each scan run:
1. Shallow-lists only the immediate children of each configured remote path (`SFTPService.list_remote_children`) — one round trip, no recursion.
2. Checks new top-level files directly against `DownloadedFile.remote_path` (batched, not per-file).
3. Checks top-level directories against the `ScannedDirectory` table. A directory already marked known is **never listed into again** — no SFTP round trip at all.
4. A genuinely new directory gets one full recursive deep-walk (`list_remote_files_recursive`), bounded by `asyncio.Semaphore(SFTP_MAX_WORKERS)` for concurrency across multiple new directories in the same run.

**Why marking is conditional, not automatic:** a deep walk that hit an I/O failure partway through, or skipped files still inside the 60-second upload grace window, must not be marked as a fully-known directory — doing so would permanently lose those files. `list_remote_files_recursive` reports `fully_walked` alongside the file list; the `ScannedDirectory` row is only inserted when that's `True`. A partial walk is simply retried on the next scan.

**Why this is safe for Jidou's domain:** SFTP sources in this context are wide, flat, and single-use — each remote directory is populated once and never appended to afterward. A directory known once can be treated as permanently immutable. `SeedOrchestrator` (the one-time baseline task) backfills `ScannedDirectory` rows for pre-existing directories, including ones with zero eligible media files, so the first real scan after seeding starts fast rather than re-walking the whole library once more.

This is a scan-layer-only optimization — it has no relationship to show/episode matching, and doesn't change what a file's `DownloadedFile` record looks like once discovered.

---

## Filesystem paths with non-UTF-8 bytes

Some filenames — and occasionally directory names — on a POSIX filesystem aren't valid UTF-8. The most common real-world cause is a legacy Latin-1/cp1252-named file from an older Windows/NAS-authored library: cp1252 `é` is the single byte `0xE9`, while UTF-8 `é` is the two bytes `0xC3 0xA9`. Python decodes such bytes via the `surrogateescape` error handler, producing lone surrogate codepoints that raise `UnicodeEncodeError` the instant anything tries to encode them as UTF-8 — a JSON response, a database write.

This surfaces specifically in the [Scan Local Files](features.md#episode-matching) feature, which walks a live filesystem via `Path.rglob()`, unlike the rest of the app which mostly deals in DB-stored, already-clean strings.

- **`services/path_transport.py`** (`encode_path_bytes`/`decode_path_bytes`) percent-encodes only the genuinely non-UTF-8 byte(s), plus any literal `%` so decoding stays unambiguous — every other character, including ordinary non-ASCII Unicode (accented letters, CJK, emoji), passes through unchanged. This is what lets a byte-exact path survive a JSON API round trip (scan response → frontend → `link-file` confirm request) so the file can still be located on disk afterward.
- **Display vs. round-trip are different concerns.** The percent-encoded form is exact but not human-readable (`Fianc%E9`). A separate `decode_path_bytes_for_display` tries `cp1252` as a fallback before giving up to `U+FFFD` — recovering the actual accented character for the overwhelmingly common real case, rather than showing either raw percent-encoding or a placeholder. Fields that get echoed back to the server for a lookup (e.g. `Episode.tracked_filename`, used by `assign-import`) store the byte-exact encoded form; a parallel `_display` field is what the UI actually renders.
- **A show's own directory can have the same problem.** `_resolve_show_root` (`services/path_parser.py`) falls back to scanning the parent directory for an entry whose raw bytes decode as cp1252 to the expected name, when a literal `Path(local_path).is_dir()` check on the clean UTF-8 string fails.

---

## TMDB rate limiting

TMDB rate limits are enforced globally using a Redis token bucket (`services/rate_limiter.py`). The bucket is shared across all worker processes and API processes, so adding more workers does not multiply TMDB traffic.

The default limit is `0.5` req/sec (configurable via `TMDB_RATE_LIMIT_PER_SECOND`). TMDB metadata responses are cached in Redis for 7 days (`TMDB_CACHE_TTL`, up from an original 24h once the cache moved to Redis and became shared/durable across processes — show/episode data changes rarely, and large imports can span many hours) to further reduce API calls.

**Why global rate limiting matters:** Without it, running 4 Celery workers each at 0.5 req/sec would produce 2 req/sec — enough to trigger TMDB's per-IP limit and get the account blocked.

**Images get their own, separate bucket.** `image.tmdb.org` (posters/backdrops) is a different host from `api.themoviedb.org` (metadata), with much looser practical limits — CDN image fetches don't risk the same account-level block metadata calls do. Sharing one bucket meant poster loading queued up behind an in-progress sync. `services/rate_limiter.py` exposes a second instance, `image_rate_limiter`, at `IMAGE_RATE_LIMIT_PER_SECOND` (default `5.0`), used only by `api/routes/images.py`.

---

## Image caching

Frontend components never link to `image.tmdb.org` directly — every poster/backdrop loads through `GET /api/images/{size}/{filename}`, which fetches from TMDB on a miss and caches the bytes to disk for every request after that.

- **Backend abstraction:** storage sits behind an `ImageCacheBackend` protocol; `DiskImageCacheBackend` is the only implementation today, selected via a factory reading `IMAGE_CACHE_BACKEND`. A future self-hosted S3-compatible backend is a drop-in swap without touching the route handler.
- **Unauthenticated by design:** this route is registered without the `X-API-Key` dependency, alongside `/api/health` — a plain `<img src>` tag can't send custom headers, and TMDB images aren't sensitive data.
- **In-flight deduplication:** concurrent requests for the same never-cached image share one upstream fetch rather than each independently fetching and writing the same bytes — the same "waiter waits on the owner's event, falls through to its own attempt if the owner failed" shape `TMDBService._request` already uses for metadata calls.
- **Retention:** a daily Celery beat task purges cached files past `IMAGE_CACHE_RETENTION_DAYS` (default 180), gated by `IMAGE_CACHE_EXPIRATION_ENABLED` so retention can be disabled to keep images indefinitely.

---

## Authentication design

Authentication uses a static API key passed in the `X-API-Key` HTTP header. The key is validated in a single FastAPI dependency (`api/dependencies.py:verify_api_key`) which is applied at the router level.

When `JIDOU_API_KEY` is not set, the dependency is a no-op — all requests are accepted. This makes the system safe for isolated local deployments without any configuration.

**Why not JWT?** Jidou has one user (the operator). JWT tokens, refresh flows, and user management would be significant complexity for no benefit. A static key is simpler to audit, rotate, and configure.

**Browser security:** The API key is never sent to the browser. The nginx reverse proxy reads `JIDOU_API_KEY` from its container environment at startup and injects `X-API-Key` on every proxied request. The key is substituted into the nginx config using `envsubst` at container start time, scoped to only that one variable so nginx built-ins like `$host` are untouched.

---

## Frontend architecture

The React frontend is a single-page application built with Vite + TypeScript. It communicates with the backend exclusively through the nginx reverse proxy — there are no direct connections to the FastAPI server or to external services.

### Data fetching

All server state is managed by [TanStack Query](https://tanstack.com/query). This provides:
- Automatic caching and deduplication of identical requests.
- Background refetching when the window regains focus.
- Optimistic updates for mutations.

### Real-time updates

A single WebSocket connection (managed in `stores/websocket.ts`) receives task progress events. Components subscribe to specific task IDs via a custom hook; unrelated events are ignored.

### TypeScript types

API types in `frontend/src/types/api.ts` are generated from the FastAPI OpenAPI spec via `make.py generate-types`. They are not hand-written. This keeps the frontend in sync with the backend schema automatically.

### Shared UI primitives

`frontend/src/components/ui/` holds the app's style primitives — `Modal`, `Button`, `Card`, `Badge` — backed by `@layer components` recipes in `index.css` (`.overlay`, `.panel-light`, `.panel-dark`, `.card`, `.btn`, `.badge`). Every modal, card wrapper, and badge-style pill in the app is built from these rather than a hand-typed Tailwind utility string at each call site, which had drifted visibly before this existed (mismatched overlay opacity, z-index, button colors for the same semantic action across different modals). `Modal` also wires up `useFocusTrap` internally, so every modal built on it gets focus-trap + Escape-to-close for free.

---

## Database design

Jidou uses PostgreSQL 16 with SQLAlchemy 2 (async) and Alembic for migrations.

### Key tables

| Table | Description |
|-------|-------------|
| `shows` | Show metadata, TMDB ID, content type, local path, aliases (JSONB) |
| `episodes` | Episode metadata + file tracking fields (`file_tracked`, `tracked_filename`, etc.) |
| `downloaded_files` | File records with status, parsed metadata, and show/episode FK |
| `background_tasks` | Task records with progress, event log (JSONB), and completion metadata |
| `watchlist` | Per-show viewing status and notes |
| `orphaned_tracking_records` | Episodes whose tracking data was orphaned by a show rematch |

### Design choices

- **Episode tracking lives on the episode model** — `file_tracked`, `tracked_filename`, and `tracked_source` are columns on `episodes`, not on `downloaded_files`. This makes it trivial to query "which episodes does this show have files for" without joining to files.
- **Aliases are JSONB** — show aliases are stored as a JSONB array rather than a separate table. They're queried rarely and never joined, so the simplicity of a single column wins over normalisation.
- **JSONB event log** — each `BackgroundTask` has an `event_log` JSONB column that accumulates structured events during the task's lifetime. This avoids a separate event table and makes replay straightforward.
- **Async everywhere** — all database access uses `AsyncSession` from SQLAlchemy 2. There are no synchronous DB calls in the application.
- **Per-item `SAVEPOINT`s, not session-wide rollback, inside a loop.** A loop that processes many already-loaded ORM objects (e.g. `TMDBOrchestrator.sync_all_shows()` iterating every show) must not call a plain `session.rollback()` after one item's failure — that expires every object in the session's identity map, including every other still-pending item in the same loop. The next iteration's bare attribute access then triggers an implicit lazy-reload outside the async greenlet bridge, raising `MissingGreenlet` instead of just skipping the failed item. Wrapping each item's work in `session.begin_nested()` (a `SAVEPOINT`) scopes a rollback to only that item's changes, leaving the rest of the loop's already-loaded objects usable.

---

## Modular monolith

Jidou is structured as a modular monolith rather than microservices. All components — API, workers, services, orchestrators — share a single codebase and Python package. The deployment is split into separate containers (API + worker) purely for process isolation and resource allocation, not for independent deployability.

**Why not microservices?** The domain is small and tightly coupled. Separating the TMDB service or the match logic into independent deployables would add network overhead, serialisation complexity, and operational burden with no benefit at this scale. If the project grows, the clean service boundaries make extraction straightforward.
