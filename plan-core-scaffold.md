# Phase 2: Core App Scaffold Plan

## Context

PR #1 (Docker infrastructure) is merged. All 6 CI checks pass. Docker references modules that don't exist yet:
- `jidou.main:app` (FastAPI app)
- `jidou.workers.celery_app` (Celery app)
- `/health` endpoint
- Alembic config

## Architecture (per CLAUDE.md)

Hexagonal architecture with service-oriented design:
```
src/jidou/
  __init__.py          # package marker
  main.py              # FastAPI app + CLI entry point
  config.py            # pydantic-settings configuration
  database.py          # SQLAlchemy async engine, session factory
  models/              # SQLAlchemy model definitions
    __init__.py
    base.py            # declarative base
    show.py            # Show model (movie/TV show metadata)
    user.py            # User preferences
    watchlist.py       # Watchlist entries
  services/            # business logic + external system access
    __init__.py
    tmdb.py            # TMDB API client with caching + rate limiting
    cache.py           # Cache abstraction (in-memory dev, Redis prod)
  api/                 # FastAPI routers
    __init__.py
    health.py          # /health endpoint
    shows.py           # show discovery routes
    watchlist.py       # watchlist routes
  workers/             # Celery background tasks
    __init__.py
    celery_app.py      # Celery app definition
    tasks.py           # background task definitions
```

## Implementation Steps

### Step 1: Configuration (`config.py`)
- `pydantic-settings` based config
- Environment variable overrides
- Database URL, Redis URL, TMDB API key, CORS origins
- **Why**: Every other module needs config; this is the foundation

### Step 2: Database Layer (`database.py` + `models/`)
- Async SQLAlchemy engine with `asyncpg`
- Session factory with dependency injection for FastAPI
- Base model with common fields (id, created_at, updated_at)
- Initial models: `Show` (movie/TV), `WatchlistEntry`
- **Why**: Docker health check needs DB connectivity

### Step 3: Health Endpoint (`api/health.py`)
- `/health` endpoint checking PostgreSQL and Redis
- Structured response with per-service status
- **Why**: Docker health check references this; needed for CI

### Step 4: FastAPI App (`main.py` update)
- Create `app = FastAPI()` with routers mounted
- CORS middleware from config
- Lifecycle management (DB engine startup/shutdown)
- Keep existing `main()` CLI entry point
- **Why**: Docker CMD references `jidou.main:app`

### Step 5: TMDB Service (`services/tmdb.py` + `services/cache.py`)
- HTTP client with `httpx`
- Rate limiting (max 1 call/2s per CLAUDE.md)
- Response caching (24h for show data)
- Pydantic validation for TMDB responses
- **Why**: Core business logic; frontend proxies through this

### Step 6: Celery Worker (`workers/celery_app.py`)
- Celery app with Redis broker
- Background task for periodic TMDB sync
- **Why**: Docker worker CMD references `jidou.workers.celery_app`

### Step 7: Alembic Config
- `alembic.ini`
- `alembic/` directory with env.py and initial migration
- **Why**: `make.py migrate` references this

### Step 8: Tests
- Test config loading
- Test health endpoint
- Test TMDB service with mocked HTTP
- Test database models
- **Why**: 90% coverage target per CLAUDE.md

## Key Design Decisions

1. **Async throughout**: SQLAlchemy async, httpx async, asyncpg
2. **Service abstraction**: TMDB behind interface, not direct imports in routes
3. **Rate limiting**: Global limiter for external APIs (CLAUDE.md requirement)
4. **Caching**: 24h cache for TMDB show data (rarely changes)
5. **Hexagonal boundaries**: Models → Services → API layers, no backward dependencies

## Files to Create (~20 files)

| File | Purpose | Lines |
|---|---|---|
| `src/jidou/config.py` | pydantic-settings config | ~80 |
| `src/jidou/database.py` | SQLAlchemy async setup | ~60 |
| `src/jidou/models/__init__.py` | model exports | ~10 |
| `src/jidou/models/base.py` | declarative base | ~30 |
| `src/jidou/models/show.py` | Show model | ~50 |
| `src/jidou/models/watchlist.py` | Watchlist model | ~40 |
| `src/jidou/services/__init__.py` | service exports | ~10 |
| `src/jidou/services/cache.py` | cache abstraction | ~60 |
| `src/jidou/services/tmdb.py` | TMDB API client | ~120 |
| `src/jidou/api/__init__.py` | router exports | ~10 |
| `src/jidou/api/health.py` | health endpoint | ~50 |
| `src/jidou/api/shows.py` | show routes | ~40 |
| `src/jidou/api/watchlist.py` | watchlist routes | ~40 |
| `src/jidou/workers/__init__.py` | worker exports | ~5 |
| `src/jidou/workers/celery_app.py` | Celery app | ~40 |
| `src/jidou/workers/tasks.py` | background tasks | ~50 |
| `alembic.ini` | Alembic config | ~30 |
| `alembic/env.py` | Alembic env | ~40 |
| `alembic/script.py.mako` | migration template | ~20 |
| `tests/test_config.py` | config tests | ~30 |
| `tests/test_health.py` | health endpoint tests | ~40 |
| `tests/test_tmdb.py` | TMDB service tests | ~60 |

Total: ~1100 lines of new code across 21 files.

## CI Impact

The CI workflow runs:
- `ruff check src/ tests/`
- `ruff format --check src/ tests/`
- `mypy src/`
- `bandit -r src/ -ll`
- `pytest -v`

All new code must pass these checks. Type annotations on every public function, Google-style docstrings, and 90%+ coverage target.
