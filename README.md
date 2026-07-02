# Jidou

[![CI](https://github.com/jamesbconner/jidou/actions/workflows/ci.yml/badge.svg)](https://github.com/jamesbconner/jidou/actions/workflows/ci.yml)

Jidou ("自動", *automatic*) is a self-hosted TV show and anime management system. It tracks shows via [TMDB](https://www.themoviedb.org/), scans remote SFTP servers for downloaded files, matches files to episodes using an LLM or heuristic fallback, and routes them to your local library — with real-time progress streaming to the browser.

---

## Quick start

```bash
cp .env.example .env      # set TMDB_API_KEY at minimum
docker compose --profile default up --build -d
docker compose exec jidou-api alembic upgrade head
```

Open http://localhost:3100

---

## Documentation

| | |
|--|--|
| [Quickstart](docs/quickstart.md) | Clone → configure → running in 5 minutes |
| [Setup](docs/setup.md) | Docker, bare-metal, all env vars, SFTP, auth |
| [Features](docs/features.md) | Scanning, matching, routing, watchlist, RSS, import |
| [API Reference](docs/api.md) | REST endpoints, authentication, WebSocket |
| [Architecture](docs/architecture.md) | Design decisions and system structure |
| [Developer Guide](docs/developer.md) | Tooling, conventions, make.py, contributing |
| [Troubleshooting](docs/troubleshooting.md) | Common failures with diagnosis and fixes |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn, Python 3.13 |
| Workers | Celery 5 |
| Database | PostgreSQL 16, SQLAlchemy 2 (async), Alembic |
| Cache / Broker | Redis 7 |
| Frontend | React 18, Vite 6, TypeScript, TailwindCSS, TanStack Query |
| Containers | Docker, Docker Compose |
| Quality | ruff, mypy (strict), bandit, pytest, Vitest |
