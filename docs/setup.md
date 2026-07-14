# Setup

Full installation guide covering Docker, bare-metal, environment variables, SFTP, TMDB, and API authentication.

---

## Docker (recommended)

### Prerequisites

- Docker Desktop ≥ 4.x (Windows/macOS) or Docker Engine + Compose plugin (Linux)
- A TMDB API key — register at https://www.themoviedb.org/settings/api (free)

### Steps

```bash
git clone https://github.com/jamesbconner/Jidou.git
cd Jidou

cp .env.example .env
# Edit .env — at minimum set TMDB_API_KEY

docker compose --profile default up --build -d
docker compose exec jidou-api alembic upgrade head
```

The `default` profile starts all five services: `postgres`, `redis`, `jidou-api`, `jidou-worker`, `jidou-frontend`.

<!-- screenshot: docker-compose-up-output -->

### Profiles

| Profile | Services started |
|---------|-----------------|
| `default` | All five (recommended) |
| `frontend` | `jidou-frontend` only (add to an existing stack) |

---

## Bare-metal (Python + Node)

Use this for development or when you prefer not to run the application in containers.

### Python environment

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev extras)
uv sync --extra dev

# Start only the infrastructure containers
docker compose up postgres redis -d

# Run database migrations
uv run alembic upgrade head

# Start the API with hot reload
uv run uvicorn jidou.main:app --host 0.0.0.0 --port 8192 --reload

# Start the Celery worker (separate terminal)
uv run celery -A jidou.workers.celery_app worker --loglevel=info
```

### Frontend

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev          # dev server at http://localhost:5173
```

The Vite dev server proxies `/api`, `/ws`, `/docs`, and `/openapi.json` to `http://localhost:8192`.

---

## Environment variables

All configuration lives in `.env`. Copy `.env.example` and fill in the values.

### Required

| Variable | Description |
|----------|-------------|
| `TMDB_API_KEY` | TMDB v3 API key |
| `DATABASE_URL` | Async PostgreSQL URL (`postgresql+asyncpg://user:pass@host/db`) |

### Ports

| Variable | Default | Description |
|----------|---------|-------------|
| `FRONTEND_PORT` | `3100` | Host port for the React UI (nginx) |
| `API_PORT` | `8192` | Host port for the FastAPI backend |
| `POSTGRES_PORT` | `5432` | Host port for PostgreSQL |
| `REDIS_PORT` | `6379` | Host port for Redis |

### Media paths

Each path has two variables: a **host path** (used in the Docker volume mount) and a **container path** (used by the Python application). On Linux/macOS they can be the same value; on Windows they must differ because the container always uses Linux paths.

| Variable | Description |
|----------|-------------|
| `LOCAL_STAGING_HOST_PATH` | Where downloaded files land (host side) |
| `LOCAL_STAGING_PATH` | Same path inside the container |
| `LOCAL_TV_PATH` | Destination for `tv` content |
| `LOCAL_ANIME_PATH` | Destination for `anime` content |
| `LOCAL_MOVIE_PATH` | Destination for `movie` content |

**Windows example:**
```env
LOCAL_STAGING_HOST_PATH=D:\media\staging
LOCAL_STAGING_PATH=/data/staging
LOCAL_TV_PATH=/data/media/tv
```

### API authentication

By default authentication is disabled (safe for isolated local deployments).

To enable it, generate a key and add it to `.env`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

```env
JIDOU_API_KEY=your_generated_key_here
```

All `/api` requests must then include:
```
X-API-Key: your_generated_key_here
```

When using Docker Compose, the nginx frontend injects this header automatically — you do not need to configure the browser.

### SFTP

| Variable | Default | Description |
|----------|---------|-------------|
| `SFTP_HOST` | — | Remote server hostname |
| `SFTP_PORT` | `22` | SSH port |
| `SFTP_USERNAME` | — | SSH username |
| `SFTP_PASSWORD` | — | Password (or use key-based auth) |
| `SFTP_KEY_FILE` | — | Host path to SSH private key (Docker mounts it read-only) |
| `SFTP_KEY_PATH` | — | Container path where the key is mounted |
| `SFTP_REMOTE_PATHS` | `/` | Comma-separated remote directories to scan |
| `SFTP_MAX_WORKERS` | `8` | Parallel download threads |

### LLM (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `none` | `openai`, `anthropic`, `ollama`, `lm-studio`, or `none` |
| `LLM_API_KEY` | — | API key for cloud providers |
| `LLM_BASE_URL` | — | Base URL for local providers |
| `LLM_MODEL` | — | Model identifier |

**Examples:**
```env
# OpenAI
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# Local Ollama (Docker)
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=llama3

# Disabled — heuristic matching only
LLM_PROVIDER=none
```

### TMDB

| Variable | Default | Description |
|----------|---------|-------------|
| `TMDB_RATE_LIMIT_PER_SECOND` | `0.5` | Max TMDB calls per second (do not exceed 1.0) |
| `TMDB_CACHE_TTL` | `86400` | Response cache TTL in seconds (24 hours) |

### Celery worker

| Variable | Default | Description |
|----------|---------|-------------|
| `CELERY_CONCURRENCY` | `4` | Worker process count |
| `CELERY_PREFETCH_MULTIPLIER` | `1` | Tasks prefetched per worker (keep at 1 for long tasks) |

---

## Database migrations

```bash
# Apply all pending migrations
uv run alembic upgrade head
# or inside Docker:
docker compose exec jidou-api alembic upgrade head

# Show current revision
uv run alembic current

# Roll back one migration
uv run alembic downgrade -1

# Create a new migration (after model changes)
uv run alembic revision --autogenerate -m "add index on files.status"
```

### Migration history

All migrations up to and including the original `0002`–`0004` set were squashed into a single `0001_initial` baseline once the schema stabilized — there is no upgrade path from a pre-squash database; wipe and re-migrate (see [Wiping and reinitializing the database](troubleshooting.md#wiping-and-reinitializing-the-database)) or restore from an export.

| Revision | Description |
|----------|-------------|
| `0001_initial` | Full baseline schema: `shows`, `episodes` (incl. `file_tracked`/`file_tracked_at`/`tracked_filename`/`tracked_source`), `downloaded_files`, `background_tasks`, `watchlist`, `orphaned_tracking_records`, `rss_feeds`, `rss_subscriptions`, `rss_config_snapshots`, `app_settings` |
| `f437cd782b1b` | Add index on `episodes.air_date` (calendar page query) |
| `287c0908e5d1` | Add `scanned_directories` table (shallow-scan redesign, issue #355) |

---

## Verifying the installation

```bash
# Deep health check — returns per-service status
curl http://localhost:8192/api/admin/health

# Or via make.py (API must be running)
uv run python make.py health
```

A healthy response looks like:
```json
{
  "database": "ok",
  "redis": "ok",
  "tmdb": "ok",
  "llm": "disabled"
}
```

<!-- screenshot: admin-health-response -->
<!-- screenshot: settings-page -->

See [Troubleshooting](troubleshooting.md) if any service reports an error.
