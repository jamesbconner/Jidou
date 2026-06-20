# Jidou

[![CI](https://github.com/jamesbconner/jidou/actions/workflows/ci.yml/badge.svg)](https://github.com/jamesbconner/jidou/actions/workflows/ci.yml)

Jidou ("自動", *automatic*) is a self-hosted TV show management system. It tracks shows via [TMDB](https://www.themoviedb.org/), scans remote SFTP servers for downloaded files, matches files to episodes using an LLM or heuristic fallback, and routes them to your local library — with real-time progress streaming to the browser.

---

## Features

- **Show tracking** — search TMDB, add shows to your library, sync episode metadata
- **SFTP scanning** — discover new files on a remote server; create a download queue automatically
- **Episode matching** — LLM-assisted (OpenAI, Anthropic, Ollama, LM Studio) or regex heuristic; manual override via UI
- **Watchlist** — curate per-show status (planned / watching / completed / on hold / dropped)
- **Real-time progress** — WebSocket push for every background task; live progress bars in the browser
- **Background workers** — Celery tasks for download, scan, match, and full sync pipelines
- **Rate-limited TMDB client** — Redis-backed token bucket; max 1 req/2 sec; 24-hour response cache
- **Operator tools** — `PATCH /api/files/{id}` to correct show/episode assignments; task cancel endpoint

---

## Architecture

```
┌─────────────────┐   HTTP/WS    ┌─────────────────────────────────────┐
│  React Frontend │ ──────────── │  FastAPI (port 8192)                │
│  (Nginx :3100)  │              │  ├── /api/shows   /api/files        │
└─────────────────┘              │  ├── /api/watchlist  /api/tasks     │
                                 │  ├── /api/admin  /api/config        │
                                 │  └── /ws/task-progress/{task_id}   │
                                 └────────────┬────────────────────────┘
                                              │
                         ┌────────────────────┼────────────────────┐
                         │                    │                    │
                   ┌─────▼──────┐    ┌────────▼───────┐   ┌──────▼──────┐
                   │ PostgreSQL │    │  Redis         │   │ Celery      │
                   │ (models,   │    │  (broker,      │   │ Worker      │
                   │  history)  │    │   cache,       │   │ (scan,      │
                   └────────────┘    │   rate limiter,│   │  download,  │
                                     │   PubSub)      │   │  match,     │
                                     └────────────────┘   │  sync)      │
                                                          └─────────────┘
```

**Key constraints:**
- API always runs on port **8192** (never 8000)
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
│   │   ├── routes/          # FastAPI route handlers
│   │   │   ├── shows.py
│   │   │   ├── files.py
│   │   │   ├── watchlist.py
│   │   │   ├── tasks.py
│   │   │   ├── admin.py
│   │   │   └── config.py
│   │   └── websocket/       # WebSocket progress streaming
│   ├── models/              # SQLAlchemy ORM models
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # External service clients
│   │   ├── tmdb_service.py  # TMDB API with rate limiting + caching
│   │   ├── sftp_service.py  # AsyncSSH file transfer
│   │   ├── llm_service.py   # Multi-provider LLM abstraction
│   │   ├── rate_limiter.py  # Redis token bucket
│   │   └── cache.py         # In-memory + Redis response cache
│   ├── orchestrators/       # Multi-service workflow coordination
│   │   ├── scan_orchestrator.py
│   │   ├── download_orchestrator.py
│   │   ├── match_orchestrator.py
│   │   └── sync_orchestrator.py
│   ├── workers/             # Celery task definitions
│   │   ├── celery_app.py
│   │   ├── scan_tasks.py
│   │   ├── download_tasks.py
│   │   ├── match_tasks.py
│   │   └── sync_tasks.py
│   └── config/              # Pydantic settings (env-based)
├── frontend/                # React + Vite SPA
│   └── src/
│       ├── api/             # Typed fetch client + WebSocket
│       ├── components/      # Reusable UI components
│       ├── hooks/           # TanStack Query data hooks
│       ├── pages/           # Route-level page components
│       └── types/           # TypeScript API types
├── alembic/versions/        # Database migrations
├── tests/                   # pytest test suite (238 tests, 85% coverage)
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.worker
├── make.py                  # Dev task runner
└── pyproject.toml
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness check |
| GET | `/api/admin/health` | Deep health (DB, Redis, TMDB config) |
| GET | `/api/admin/stats` | Row counts per table |
| POST | `/api/admin/cache/flush` | Clear in-memory TMDB cache |
| GET | `/api/config` | View current application config |
| POST | `/api/config/test-sftp` | Test SFTP connectivity |
| POST | `/api/config/test-tmdb` | Test TMDB API key |
| GET | `/api/shows` | List tracked shows |
| POST | `/api/shows` | Add a show (from TMDB ID) |
| GET | `/api/shows/{id}` | Get show detail + episodes |
| PUT | `/api/shows/{id}/paths` | Set remote/local paths |
| DELETE | `/api/shows/{id}` | Remove show and its data |
| GET | `/api/shows/search` | Search TMDB |
| POST | `/api/shows/{id}/sync-episodes` | Sync episode metadata from TMDB |
| GET | `/api/files` | List downloaded files (filter by status/show) |
| GET | `/api/files/{id}` | Get file detail |
| PATCH | `/api/files/{id}` | Correct show_id, episode_id, status, error |
| POST | `/api/files/{id}/match` | Re-trigger episode matching |
| GET | `/api/watchlist` | List watchlist entries (filter by status) |
| POST | `/api/watchlist` | Add show to watchlist (idempotent) |
| GET | `/api/watchlist/{id}` | Get entry |
| PATCH | `/api/watchlist/{id}` | Update status / notes / position |
| DELETE | `/api/watchlist/{id}` | Remove entry |
| GET | `/api/tasks` | List background tasks |
| GET | `/api/tasks/{id}` | Get task status + progress |
| POST | `/api/tasks/trigger` | Launch scan / download / match / sync |
| POST | `/api/tasks/{id}/cancel` | Cancel running task |
| WS | `/ws/task-progress/{task_id}` | Real-time progress stream |

File statuses: `pending → downloading → downloaded → routing → routed / error`

---

## Background Tasks

Trigger via `POST /api/tasks/trigger` or from the Tasks page in the UI.

| Task type | Description |
|-----------|-------------|
| `scan` | List files on SFTP; create `DownloadedFile` rows for new files |
| `download` | Download pending/errored files from SFTP to local path |
| `match` | Match downloaded files to episodes via LLM or heuristic |
| `sync` | Full pipeline: scan → download → match |

All tasks support a `dry_run` flag; progress is streamed to the UI in real time via WebSocket.

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
| `0001` | Initial schema: `shows` table |
| `0002` | `watchlist` table + `WatchlistStatus` enum |
| `0003` | `episodes` + `downloaded_files` tables |
| `0004` | `UNIQUE(show_id, remote_path)` on `downloaded_files` |
| `0005` | `UNIQUE(show_id)` on `watchlist` |

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

238 Python tests · 85% coverage · 15 frontend tests (Vitest)

---

## Contributing

1. Run `pre-commit install` after cloning to wire up git hooks
2. All PRs must pass `uv run python make.py check` (lint, format, types, security, tests)
3. New behaviour requires new tests; bug fixes require regression tests
4. Keep coverage ≥ 85%
