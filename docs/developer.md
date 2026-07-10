# Developer Guide

Tooling, conventions, and workflows for contributing to Jidou.

---

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — dependency management and virtual environments
- Node.js 20+ and npm — frontend
- Docker + Docker Compose — local infrastructure (Postgres, Redis)
- [pre-commit](https://pre-commit.com/) — git hook automation

---

## First-time setup

```bash
git clone https://github.com/jamesbconner/Jidou.git
cd Jidou

# Install Python dependencies including dev extras
uv sync --extra dev

# Install frontend dependencies
cd frontend && npm install --legacy-peer-deps && cd ..

# Wire up git hooks
pre-commit install

# Start infrastructure
docker compose up postgres redis -d

# Apply migrations
uv run alembic upgrade head
```

---

## make.py — task runner

`make.py` is a thin Click-based script that wraps common dev tasks. Prefer it over raw `uv run` invocations for consistency.

```bash
# Code quality (runs all checks in sequence)
uv run python make.py check

# Individual checks
uv run python make.py lint          # ruff check
uv run python make.py format        # ruff format
uv run python make.py types         # mypy src/
uv run python make.py security      # bandit -r src/ -l
uv run python make.py test          # pytest with coverage

# Docker
uv run python make.py docker-up     # docker compose --profile default up -d
uv run python make.py docker-down   # docker compose down
uv run python make.py docker-build  # docker compose build --no-cache

# Database
uv run python make.py migrate       # alembic upgrade head
uv run python make.py seed          # insert sample show data

# Frontend
uv run python make.py build-frontend    # npm run build
uv run python make.py generate-types   # regenerate TS types from OpenAPI (API must be running)

# Health
uv run python make.py health        # GET /api/admin/health
```

---

## Code quality tools

| Tool | Purpose | Config |
|------|---------|--------|
| `ruff` | Linting + formatting | `pyproject.toml` `[tool.ruff]` |
| `mypy` | Static type checking (strict mode) | `pyproject.toml` `[tool.mypy]` |
| `bandit` | Security scanning | `pyproject.toml` `[tool.bandit]` |
| `pytest` | Testing + coverage | `pyproject.toml` `[tool.pytest]` |
| `pre-commit` | Git hook automation | `.pre-commit-config.yaml` |

All checks run in CI on every push. A PR must be green before merging.

```bash
# Run everything at once (same as CI)
uv run python make.py check
```

---

## Project layout

```
jidou/
├── src/jidou/
│   ├── api/
│   │   ├── routes/           # FastAPI route handlers (one file per resource)
│   │   ├── dependencies.py   # Shared FastAPI dependencies (auth, DB session)
│   │   └── websocket/        # WebSocket progress streaming
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/              # Pydantic request/response schemas
│   ├── services/             # External service clients (TMDB, SFTP, LLM, Redis)
│   ├── orchestrators/        # Multi-service workflow coordination
│   ├── workers/              # Celery task definitions
│   ├── config.py             # Pydantic-settings configuration
│   ├── database.py           # Async SQLAlchemy engine + session factory
│   └── main.py               # FastAPI app factory + startup
├── frontend/
│   └── src/
│       ├── api/              # Typed fetch client + WebSocket hook
│       ├── components/       # Reusable UI components
│       ├── hooks/            # TanStack Query data hooks
│       ├── pages/            # Route-level page components
│       ├── types/            # TypeScript API types (generated from OpenAPI)
│       └── utils/            # Shared utilities
├── alembic/versions/         # Database migrations
├── tests/                    # pytest test suite
├── docs/                     # Documentation
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.worker
├── make.py
└── pyproject.toml
```

### Conventions

- **One route handler file per resource** — `shows.py`, `files.py`, `watchlist.py`, etc.
- **Orchestrators coordinate, services execute** — orchestrators hold workflow logic; services hold external I/O.
- **CLI commands are thin** — parse args, build context, delegate to orchestrators.
- **No global state** — configuration and services flow through a context object or FastAPI dependency injection.
- **Async everywhere** — all I/O uses `async/await`; SQLAlchemy 2 async sessions throughout.

---

## Testing

```bash
# Full suite with coverage
uv run pytest --cov=src

# Single file
uv run pytest tests/test_shows.py -v

# Single test
uv run pytest tests/test_shows.py::test_add_show -v

# Frontend
cd frontend && npm run test
```

Coverage target is **85%**. New behaviour requires new tests; bug fixes require regression tests.

### Test conventions

- Unit tests mock external services (`TMDBService`, `SFTPService`, `LLMService`).
- Integration tests hit a real in-memory or local database.
- `tests/conftest.py` provides shared fixtures: async test client, mock DB session, auth bypass.
- Use `pytest.mark.parametrize` for data-driven cases.

---

## Adding a new API endpoint

1. Add the route handler to the appropriate `src/jidou/api/routes/*.py` file.
2. Add a Pydantic request/response schema in `src/jidou/schemas/`.
3. Register the router in `src/jidou/main.py` if it's a new file.
4. Write tests in `tests/`.
5. Run `uv run python make.py generate-types` to update the TypeScript types (API must be running).

## Adding a new Alembic migration

```bash
# After modifying a SQLAlchemy model
uv run alembic revision --autogenerate -m "short description"

# Review the generated file in alembic/versions/
# Then apply
uv run alembic upgrade head
```

Always review auto-generated migrations before applying — `--autogenerate` may miss complex changes like index renames or data migrations.

---

## TypeScript type generation

`frontend/src/types/api-generated.ts` is the raw, auto-generated OpenAPI type reference — safe to regenerate at any time, never hand-edited:

```bash
# The API must be running
uv run python make.py generate-types
```

`frontend/src/types/api.ts` is hand-maintained on top of it (see the comment at the top of that file) — most types are thin aliases (`export type X = components['schemas']['X']`) or `Omit<>`+override narrowings for fields the backend types more loosely than the frontend needs (e.g. a bare `string` where the frontend wants a literal union, or a generic dict where it wants a specific shape). A handful of types have no backend schema to alias at all — TMDB proxy endpoints return raw `dict[str, Any]`, WebSocket payloads aren't part of the REST OpenAPI spec — and stay fully hand-written.

After running `generate-types`, diff `api-generated.ts` against `api.ts`'s `Omit<>` overrides for anything you changed on the backend — a renamed or newly-loosened field shows up as a type error in `api.ts`, not a silent runtime drift.

---

## Dependency management

```bash
# Add a runtime dependency
uv add some-package

# Add a dev-only dependency
uv add --dev some-package

# Update all dependencies
uv sync --upgrade

# Never use pip directly — always use uv
```

All dependency config lives in `pyproject.toml`. There is no `requirements.txt`.
