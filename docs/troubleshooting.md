# Troubleshooting

Common operational failures with diagnosis steps and resolutions.

---

## Files stuck in `unmatched` status

**Symptoms:** The Files page shows files with `unmatched` status after the match task completes. The show exists in your library.

**Root causes:**
- The parsed show name extracted from the filename doesn't match any show title or alias in the database.
- No LLM is configured (`LLM_PROVIDER=none`) and the heuristic regex couldn't extract a season/episode number.
- The LLM was called but returned `UNKNOWN` because the filename is ambiguous or the show title is very different from the filename.

**Resolution:**
1. Open the Files page, find the unmatched file, and click **Resolve** to manually pick the show and episode via the TMDB search modal.
2. If the same show repeatedly fails to match, add an alias to the show: go to Show Detail → Edit Aliases and add the name the filenames use (e.g. `Attack on Titan` when the show is stored as `Shingeki no Kyojin`).
3. If you want automatic matching, configure an LLM provider in `.env`:
   ```env
   LLM_PROVIDER=ollama
   LLM_BASE_URL=http://host.docker.internal:11434
   LLM_MODEL=llama3
   ```
   Then re-run the match task from the Tasks page.

**Prevention:** Keep show aliases up to date. The more aliases a show has, the broader the heuristic net.

---

## Parse cycle not detecting new SFTP files

**Symptoms:** You know new files exist on the remote server, but after running `scan` no new records appear.

**Root causes:**
- The SFTP connection is failing silently (credentials, host key, firewall).
- The file's `remote_path` already exists in the database — the scan deduplicates by path, so re-appearing files are not re-created.
- `SFTP_REMOTE_PATHS` doesn't include the directory the new files are in.

**Diagnosis:**
```bash
# Check API logs for SFTP errors
docker compose logs jidou-api --tail=100

# Test connectivity from the Settings page or via API
curl -X POST http://localhost:8192/api/config/test/sftp
```

**Resolution:**
1. Verify SFTP credentials in `.env` and test via the Settings page connectivity test.
2. Check `SFTP_REMOTE_PATHS` includes the correct remote directories (comma-separated).
3. If a file was previously deleted from the database but still exists remotely, it will be re-discovered on the next scan — no action needed.
4. For a host-key mismatch, connect manually once via `ssh user@host` on the Docker host to accept the host key, or configure `SFTP_KNOWN_HOSTS_PATH`.

**Prevention:** Run the SFTP connectivity test from the Settings page after any credential or network change.

<!-- screenshot: settings-connectivity-fail -->

---

## Celery tasks not being processed

**Symptoms:** You trigger a task from the UI or API and it stays in `pending` indefinitely. The task counter shows active = 0.

