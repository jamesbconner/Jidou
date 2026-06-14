# Jidou Implementation Plan

## Overview

Transform Jidou from a skeleton CLI project into a full FastAPI application running in Docker, with a React frontend, real-time progress streaming via WebSockets, and background task processing via Celery.

**Key Constraints:**
- API port: **8192** (never 8000 — conflicts with other containers)
- External API rate limiting: max 1 call / 2 seconds, Redis-backed, shared across all workers
- Frontend never calls external APIs directly — all proxied through backend
- Local SLM: qwen 3.6-27b via LM Studio, max 4 concurrent agents
- Scope: all TV shows (no genre restrictions)

---

## Phase 1: Docker Infrastructure & Backend Skeleton

### 1.1 Docker Compose Setup

**File:** `docker-compose.yml`

Services:
- `jidou-api`: FastAPI + Uvicorn on port **8192**
- `jidou-frontend`: React SPA served by Nginx on port **3100**
- `jidou-worker`: Celery worker(s) for background tasks
- `postgres`: PostgreSQL 16
- `redis`: Redis 7 (broker + cache + rate limiter)

Development vs production profiles via `docker-compose profiles`.

### 1.2 Dockerfiles

**File:** `Dockerfile.api` — Python 3.13 slim, uv for deps, mounts src, runs Uvicorn
**File:** `Dockerfile.worker` — Same base, runs Celery worker
**File:** `Dockerfile.frontend` — Node 20, builds React SPA, serves via Nginx

Multi-stage builds: build stage installs deps, production stage copies only what's needed.

### 1.3 Environment Configuration

**File:** `.env.example` — Template with all required env vars (DB credentials, API keys, ports)
**File:** `src/jidou/config/settings.py` — Pydantic `BaseSettings` reading from env vars

Settings structure:
```python
class Settings(BaseSettings):
    # Database
    database_url: str

    # Redis
    redis_url: str

    # TMDB API
    tmdb_api_key: str
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    tmdb_rate_limit_per_second: float = 0.5  # 1 call per 2 seconds

    # LLM (optional)
    llm_provider: str = "none"
    llm_api_key: str = ""
    llm_base_url: str = ""

    # Application
    debug: bool = False
    allowed_origins: list[str] = ["http://localhost:3100"]
```

### 1.4 FastAPI App Factory

**File:** `src/jidou/main.py` — Replace stub with FastAPI app

- Lifespan context manager for startup/shutdown (init DB, health checks)
- CORS middleware configured for frontend origin
- Dependency injection for settings, DB session, Redis connection
- OpenAPI schema auto-generated from routes + Pydantic schemas

---

## Phase 2: Database Layer & Models

### 2.1 SQLAlchemy Setup

**File:** `src/jidou/database/engine.py` — Async engine, session factory, base metadata
**File:** `src/jidou/database/session.py` — Dependency that yields async session, auto-close
**File:** `alembic.ini` + `alembic/` — Migration configuration

### 2.2 Core Models

**File:** `src/jidou/models/show.py`
```python
class Show(BaseModel):
    id: Mapped[int]
    tmdb_id: Mapped[int]  # unique
    title: Mapped[str]
    overview: Mapped[str]
    first_air_date: Mapped[date | None]
    poster_path: Mapped[str | None]
    backdrop_path: Mapped[str | None]
    genre_ids: Mapped[list[int]]  # JSONB
    status: Mapped[str]  # "ongoing", "ended", "cancelled"
    remote_path: Mapped[str | None]  # base path on SFTP server
    local_path: Mapped[str | None]  # local mount path
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

**File:** `src/jidou/models/episode.py`
```python
class Episode(BaseModel):
    id: Mapped[int]
    show_id: Mapped[int] = ForeignKey("shows.id")
    tmdb_id: Mapped[int]
    season_number: Mapped[int]
    episode_number: Mapped[int]
    name: Mapped[str]
    air_date: Mapped[date | None]
    overview: Mapped[str]
    runtime: Mapped[int | None]
    file_tracked: Mapped[bool] = False  # have we found/routed this file?
