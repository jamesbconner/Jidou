# API Reference

Jidou exposes a REST API at `http://localhost:8192` and a WebSocket endpoint for real-time progress.

Interactive documentation (Swagger UI) is available at `/docs`. The OpenAPI spec is at `/openapi.json`.

---

## Authentication

When `JIDOU_API_KEY` is set in `.env`, all `/api` endpoints require the header:

```
X-API-Key: your_key
```

When the key is unset or empty, authentication is disabled. The Docker Compose nginx proxy injects the header automatically for browser traffic — only direct API consumers (curl, scripts, CI) need to add it manually.

---

## Health & Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness check — returns `{"status": "ok"}` |
| GET | `/api/admin/health` | Deep health check (DB, Redis, TMDB, LLM connectivity) |
| GET | `/api/admin/stats` | Row counts and DQ totals |
| GET | `/api/admin/stats/files-timeline` | Files added per day (last 30 days) |
| GET | `/api/admin/stats/pipeline-status` | File counts by status |
| GET | `/api/admin/cache` | Inspect TMDB response cache entries |
| POST | `/api/admin/cache/flush` | Clear the TMDB response cache (Redis-backed, shared across API and worker processes) |

---

## Dashboard

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/dashboard/recent-shows` | Recently added shows for the dashboard carousel; filter by `content_type`/`genre`, sort by `tracked` or `release` |
| GET | `/api/dashboard/recent-episodes` | Recently tracked episodes for the dashboard carousel; same filters/sort |
| GET | `/api/dashboard/genres` | Distinct TMDB genre names across the library, for the genre filter dropdown |

Adult-flagged shows/episodes are excluded from both carousels unless the `show_adult_content` setting is enabled — this is enforced server-side in SQL, not a client-side filter.

## Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Current value of every app setting (`show_adult_content`, `calendar_enabled`, `recent_episodes_enabled`) |
| PATCH | `/api/settings` | Update one or more settings |

---

## Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config` | View current config (secrets redacted) |
| POST | `/api/config/test/tmdb` | Test TMDB API key |
| POST | `/api/config/test/sftp` | Test SFTP connectivity |
| POST | `/api/config/test/redis` | Test Redis connectivity |
| POST | `/api/config/test/llm` | Test LLM provider connectivity |

---

## Shows

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/shows` | List tracked shows |
| POST | `/api/shows` | Add a show from TMDB; auto-infers content type and syncs episodes |
| GET | `/api/shows/{id}` | Get show detail |
| PATCH | `/api/shows/{id}` | Update user-managed fields (`content_type`, `local_path`, etc.) |
| PUT | `/api/shows/{id}/paths` | Set local filesystem path |
| PUT | `/api/shows/{id}/aliases` | Replace show aliases list |
| DELETE | `/api/shows/{id}` | Remove show and all its data |
| GET | `/api/shows/trending` | Trending TV or movie results from TMDB |
| GET | `/api/shows/search` | Search TMDB by title |
| GET | `/api/shows/tmdb/{tmdb_id}` | Fetch TMDB detail for a specific ID |
| POST | `/api/shows/{id}/rematch` | Re-link show to a different TMDB entry |
| POST | `/api/shows/{id}/sync-episodes` | Sync episode metadata from TMDB |
| POST | `/api/shows/{id}/aliases/regenerate` | Rebuild TMDB + LLM alias sources; preserves user-added aliases |
| POST | `/api/shows/{id}/rss-stub` | Link (or create) an RSS subscription for this show |
| GET | `/api/shows/calendar` | Episodes airing in a date range, across all shows, with computed `tracked`/`missing`/`upcoming` status |
| GET | `/api/shows/{id}/episodes` | List episodes for a show |
| POST | `/api/shows/{show_id}/episodes/{episode_id}/begin-rematch` | Prepare a tracked episode's backing file for re-matching (download-backed episodes only) |
| POST | `/api/shows/{show_id}/episodes/{episode_id}/assign-import` | Reassign a path-imported episode's tracked filename to a different episode, atomically |

**Query parameters for `GET /api/shows`:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `sort` | string | `title_asc`, `title_desc`, `created_asc`, `created_desc` |
| `content_type` | string | Filter by `tv`, `anime`, `movie` |
| `limit` | int | Max results (default 100) |

---

## Files

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/files` | List files with optional filters |
| GET | `/api/files/unmatched` | List `unmatched` files awaiting manual review |
| GET | `/api/files/{id}` | Get a single file record |
| GET | `/api/files/{id}/tmdb-suggestions` | TMDB search results seeded from the file's `parsed_show_name`, for the Resolve modal |
| PATCH | `/api/files/{id}` | Correct `show_id`, `episode_id`, `status`, or `error_message` |
| POST | `/api/files/{id}/match` | Manually assign a show; runs heuristic S/E detection |

**Query parameters for `GET /api/files`:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by `FileStatus` value |
| `show_id` | int | Filter by show |
| `search` | string | Substring match on `original_filename` |
| `limit` | int | Max results (1–1000, default 50) |
| `offset` | int | Pagination offset |

