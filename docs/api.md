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
| POST | `/api/admin/cache/flush` | Clear in-memory TMDB cache |

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
| GET | `/api/shows/{id}/episodes` | List episodes for a show |

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

**Task types:** `scan`, `download`, `match`, `route`, `sync`

All task types support `dry_run: true` — validation and planning runs but no files are moved and no tracking data is written.

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

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/rss/subscriptions` | List RSS subscriptions |
| POST | `/api/rss/subscriptions` | Create a subscription |
| PATCH | `/api/rss/subscriptions/{id}` | Update a subscription |
| DELETE | `/api/rss/subscriptions/{id}` | Delete a subscription |
| POST | `/api/rss/sync` | Push current subscriptions to the remote RSS config file |
| POST | `/api/rss/suggest-regex` | LLM-assisted regex suggestion for a show name |

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