```

**File:** `src/jidou/models/downloaded_file.py`
```python
class DownloadedFile(BaseModel):
    id: Mapped[int]
    show_id: Mapped[int | None] = ForeignKey("shows.id", nullable=True)
    episode_id: Mapped[int | None] = ForeignKey("episodes.id", nullable=True)
    original_filename: Mapped[str]
    remote_path: Mapped[str]
    local_path: Mapped[str | None]
    file_size: Mapped[int]
    hash_sha256: Mapped[str | None]
    status: Mapped[str]  # "pending", "downloading", "downloaded", "routed", "error"
    matched_by: Mapped[str | None]  # "llm", "heuristic", "manual"
    created_at: Mapped[datetime]
```

**File:** `src/jidou/models/task.py`
```python
class BackgroundTask(BaseModel):
    id: Mapped[int]
    celery_task_id: Mapped[str]  # unique
    task_type: Mapped[str]  # "download", "scan", "match", "sync"
    status: Mapped[str]  # "pending", "running", "completed", "failed"
    progress_current: Mapped[int] = 0
    progress_total: Mapped[int] = 0
    progress_message: Mapped[str | None]
    result_summary: Mapped[str | None]  # JSONB
    created_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]
```

### 2.3 Pydantic Schemas

**Directory:** `src/jidou/schemas/` — Request/response schemas for each domain
- `show_schema.py`: ShowCreate, ShowRead, ShowUpdate, ShowList
- `episode_schema.py`: EpisodeRead, EpisodeList
- `file_schema.py`: FileRead, FileList, FileMatchRequest
- `task_schema.py`: TaskRead, TaskProgress, TaskList

Schemas use nested models appropriately and exclude sensitive fields.

---

## Phase 3: Real-Time Infrastructure (Celery + WebSockets)

### 3.1 Celery Configuration

**File:** `src/jidou/workers/celery_app.py`
- Celery app with Redis broker, Redis backend
- Task serialization: JSON
- Timeouts, retries, and rate limits per task type
- Beat schedule for periodic tasks (optional)

### 3.2 WebSocket Manager

**File:** `src/jidou/api/websocket/task_progress.py`
- `ConnectionManager` class: tracks active WebSocket connections per task_id
- WebSocket endpoint: `/ws/task-progress/{task_id}`
- Messages are typed: `{"type": "progress" | "file_update" | "complete" | "error", "data": ...}`
- Automatic reconnection with exponential backoff on the frontend

### 3.3 Progress Emission Pattern

Every background task that does work emits progress:
```python
async def emit_progress(task_id: str, message: dict[str, Any]):
    """Emit progress event to all subscribers via Redis PubSub."""
    await redis.publish("task_progress", json.dumps({"task_id": task_id, **message}))
