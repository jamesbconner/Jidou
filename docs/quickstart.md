# Quickstart

Get Jidou running in under five minutes using Docker.

## Prerequisites

- [Docker + Docker Compose](https://docs.docker.com/get-docker/)
- A [TMDB API key](https://www.themoviedb.org/settings/api) (free)

## 1. Configure environment

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```env
TMDB_API_KEY=your_key_here
```

Everything else has working defaults for local development.

## 2. Start all services

```bash
docker compose --profile default up --build -d
# or via make.py:
uv run python make.py docker-up
```

This starts PostgreSQL, Redis, the FastAPI backend, the Celery worker, and the React frontend.

## 3. Run database migrations

```bash
docker compose exec jidou-api alembic upgrade head
# or:
uv run python make.py migrate
```

## 4. Open the UI

| Service | URL |
|---------|-----|
| React UI | http://localhost:3100 |
| API + Swagger | http://localhost:8192/docs |

## 5. Add your first show

1. Click **Shows** → **Add Show**.
2. Search for a title (e.g. `Breaking Bad`).
3. Click the result to add it to your library.

<!-- screenshot: add-show-search -->

Episodes are synced from TMDB automatically on creation.

## What a running task looks like

Trigger a **Scan** from the Tasks page and watch it stream live — a progress bar, the current file being processed, and an expandable event log entry for every file it touches.

<!-- screenshot: tasks-live-progress -->

## Next steps

- [Full setup guide](setup.md) — SFTP, LLM, bare-metal install, API key auth
- [Features overview](features.md) — scanning, matching, routing, watchlist
- [Troubleshooting](troubleshooting.md) — common failures and fixes