**Response headers:** `X-Total-Count` contains the total matching record count for pagination.

---

## Data Quality — Orphaned Tracking Records

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/orphans` | List all orphaned tracking records |
| GET | `/api/orphans/show/{show_id}` | List orphans for a specific show |
| DELETE | `/api/orphans/{id}` | Dismiss without resolving |
| POST | `/api/orphans/{id}/resolve` | Resolve by linking to a specific episode |

**Resolve request body:**
```json
{ "episode_id": 42 }
```

---

## Watchlist

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | List entries |
| POST | `/api/watchlist` | Add show to watchlist (idempotent) |
| GET | `/api/watchlist/{id}` | Get entry |
| PATCH | `/api/watchlist/{id}` | Update `status`, `notes`, or `position` |
| DELETE | `/api/watchlist/{id}` | Remove entry |
| PATCH | `/api/watchlist/reorder` | Bulk-update positions after drag-to-reorder |

**Watchlist status values:** `planned`, `watching`, `completed`, `on_hold`, `dropped`

---

## Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks` | List background tasks |
| GET | `/api/tasks/{id}` | Get task status and progress |
| GET | `/api/tasks/count` | Count of tasks by status |
| GET | `/api/tasks/active` | List currently running tasks |
| POST | `/api/tasks/trigger` | Launch a background task |
| DELETE | `/api/tasks/{id}` | Cancel a running task |

**Trigger request body:**
```json
{
  "task_type": "sync",
  "dry_run": false
}
```

**Task types:** `scan`, `download`, `match`, `route`, `sync`, `seed`, `import`, `db_import`, `rss_import`, `rss_publish`

All task types support `dry_run: true` — validation and planning runs but no files are moved and no tracking data is written. `seed` is triggered from the Settings page, not the Tasks trigger panel.

Every task type streams a structured, append-only `event_log` — one entry per file/directory processed, not just failures or a final summary — viewable live on the Tasks page and replayed from `GET /api/tasks/{id}` after the fact.

---

## Import / Export

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/import/text` | Import shows from a newline-delimited path list |
| POST | `/api/import/database` | Restore library from an exported YAML file |
| GET | `/api/export/database` | Export full library to YAML |

**Path import request:**
```
POST /api/import/text
Content-Type: text/plain

/data/media/tv/Breaking Bad
/data/media/anime/Attack on Titan
```

**Database export:**
```bash
curl http://localhost:8192/api/export/database -o backup.yaml
```

---

## RSS

Jidou models a YaRSS2 config as **feeds** (the RSS source URL, e.g. a Nyaa or tracker feed) and **subscriptions** (a filtered link between a feed and a show). Both are separate resources with independent CRUD.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/rss/feeds` | List RSS feeds |
| POST | `/api/rss/feeds` | Create a feed |
| PATCH | `/api/rss/feeds/{id}` | Update a feed |
| DELETE | `/api/rss/feeds/{id}` | Delete a feed |
| GET | `/api/rss/subscriptions` | List subscriptions, with optional filters |
| POST | `/api/rss/subscriptions` | Create a subscription (feed + show + optional include/exclude regex) |
| GET | `/api/rss/subscriptions/{id}` | Get a single subscription |
| PATCH | `/api/rss/subscriptions/{id}` | Update a subscription |
| PATCH | `/api/rss/subscriptions/bulk` | Apply active-flag changes to multiple subscriptions in one transaction |
| DELETE | `/api/rss/subscriptions/{id}` | Delete a subscription |
| GET | `/api/rss/subscriptions/recommendations` | Health-check recommendations (e.g. stale/unlinked subscriptions) |
| POST | `/api/rss/subscriptions/{id}/suggest-regex` | LLM-assisted include/exclude regex suggestion |
| GET | `/api/rss/subscriptions/{id}/preview` | Preview the YaRSS2 dict Jidou would publish for one subscription |
| GET | `/api/rss/download` | Compose and download the current DB state as a YaRSS2 config file |
| GET | `/api/rss/snapshots` | List recent published config snapshots, most recent first |
| GET | `/api/rss/snapshots/{id}` | Get one snapshot including its full raw content |
| POST | `/api/rss/import` | Background task: download the remote YaRSS2 config and reconcile it into the DB |
| POST | `/api/rss/publish` | Background task: compose the DB state and upload it to the remote YaRSS2 config (optionally stopping/restarting Deluge around the upload) |

---

## WebSocket

```
ws://localhost:8192/ws
```

The WebSocket connection receives progress events for all running tasks. Each message is a JSON object:

```json
{
  "task_id": 42,
  "task_type": "sync",
  "status": "running",
  "progress_current": 12,
  "progress_total": 50,
  "progress_message": "Matching: show.s01e03.mkv",
  "event_log": [...]
}
```

The frontend connects automatically on page load and reconnects with exponential backoff on disconnection.
