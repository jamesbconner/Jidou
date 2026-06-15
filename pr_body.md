## Summary

Build the complete core application architecture for the Jidou media tracking platform.

## Changes

### Application Layer
- FastAPI application with lifespan-based startup/shutdown
- Health check endpoint monitoring PostgreSQL, Redis, and TMDB
- Show discovery endpoints for trending, search, and details

### Data Layer
- Async SQLAlchemy 2.0 database layer with engine and session factory
- Show model — movies and TV series metadata
- WatchlistEntry model — user watchlist with status tracking
- Alembic migrations with async support

### Services
- Redis-backed cache with TTL support
- TMDB API client with rate limiting and HTTP caching
- Token bucket rate limiter for external API calls
- Celery worker for background task processing

### Configuration
- pydantic-settings with .env file support
- Database URLs, Redis URLs, TMDB API keys, CORS origins

### Quality
- ruff lint — all checks passing
- ruff format — 24 files formatted
- mypy — type checking passes on 18 source files
- Unit tests — config, models, health, and TMDB service

## Files Added (26)

| Layer | Files |
|-------|-------|
| Config | config.py |
| Database | database.py, models/base.py, models/show.py, models/watchlist.py |
| Services | services/cache.py, services/rate_limiter.py, services/tmdb.py |
| API | api/health.py, api/shows.py, main.py (updated) |
| Workers | workers/celery_app.py, workers/tasks.py |
| Migrations | alembic/, alembic.ini |
| Tests | tests/test_config.py, tests/test_health.py, tests/test_models.py, tests/test_tmdb.py |