**Root causes:**
- The Celery worker container is not running.
- The Redis broker is unreachable (worker can't pick up tasks).
- A previous worker process crashed and left a task locked.

**Diagnosis:**
```bash
# Check all container status
docker compose ps

# Check worker logs
docker compose logs jidou-worker --tail=50

# Verify Redis is up
docker compose exec redis redis-cli ping
```

**Resolution:**
1. If the worker is stopped: `docker compose up -d jidou-worker`.
2. If Redis is down: `docker compose up -d redis` — the worker reconnects automatically once Redis is available.
3. If a task is permanently stuck in `running` after a worker crash, cancel it via the UI (Tasks page → Cancel) or `DELETE /api/tasks/{id}`, then re-trigger.
4. To restart the worker cleanly: `docker compose restart jidou-worker`.

**Prevention:** The worker container has `restart: unless-stopped` in `docker-compose.yml` so it recovers from crashes automatically. Ensure Docker itself is configured to start on system boot.

---

## Database migration failed

**Symptoms:** `alembic upgrade head` exits with an error mid-way, or the API fails to start with a missing column / table error.

**Root causes:**
- The database was not reachable when the migration ran.
- A migration script has a bug or depends on data that doesn't exist.
- A partial migration left the schema in an inconsistent state.

**Resolution:**
```bash
# Check the current migration state
docker compose exec jidou-api alembic current

# Roll back the failed migration
docker compose exec jidou-api alembic downgrade -1

# Fix the migration script if needed, then re-apply
docker compose exec jidou-api alembic upgrade head
```

If the schema is badly corrupted and the data is expendable:
```bash
# Nuclear option — drops all data (see "Wiping the database" below)
docker compose down -v
docker compose up -d postgres redis
docker compose exec jidou-api alembic upgrade head
```

**Prevention:** Always test migrations on a staging environment before applying to production data. Use `alembic upgrade head --sql` to preview the SQL before executing.

---

## Resetting a show's tracking state

**Symptoms:** Episode tracking data is wrong for a show (e.g. after a show rematch to a different TMDB entry) and you want to re-run matching from scratch.

**Resolution — per file (UI):**
1. Open the Files page, filter by the show.
2. For each `matched` or `routed` file, open the Resolve modal and click **Reset for auto re-match**. This sets the file back to `downloaded` and clears the episode link.
3. Re-run the match task from the Tasks page.

**Resolution — per file (API):**
```bash
# Reset a specific file to downloaded (replace 42 with the file ID)
curl -X PATCH http://localhost:8192/api/files/42 \
  -H 'Content-Type: application/json' \
  -d '{"status": "downloaded", "episode_id": null}'
```

**Resolution — full show reset:**
```bash
# Get all matched/routed files for a show (replace show_id=7)
curl "http://localhost:8192/api/files?show_id=7&limit=1000"
# PATCH each file to status=downloaded, episode_id=null
```

**Prevention:** Before rematching a show to a new TMDB entry, review the orphaned tracking records surface on the Data Quality tab — it shows which files will need re-resolution.

---

## TMDB rate limiting (429 errors)

**Symptoms:** API logs contain `429 Too Many Requests` from TMDB. Show syncs or episode lookups fail or are very slow.

**Root causes:**
- `TMDB_RATE_LIMIT_PER_SECOND` is set too high for your account.
- The Redis-backed rate limiter is not running (rate limiting is bypassed, leading to bursts).
- A bulk operation (e.g. adding many shows at once) exhausted the token bucket.

**Diagnosis:**
```bash
# Check Redis is up (rate limiter requires Redis)
docker compose exec redis redis-cli ping

# Check current rate limit config
curl http://localhost:8192/api/config
```

**Resolution:**
1. Reduce the rate limit in `.env`: `TMDB_RATE_LIMIT_PER_SECOND=0.2` (one call every 5 seconds) and restart the API.
2. Ensure Redis is running — without it the rate limiter fails open and requests are not throttled.
3. Wait for TMDB's rate limit window to reset (typically 10–30 seconds), then retry.
4. For bulk show imports, spread them across multiple sync cycles rather than adding everything at once.

**Prevention:** The default of `0.5` req/sec (one call every 2 seconds) is well within TMDB's limits. Do not increase this value above `1.0` without monitoring for 429 responses.

---

## Wiping and reinitializing the database

**When to use:** You want a clean slate — all show, episode, file, and task records deleted.

```bash
# Stop all services and remove the postgres volume
docker compose down -v

# Restart infrastructure
docker compose up -d postgres redis

# Run migrations to recreate the schema
docker compose exec jidou-api alembic upgrade head

# (Optional) seed sample shows
uv run python make.py seed
```

> **Warning:** `-v` removes all named volumes including `postgres_data`. This is irreversible. Back up your data first using `GET /api/export/database`.

**Back up before wiping:**
```bash
curl http://localhost:8192/api/export/database -o jidou-backup.yaml
```

**Restore after reinitializing:**
```bash
curl -X POST http://localhost:8192/api/import/database \
  -F "file=@jidou-backup.yaml"
```

---

## Re-resolving a mis-matched file

**Symptoms:** A file was matched to the wrong show or the wrong episode, and it may already be `routed`.

**Resolution — via UI:**
1. Go to the Files page and find the file.
2. Click **Resolve** to open the match modal.
3. Search for the correct show, select the correct episode, and confirm.

**Resolution — via API:**
```bash
# Reassign to correct show and episode (get the IDs from /api/shows and /api/shows/{id}/episodes)
curl -X PATCH http://localhost:8192/api/files/42 \
  -H 'Content-Type: application/json' \
  -d '{"show_id": 3, "episode_id": 117, "status": "matched"}'
```

If the file is already `routed` (physically moved), the API patch corrects the database record but does not move the file back. Move the file on disk manually if needed, then update `local_path` via PATCH.

**Prevention:** Review the Files page after each match cycle and resolve any `unmatched` files promptly before routing.

---

## API health check failing on startup

**Symptoms:** `GET /api/admin/health` returns errors or the API container fails to start. The frontend shows a connection error.

**Root causes:**
- PostgreSQL is not ready when the API starts (race condition on first boot).
- Alembic migrations have not been run; the schema is missing tables.
- A required environment variable (`TMDB_API_KEY`, `DATABASE_URL`) is not set.

**Diagnosis:**
```bash
# Check API startup logs
docker compose logs jidou-api --tail=50

# Run the health endpoint
curl http://localhost:8192/api/admin/health
```

**Resolution:**
1. If Postgres is not ready: wait 10–20 seconds and try again. The `docker-entrypoint.sh` script retries Alembic on startup, but if the DB is very slow the API may start before migrations finish.
2. Run migrations explicitly: `docker compose exec jidou-api alembic upgrade head`.
3. Verify all required variables are present: `docker compose exec jidou-api env | grep -E 'TMDB|DATABASE|REDIS'`.

**Prevention:** Use `depends_on` with a `healthcheck` condition (already configured in `docker-compose.yml`) to ensure Postgres is accepting connections before the API starts.

---

## Docker Compose won't start (port conflicts, volume issues)

**Symptoms:** `docker compose up` fails immediately with a port-in-use error or volume mount error.

**Port conflicts:**

| Service | Default port | Variable |
|---------|-------------|----------|
| Frontend (nginx) | 3100 | `FRONTEND_PORT` |
| API | 8192 | `API_PORT` |
| PostgreSQL | 5432 | `POSTGRES_PORT` |
| Redis | 6379 | `REDIS_PORT` |

```bash
# Find what's using a port (Windows)
netstat -ano | findstr :8192

# Override a conflicting port in .env
FRONTEND_PORT=3200
API_PORT=8300
```

**Volume mount errors (Windows):**
- Ensure Docker Desktop has access to the drive letters used in `LOCAL_*_HOST_PATH` (Docker Desktop → Settings → Resources → File sharing).
- On Windows, host paths in `.env` must use drive-letter format: `D:\media\staging` (not `/mnt/d/media/staging`).
- The container path (`LOCAL_*_PATH`) must always be a Linux path: `/data/staging`.

**"volume already exists" after a failed first boot:**
```bash
docker compose down -v   # remove stale volumes
docker compose up -d     # start fresh
```
