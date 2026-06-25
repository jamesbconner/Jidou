# Jidou

[![CI](https://github.com/jamesbconner/jidou/actions/workflows/ci.yml/badge.svg)](https://github.com/jamesbconner/jidou/actions/workflows/ci.yml)

Jidou ("自動", *automatic*) is a self-hosted TV show and anime management system. It tracks shows via [TMDB](https://www.themoviedb.org/), scans remote SFTP servers for downloaded files, matches files to episodes using an LLM or heuristic fallback, and routes them to your local library — with real-time progress streaming to the browser.

---

## Features

- **Show tracking** — search or browse TMDB trending, add shows to your library; episodes are auto-synced on creation
- **Content type inference** — new shows are automatically classified as `anime`, `tv`, or `movie` from TMDB genre and language metadata; editable from the show detail page
- **SFTP scanning** — discover new files on a remote server; create a download queue automatically
- **File download** — pull files from SFTP to a local staging path via background worker
- **Episode matching** — LLM-assisted (OpenAI, Anthropic, Ollama, LM Studio) or regex heuristic; manual override via UI; TMDB suggestions for unmatched files
- **File routing** — move matched files to the correct library folder by content type
- **Path import** — bulk-import an existing local media directory; creates show and episode records from folder structure
- **Show rematch** — re-link a show to a different TMDB entry, replacing all episode data
- **Data quality** — per-show DQ checks (missing path, unset content type, no episodes, orphan); amber badge on library cards; filterable Data Quality tab
- **Watchlist** — curate per-show status (`planned` / `watching` / `completed` / `on_hold` / `dropped`) with optional notes
- **Real-time progress** — WebSocket push for every background task; live progress bars in the browser
- **Background workers** — Celery tasks for scan, download, match, route, and full sync pipelines
- **Rate-limited TMDB client** — Redis-backed token bucket; max 0.5 req/sec; 24-hour response cache
- **Export / import** — export the full database to YAML; re-import to restore or migrate
- **Operator tools** — `PATCH /api/files/{id}` to correct show/episode assignments; task cancel endpoint; cache flush

---

## Architecture

```
┌─────────────────┐   HTTP/WS    ┌─────────────────────────────────────┐
│  React Frontend │ ──────────── │  FastAPI (port 8192)                │
│  (Nginx :3100)  │              │  ├── /api/shows   /api/files        │
└─────────────────┘              │  ├── /api/watchlist  /api/tasks     │
                                 │  ├── /api/admin  /api/config        │
                                 │  ├── /api/import  /api/export       │
                                 │  └── /ws/task-progress/{task_id}    │
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
- API runs on port **8192**
- Frontend never calls TMDB directly — all external traffic is proxied through the backend
- TMDB rate limit enforced globally across all workers via Redis (max 0.5 req/sec)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn, Python 3.13 |
| Workers | Celery 5, asyncio tasks |
| Database | PostgreSQL 16, SQLAlchemy 2 (async), Alembic |
| Cache / Broker | Redis 7 |
| Frontend | React 18, Vite 6, TypeScript, TailwindCSS, TanStack Query |
| Containers | Docker, Docker Compose |
| Quality | ruff, mypy (strict), bandit, pytest, Vitest |

---

## Quick Start

### Prerequisites

- [Docker + Docker Compose](https://docs.docker.com/get-docker/)
- A [TMDB API key](https://www.themoviedb.org/settings/api) (free)
- SFTP credentials if you want file scanning/downloading

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — set TMDB_API_KEY at minimum
```

### 2. Start all services

```bash
uv run python make.py docker-up
# or: docker compose --profile default up --build -d
```

| Service | URL |
|---------|-----|
| React UI | http://localhost:3100 |
| API + Swagger | http://localhost:8192/docs |
| ReDoc | http://localhost:8192/redoc |

### 3. Run database migrations

```bash
uv run python make.py migrate
# or: uv run alembic upgrade head
```

### 4. (Optional) Seed sample data

```bash
uv run python make.py seed
```

---

## Local Development (without Docker)

```bash
# Install uv if you don't have it: https://docs.astral.sh/uv/
uv sync --extra dev

# Start infrastructure (DB + Redis only)
docker compose up postgres redis -d

# Run API with hot reload
uv run uvicorn jidou.main:app --host 0.0.0.0 --port 8192 --reload

# Run Celery worker (separate terminal)
uv run celery -A jidou.workers.celery_app worker --loglevel=info

# Run frontend dev server (separate terminal)
cd frontend && npm install && npm run dev
```

---

## Project Layout

```
jidou/
├── src/jidou/
│   ├── api/
│   │   ├── routes/               # FastAPI route handlers
│   │   │   ├── shows.py          # Show CRUD, TMDB search/trending, rematch, sync
│   │   │   ├── files.py          # File list, TMDB suggestions, PATCH, manual match
│   │   │   ├── watchlist.py      # Watchlist CRUD + status/notes management
│   │   │   ├── tasks.py          # Task trigger, status, cancel
│   │   │   ├── admin.py          # Stats, cache, health, timeline
│   │   │   ├── import_routes.py  # Bulk import: path text / database YAML
│   │   │   ├── export_routes.py  # Database YAML export
│   │   │   └── config.py         # Config view, SFTP/TMDB connectivity tests
│   │   └── websocket/            # WebSocket progress streaming
│   ├── models/                   # SQLAlchemy ORM models
│   ├── schemas/                  # Pydantic request/response schemas
│   ├── services/                 # External service clients
│   │   ├── tmdb.py               # TMDB API with rate limiting + caching
│   │   ├── sftp_service.py       # AsyncSSH file transfer
│   │   ├── llm_service.py        # Multi-provider LLM abstraction
│   │   ├── rate_limiter.py       # Redis token bucket
│   │   └── progress.py           # Task record management + WebSocket emit
│   ├── orchestrators/            # Multi-service workflow coordination
│   │   ├── scan_orchestrator.py
│   │   ├── download_orchestrator.py
│   │   ├── match_orchestrator.py
│   │   ├── parse_orchestrator.py
│   │   ├── route_orchestrator.py
│   │   ├── path_import_orchestrator.py
│   │   ├── tmdb_orchestrator.py
│   │   └── sync_orchestrator.py
│   └── workers/                  # Celery task definitions
│       ├── celery_app.py
│       ├── scan_tasks.py
│       ├── download_tasks.py
│       ├── match_tasks.py
│       ├── route_tasks.py
│       ├── import_tasks.py       # Path and DB import
│       ├── db_import_tasks.py
│       └── sync_tasks.py
├── frontend/                     # React + Vite SPA
│   └── src/
│       ├── api/                  # Typed fetch client + WebSocket
│       ├── components/           # Reusable UI components (ShowCard, FileStatusBadge)
│       ├── hooks/                # TanStack Query data hooks
│       ├── pages/                # Route-level page components
│       ├── stores/               # WebSocket connection state
│       ├── types/                # TypeScript API types
│       └── utils/                # Shared utilities (DQ check definitions)
├── alembic/versions/             # Database migrations
├── tests/                        # pytest test suite (384 tests)
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.worker
├── make.py                       # Dev task runner
└── pyproject.toml
```

---

## API Reference

### Health & Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness check |
| GET | `/api/admin/health` | Deep health check (DB, Redis, TMDB, LLM) |
| GET | `/api/admin/stats` | Row counts and DQ totals |
| GET | `/api/admin/stats/files-timeline` | Files added per day (last 30 days) |
| GET | `/api/admin/stats/pipeline-status` | File counts by status |
| GET | `/api/admin/cache` | Inspect TMDB response cache entries |
| POST | `/api/admin/cache/flush` | Clear in-memory TMDB cache |

### Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config` | View current application config |
| POST | `/api/config/test-sftp` | Test SFTP connectivity |
| POST | `/api/config/test-tmdb` | Test TMDB API key |

### Shows

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/shows` | List tracked shows (sort, filter, limit) |
| POST | `/api/shows` | Add a show from TMDB; auto-infers content type and syncs episodes |
| GET | `/api/shows/{id}` | Get show detail |
| PATCH | `/api/shows/{id}` | Update user-managed fields (e.g. `content_type`) |
| PUT | `/api/shows/{id}/paths` | Set local filesystem path |
| PUT | `/api/shows/{id}/aliases` | Replace show aliases list |
| DELETE | `/api/shows/{id}` | Remove show and all its data |
| GET | `/api/shows/trending` | Trending TV or movie results from TMDB |
| GET | `/api/shows/search` | Search TMDB by title |
| GET | `/api/shows/tmdb/{tmdb_id}` | Fetch TMDB detail for a specific ID |
| POST | `/api/shows/{id}/rematch` | Re-link show to a different TMDB entry |
| POST | `/api/shows/{id}/sync-episodes` | Sync episode metadata from TMDB |
| GET | `/api/shows/{id}/episodes` | List episodes for a show |

### Files

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/files` | List files (filter by status, show, filename) |
| GET | `/api/files/unmatched` | List files needing manual review |
| GET | `/api/files/{id}` | Get file detail |
| GET | `/api/files/{id}/tmdb-suggestions` | TMDB show suggestions for an unmatched file |
| PATCH | `/api/files/{id}` | Correct `show_id`, `episode_id`, `status`, or `error_message` |
| POST | `/api/files/{id}/match` | Re-trigger episode matching |

### Watchlist

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | List entries (filter by status) |
| POST | `/api/watchlist` | Add show to watchlist (idempotent) |
| GET | `/api/watchlist/{id}` | Get entry |
| PATCH | `/api/watchlist/{id}` | Update status / notes / position |
| DELETE | `/api/watchlist/{id}` | Remove entry |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks` | List background tasks |
| GET | `/api/tasks/{id}` | Get task status + progress |
| POST | `/api/tasks/trigger` | Launch `scan` / `download` / `match` / `route` / `sync` |
| POST | `/api/tasks/{id}/cancel` | Cancel a running task |
| WS | `/ws/task-progress/{task_id}` | Real-time progress stream |

### Import / Export

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/import/text` | Import shows from a newline-delimited path list |
| POST | `/api/import/database` | Restore library from an exported YAML file |
| GET | `/api/export/database` | Export full library to YAML |

---

## File Status Lifecycle

```
discovered → downloading → downloaded → matched → routing → routed
                                      ↘ unmatched (needs manual review)
                                                           ↘ error
```

| Status | Description |
|--------|-------------|
| `discovered` | Found on SFTP, not yet downloaded |
| `downloading` | Transfer in progress |
| `downloaded` | In staging area, awaiting match |
| `unmatched` | Parse/match failed; needs manual correction |
| `matched` | Linked to a show/episode; ready to route |
| `routing` | Being moved to final library path |
| `routed` | In final location |
| `error` | Terminal failure with error message |

---

## Background Tasks

Trigger via `POST /api/tasks/trigger` or from the Tasks page in the UI.

| Task type | Description |
|-----------|-------------|
| `scan` | List files on SFTP; create records for new files |
| `download` | Download `discovered`/`error` files from SFTP to staging |
| `match` | Match `downloaded` files to episodes via LLM or heuristic |
| `route` | Move `matched` files to the correct library folder |
| `sync` | Full pipeline: scan → download → match → route |

All tasks support a `dry_run` flag; progress is streamed via WebSocket in real time.

---

## LLM Configuration

Set `LLM_PROVIDER` in `.env` to one of: `openai`, `anthropic`, `ollama`, `lm-studio`, `none`.

```env
# OpenAI
LLM_PROVIDER=openai
LLM_API_KEY=sk-...

# Local Ollama
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434

# LM Studio
LLM_PROVIDER=lm-studio
LLM_BASE_URL=http://host.docker.internal:1234/v1

# Disable (heuristic matching only)
LLM_PROVIDER=none
```

---

## Make Script

```bash
# Code quality
uv run python make.py check          # lint + format-check + types + security + test
uv run python make.py lint
uv run python make.py format
uv run python make.py types
uv run python make.py security
uv run python make.py test

# Docker
uv run python make.py docker-up      # start all services
uv run python make.py docker-down
uv run python make.py docker-build   # rebuild images (no cache)

# Database
uv run python make.py migrate        # run Alembic migrations
uv run python make.py seed           # insert sample shows

# Frontend
uv run python make.py build-frontend # npm run build
uv run python make.py generate-types # regenerate TS types from OpenAPI (API must be running)

# Health
uv run python make.py health         # GET /api/admin/health (API must be running)
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | *(see .env.example)* | Async PostgreSQL URL (`postgresql+asyncpg://...`) |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `TMDB_API_KEY` | — | **Required.** TMDB v3 API key |
| `LLM_PROVIDER` | `none` | LLM backend (`openai`, `anthropic`, `ollama`, `lm-studio`, `none`) |
| `LLM_API_KEY` | — | API key for chosen LLM provider |
| `LLM_BASE_URL` | — | Base URL for local LLM providers |
| `LLM_MODEL` | *(provider default)* | Model name to use for episode matching |
| `SFTP_HOST` | — | SFTP server hostname |
| `SFTP_PORT` | `22` | SFTP port |
| `SFTP_USERNAME` | — | SFTP username |
| `SFTP_PASSWORD` | — | SFTP password (or use key-based auth) |
| `LOCAL_TV_PATH` | — | Destination folder for `tv` content |
| `LOCAL_ANIME_PATH` | — | Destination folder for `anime` content |
| `LOCAL_MOVIE_PATH` | — | Destination folder for `movie` content |
| `LOCAL_STAGING_PATH` | — | Temporary staging area for downloaded files |
| `DEBUG` | `true` | Enable auto-reload and verbose logging |
| `ALLOWED_ORIGINS` | `http://localhost:3100` | CORS allowed origins |
| `API_PORT` | `8192` | Host port for the API container |
| `FRONTEND_PORT` | `3100` | Host port for the frontend container |
| `CELERY_CONCURRENCY` | `4` | Worker process count |

---

## Database Migrations

```bash
# Apply all migrations
uv run alembic upgrade head

# Roll back one migration
uv run alembic downgrade -1

# Create a new migration
uv run alembic revision --autogenerate -m "description"
```

Migration history:

| Revision | Description |
|----------|-------------|
| `0001` | Initial schema: `shows`, `episodes`, `downloaded_files`, `background_tasks`, `watchlist` |
| `0002` | Add `file_tracked_at` to `episodes` |

---

## Testing

```bash
# Full Python suite
uv run pytest

# With coverage
uv run pytest --cov=src

# Frontend tests
cd frontend && npm run test
```

384 Python tests · frontend tests (Vitest)

---

## Contributing

1. Run `pre-commit install` after cloning to wire up git hooks
2. All PRs must pass `uv run python make.py check` (lint, format, types, security, tests)
3. New behaviour requires new tests; bug fixes require regression tests
4. Keep coverage ≥ 85%