```

A Redis subscriber in the API layer forwards to WebSocket clients. This decouples workers from the WebSocket layer.

### 3.4 Task Definitions

**File:** `src/jidou/tasks/download_tasks.py` — Download files from SFTP with per-file progress
**File:** `src/jidou/tasks/scan_tasks.py` — Scan remote SFTP servers for new files
**File:** `src/jidou/tasks/match_tasks.py` — Match files to episodes via LLM or heuristic
**File:** `src/jidou/tasks/sync_tasks.py` — Full sync pipeline: scan → match → route

Each task:
- Updates `BackgroundTask` DB row on start, progress, and completion
- Emits progress events via Redis PubSub for real-time WebSocket delivery
- Includes `dry_run` parameter for state-changing operations
- Has retry logic with exponential backoff for transient failures

---

## Phase 4: External API Services with Rate Limiting

### 4.1 Rate Limiter

**File:** `src/jidou/services/rate_limiter.py`
- Redis-backed token bucket algorithm
- Configurable per-endpoint limits (default: 0.5 req/sec = 1 call per 2 seconds)
- In-flight request deduplication: if same query is pending, wait for existing result
- Proactive throttling: warn at 80% capacity, throttle at 90%
- Observability: log every call with timing, status, and rate-limit headers remaining

### 4.2 TMDB Service

**File:** `src/jidou/services/tmdb_service.py`
- Methods: `get_show_by_id`, `search_show`, `get_episodes`, `get_images`
- All calls go through rate limiter
- Response caching: 24-hour TTL for show data, 1-hour TTL for search results
- Retry on 429 with backoff, but also prevent 429s proactively
- Never called from frontend — all proxied through backend API routes

### 4.3 SFTP Service

**File:** `src/jidou/services/sftp_service.py`
- AsyncSSH-based, non-blocking
- Methods: `list_remote_files`, `download_file`, `download_files`
- `download_files` emits per-file progress: filename, size, current/total, elapsed time
- Connection pooling for repeated operations
- Dry run support: list what would be downloaded without transferring

### 4.4 LLM Service (Optional)

**File:** `src/jidou/services/llm_service.py`
- Multi-provider abstraction: OpenAI, Anthropic, Ollama, LM Studio
- Select provider via config, not code changes
- Response caching keyed on (prompt, model, provider)
- Graceful degradation: if LLM unavailable, fall back to heuristic matching
- Never blocks startup — log warning and continue if LLM fails to connect

---

## Phase 5: API Routes

### 5.1 Route Structure

**Directory:** `src/jidou/api/routes/`

- `shows.py`: CRUD for shows, discover shows via TMDB, link local/remote paths
- `files.py`: List tracked files, trigger downloads, re-match files
- `tasks.py`: List background tasks, get task status, cancel running tasks
- `config.py`: View/update application settings, test connections
- `admin.py`: Database migrations, cache clearing, system health

### 5.2 Route Design Principles

- Thin route handlers: parse request, validate, delegate to service/orchestrator
- All long-running operations return immediately with `task_id`, processing happens in Celery
- Response schemas validated by Pydantic
- Dependency injection for DB sessions, services, settings
- Health check endpoint at `/health` for container orchestration

---

## Phase 6: React Frontend

### 6.1 Project Structure

**Directory:** `frontend/`

```
frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── src/
│   ├── main.tsx                 # Entry point
│   ├── App.tsx                  # Router + layout
│   ├── api/
│   │   ├── client.ts            # ofetch/axios wrapper, auto-typed from OpenAPI
│   │   └── websocket.ts         # WebSocket client with auto-reconnect
│   ├── components/
│   │   ├── ShowCard.tsx
│   │   ├── FileList.tsx
│   │   ├── TaskProgress.tsx     # Real-time progress bar
│   │   └── ...
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── Shows.tsx
│   │   ├── ShowDetail.tsx
│   │   ├── Files.tsx
│   │   └── Settings.tsx
│   ├── hooks/
│   │   ├── useTaskProgress.ts   # WebSocket hook for task progress
│   │   └── ...
│   └── stores/
│       └── connection.ts        # WebSocket connection state
├── public/
└── tests/
```

### 6.2 Key Frontend Features

- **Auto-generated types** from FastAPI OpenAPI spec (via `openapi-typescript`)
- **TanStack Query** for server state with caching, background refetching, optimistic updates
- **WebSocket integration** for real-time task progress:
  - `TaskProgress` component shows live progress bar with file-by-file updates
  - Connection state indicator in header
  - Auto-reconnect with exponential backoff
- **Error boundaries** catch React rendering errors, display fallback UI
- **Responsive design** works on desktop and tablet
- **Theme support** light/dark mode

### 6.3 Frontend Steering Rules

- Never call external APIs (TMDB, etc.) directly — all through backend
- API client has retry logic for transient failures (4xx/5xx)
- Loading states for all async operations, skeleton screens for lists
- Confirmation dialogs for destructive actions (delete, overwrite)
- `dry_run` flag exposed as checkbox in UI for state-changing operations

---

## Phase 7: Orchestrators

### 7.1 Show Discovery Orchestrator

**File:** `src/jidou/orchestrators/show_discovery.py`
- Search TMDB for shows, create DB entries, fetch episode metadata
- Idempotent: won't duplicate existing shows
- Emits progress: searching, found N shows, fetching episodes for each

### 7.2 File Download Orchestrator

**File:** `src/jidou/orchestrators/file_download.py`
- Scan remote SFTP, list files, download with per-file progress
- Track each file in DB, update status on completion/error
- Dry run: list what would be downloaded, don't transfer

### 7.3 Episode Matching Orchestrator

**File:** `src/jidou/orchestrators/episode_matching.py`
- Match downloaded files to episodes via LLM (preferred) or heuristic (fallback)
- Update DB with match results
- Log match confidence, allow manual override via UI

### 7.4 Sync Pipeline Orchestrator

**File:** `src/jidou/orchestrators/sync_pipeline.py`
- Full pipeline: scan → download → match → route
- Configurable stages, can run any subset
- Emits overall progress plus per-stage progress

---

## Phase 8: Testing

### 8.1 Test Structure

```
tests/
├── conftest.py            # Shared fixtures: async DB session, mock services
├── test_models/
├── test_services/
│   ├── test_tmdb_service.py
│   ├── test_sftp_service.py
│   └── test_rate_limiter.py
├── test_api/
│   ├── test_routes/
│   └── test_websocket/
├── test_tasks/
└── test_orchestrators/
```

### 8.2 Testing Approach

- **Async fixtures** for DB sessions, Redis connections
- **Mock external services**: TMDB responses from cached JSON fixtures, SFTP with moto or custom mocks
- **Integration tests** with real SQLite in-memory DB
- **WebSocket tests** using `websockets` library or FastAPI's `TestClient` WebSocket support
- **Frontend tests** with Vitest + React Testing Library
- **Rate limiter tests**: verify that burst requests are throttled correctly

---

## Phase 9: Make Script Updates

### 9.1 New Targets

Update `make.py` to include:
- `docker-up`: start Docker Compose
- `docker-down`: stop Docker Compose
- `docker-build`: rebuild images
- `migrate`: run Alembic migrations
- `seed`: populate DB with sample data
- `health`: run health checks
- `generate-types`: generate TypeScript types from OpenAPI spec
- `build-frontend`: build React SPA for production

---

## Implementation Order

1. **Docker infrastructure** (Phase 1) — foundation everything else builds on
2. **Database layer** (Phase 2) — models, sessions, migrations
3. **Real-time infrastructure** (Phase 3) — Celery + WebSockets, build early so everything benefits
4. **Rate limiter** (Phase 4.1) — critical to get right before any external API calls
5. **TMDB service** (Phase 4.2) — show/episode metadata
6. **SFTP service** (Phase 4.3) — remote file access
7. **API routes** (Phase 5) — expose everything through FastAPI
8. **React frontend** (Phase 6) — consume the API
9. **Orchestrators** (Phase 7) — tie services together into pipelines
10. **Testing** (Phase 8) — throughout, but comprehensive suite at end
11. **Make script** (Phase 9) — dev task runner

---

## Files to Create (Estimated Count: ~40-50 Python files, ~15-20 Frontend files)

### Backend (~45 files)
- Docker: 3 (Dockerfile.api, Dockerfile.worker, Dockerfile.frontend, docker-compose.yml)
- Config: 2 (settings.py, health.py)
- Database: 3 (engine.py, session.py, alembic config)
- Models: 4 (show.py, episode.py, downloaded_file.py, task.py)
- Schemas: 4 (show, episode, file, task)
- Services: 5 (tmdb, sftp, llm, rate_limiter, database)
- Orchestrators: 4 (discovery, download, matching, sync)
- API routes: 5 (shows, files, tasks, config, admin)
- WebSocket: 1 (task_progress)
- Tasks: 4 (download, scan, match, sync)
- Workers: 1 (celery_app)
- Dependencies: 1 (deps.py)

### Frontend (~18 files)
- Config: 3 (package.json, tsconfig, vite.config)
- Entry: 2 (main.tsx, App.tsx)
- API client: 2 (client.ts, websocket.ts)
- Components: 6 (ShowCard, FileList, TaskProgress, etc.)
- Pages: 5 (Dashboard, Shows, ShowDetail, Files, Settings)
- Hooks: 1 (useTaskProgress)
- Stores: 1 (connection state)

### Infrastructure
- `.env.example`: 1
- `docker-compose.yml`: 1
- Updated `pyproject.toml`: 1
- Updated `make.py`: 1

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| TMDB API key rate limit exceeded during development | Rate limiter built early, aggressive caching, test with small datasets |
| WebSocket connection drops during long tasks | Auto-reconnect with backoff, task state persisted in DB |
| Celery worker crashes mid-operation | Task retries, DB transactions, idempotent operations |
| Frontend type drift from backend | Auto-generate types from OpenAPI spec, run in CI |
| Docker compose complexity | Start with minimal compose, add services incrementally |
