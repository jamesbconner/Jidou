# Jidou

[![CI](https://github.com/jamesbconner/jidou/actions/workflows/ci.yml/badge.svg)](https://github.com/jamesbconner/jidou/actions/workflows/ci.yml)

Python 3.13 project.

## Quick start

```bash
# Install uv if you don't have it
# https://docs.astral.sh/uv/

# Create venv and install the project with dev dependencies
uv sync --extra dev

# Run the tests
uv run pytest

# Run the application
uv run jidou
```

## Project layout

```
jidou/
├── pyproject.toml          # Project metadata + tool config
├── .pre-commit-config.yaml # Pre-commit hooks
├── make.py                 # Dev task runner
├── src/
│   └── jidou/
│       ├── __init__.py
│       └── main.py
├── tests/
│   ├── __init__.py
│   └── test_main.py
├── README.md
└── CHANGELOG.md
```

## Development

```bash
# Run all checks locally (same as CI)
uv run python make.py check

# Or run individual tasks
uv run python make.py lint
uv run python make.py format
uv run python make.py types
uv run python make.py security
uv run python make.py test
```
