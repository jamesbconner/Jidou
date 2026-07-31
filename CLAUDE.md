# Jidou

Python 3.13 project using the `src/` layout with `hatchling` as the build backend.

## Tooling

| Tool       | Purpose                      | Command                                 |
|------------|------------------------------|-----------------------------------------|
| uv         | Dependency mgmt + venv       | `uv sync --extra dev`                   |
| ruff       | Linting + formatting         | `uv run ruff check .` / `ruff format .` |
| mypy       | Static type checking         | `uv run mypy src/`                      |
| bandit     | Security scanning            | `uv run bandit -r src/ -l`              |
| pytest     | Testing                      | `uv run pytest`                         |
| coverage   | Code coverage                | `uv run pytest --cov=src`               |
| pre-commit | Git hook automation          | `pre-commit run --all-files`            |

## Key conventions

- All config lives in `pyproject.toml` (no separate `requirements.txt`, `setup.cfg`, etc.).
- Use `uv` for all dependency management and virtual environments — never `pip` or `python -m venv`.
- Source code under `src/jidou/`; tests under `tests/`.
- Ruff is configured for Python 3.13 target; mypy runs in strict mode.
- Runtime deps: `click`, `rich`, `pydantic`.
- Console entry points: `jidou` → `jidou.main:main`, `jidou-make` → `make:cli`.
- Use `make.py` (or `jidou-make`) for common dev tasks: `lint`, `format`, `types`, `security`, `test`, `check`, `clean`, `install`.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
