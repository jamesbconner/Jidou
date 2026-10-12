# Developer Guide

Tooling, conventions, and workflows for contributing to Jidou.

---

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — dependency management and virtual environments
- Node.js 24+ and npm — frontend (`npm ci` needs Node 24 or newer; `frontend/package.json` declares `engines.node >=24`)
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
uv run python make.py format-check  # ruff format --check (read-only; this is what CI runs)
uv run python make.py types         # mypy src/
uv run python make.py security      # bandit -r src/ -l
uv run python make.py test          # pytest with coverage

# Docker
uv run python make.py docker-up     # docker compose --profile default up --build -d
uv run python make.py docker-down   # docker compose --profile default down
uv run python make.py docker-build  # docker compose --profile default build --no-cache

# Database
uv run python make.py migrate       # alembic upgrade head
uv run python make.py seed          # insert sample show data

# Frontend
uv run python make.py build-frontend    # npm run build
uv run python make.py generate-types   # regenerate TS types from OpenAPI (API must be running)
uv run python make.py export-openapi <file>  # write the OpenAPI spec to <file> (no server needed)

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
│       ├── types/            # api-generated.ts (from OpenAPI) + hand-maintained api.ts on top
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

- **One route handler file per resource** — `files.py`, `watchlist.py`, etc. Large resources are split into sub-resource modules that share a router prefix: `shows.py`, `tmdb_proxy.py`, `show_episodes.py`, `show_local_files.py` under `/shows`, and `rss_feeds.py`, `rss_subscriptions.py`, `rss_publish.py` under `/rss`. Registration order in `main.py` matters for literal-versus-parameter paths (`tmdb_proxy` before `shows`).
- **Orchestrators coordinate, services execute** — orchestrators hold workflow logic; services hold external I/O.
- **CLI commands are thin** — parse args, build context, delegate to orchestrators.
- **No global state** — configuration and services flow through a context object or FastAPI dependency injection.
- **Async everywhere** — all I/O uses `async/await`; SQLAlchemy 2 async sessions throughout.
- **Extract shared logic instead of duplicating it across similar entry points** — e.g. `services/episode_file_matching.py` (episode matching shared between bulk path-import and the show-scoped "Scan Local Files" feature) and `services/synthetic_file.py` (shared between bulk import and manual file-linking). When a second feature needs logic a first one already has, pull it into `services/` rather than copying it.
- **Frontend UI primitives live in `components/ui/`** — `Modal`, `Button`, `Card`, `Badge`, backed by `@layer components` recipes in `index.css`. New modals, cards, and badge-style pills should build on these instead of hand-typing Tailwind utility strings, which drifts visibly across call sites over time (see [Architecture — Shared UI primitives](architecture.md#shared-ui-primitives)).

---

## Frontend structure

All paths below are under `frontend/src/`.

### Hooks boundary

Pages and components never call the API client or the query client
themselves. They read and mutate server data through a hook in `hooks/`, so
cache keys and invalidation live in one layer. ESLint enforces this in
`frontend/eslint.config.js` for `pages/**` and `components/**`: importing
`@/api/client` (or any `**/api/client` relative spelling) and calling
`useQueryClient` are both errors. Tests are outside the rule.

### Query keys and shared hooks

- Each data hook module exports a key factory (`showKeys`, `fileKeys`,
  `taskKeys`, `rssKeys`, `configKeys`, `dashboardKeys`, `calendarKeys`,
  `orphanKeys`, `watchlistKeys`, `settingsKeys`, `adminKeys`). Build query
  keys and invalidations from the factory, not from string literals.
- `hooks/invalidation.ts` holds `invalidateShowsAndFiles`, the shared
  refetch for mutations that re-link files.
- `useConfig` (`hooks/useConfig.ts`) is the single query for the server's
  read-only `/config`, so every consumer shares one cache entry.
- `useTaskUntilDone` (`hooks/useTasks.ts`) polls one task by id until it
  reaches a terminal status (`TERMINAL_TASK_STATUSES`), then stops. Pass
  `null` before the task exists.

### Per-tab page layout

Large pages are split so the route file wires tabs and sections together,
and the pieces live in a folder named after the page:

- `pages/settings/`: `GeneralTab`, `ServicesTab`, `FeaturesTab`, `DataTab`,
  `LiveImportTask`, `rows`
- `pages/shows/`: `LibraryTab`, `MissingTab`, `DataQualityTab`,
  `ShowsHeader`, `ShowsSearchModal`, `styles`
- `pages/showDetail/`: `EpisodesCard`, `ShowDetailSections`,
  `ShowDetailModals`, `WatchlistControls`, `useShowDetailData`,
  `modalState`, `episodeStats`
- `pages/files/`: `FilesTable`, `FilesToolbar`, `InlineEditors`
- `pages/rss/`: `RssHeader`, `SubscriptionFilters`, `rssFilters`

Modals follow the same pattern: `components/linkFile/`,
`components/rematch/` and `components/resolveFile/` hold the panes and hooks
extracted from `LinkFileModal`, `RematchModal` and `ResolveFileModal`.

### Complexity budget

ESLint's `complexity` rule is a ratchet, currently `25`, and it may only be
lowered. `RematchModal` and `ResolveFileModal` sit at the limit; every other
function is at or below it. Test files are exempt. The ratchet came down from
51 when FE-7 split `ShowDetail`, `Shows`, `FeaturesTab`, `ResolveFileModal`,
`AddShowFromFeedPane`, `Files`, `RSS`, `LinkFileModal`, `RematchModal`,
`ServiceRow`, `ScanLocalFilesModal` and `FeedFormModal`. When you touch a
function near the limit, extract a helper or subcomponent rather than raising
the number.

### Node version

The frontend needs Node 24 or newer for `npm ci` (`engines.node >=24`).

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
5. Regenerate the TypeScript types (see [TypeScript type generation](#typescript-type-generation)); CI fails if `frontend/src/types/api-generated.ts` is stale.

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

### CI drift check

The `frontend` job in `.github/workflows/ci.yml` fails when the committed `api-generated.ts` differs from what the backend's current OpenAPI spec generates. It runs `make.py export-openapi` (which writes `app.openapi()` to a file without starting a server), generates types with the pinned `openapi-typescript@7.13.0`, and diffs the result against the committed file. To regenerate without a running API, exactly as CI does, from the repo root:

```bash
uv run python make.py export-openapi /tmp/openapi.json
cd frontend && npx openapi-typescript@7.13.0 /tmp/openapi.json -o src/types/api-generated.ts
```

Use that pinned version: a different `openapi-typescript` version can format the output differently and trip the check.

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
