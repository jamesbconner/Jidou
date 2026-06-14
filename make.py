"""Development task runner for Jidou.

Usage:
    uv run python make.py <command>

Commands:
    check       Run all checks (lint, format, types, security, test)
    lint        Run ruff linter
    format      Run ruff formatter
    types       Run mypy type checker
    security    Run bandit security linter
    test        Run pytest
    docker-up   Start Docker Compose services
    docker-down Stop Docker Compose services
    docker-build Rebuild Docker images
    migrate     Run Alembic migrations
    seed        Populate DB with sample data
    health      Run health checks
    generate-types Generate TypeScript types from OpenAPI spec
    build-frontend Build React SPA for production
"""

from __future__ import annotations

import subprocess
import sys

import click


def run(cmd: str, **kwargs: object) -> subprocess.CompletedProcess:
    """Run a shell command."""
    return subprocess.run(cmd, shell=True, **kwargs)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Jidou development task runner."""
    pass


@cli.command()
def lint() -> None:
    """Run ruff linter."""
    run("uv run ruff check src/ tests/")


@cli.command()
def format() -> None:
    """Run ruff formatter."""
    run("uv run ruff format src/ tests/")


@cli.command()
def types() -> None:
    """Run mypy type checker."""
    run("uv run mypy src/")


@cli.command()
def security() -> None:
    """Run bandit security linter."""
    run("uv run bandit -r src/ -ll")


@cli.command()
def test() -> None:
    """Run pytest."""
    run("uv run pytest -v")


@cli.command()
def check() -> None:
    """Run all checks (lint, format, types, security, test)."""
    lint()
    format()
    types()
    security()
    test()


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--profile", default="default", help="Docker Compose profile to use")
def docker_up(profile: str) -> None:
    """Start Docker Compose services."""
    run(f"docker compose --profile {profile} up --build -d")


@cli.command()
@click.option("--profile", default="default", help="Docker Compose profile to use")
def docker_down(profile: str) -> None:
    """Stop Docker Compose services."""
    run(f"docker compose --profile {profile} down")


@cli.command()
def docker_build() -> None:
    """Rebuild Docker images."""
    run("docker compose build --no-cache")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@cli.command()
def migrate() -> None:
    """Run Alembic migrations."""
    run("uv run alembic upgrade head")


@cli.command()
def seed() -> None:
    """Populate DB with sample data."""
    click.echo("Seed command not yet implemented.")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@cli.command()
def generate_types() -> None:
    """Generate TypeScript types from OpenAPI spec."""
    click.echo("Generate types command not yet implemented (requires running API).")
    sys.exit(0)


@cli.command()
def build_frontend() -> None:
    """Build React SPA for production."""
    click.echo("Build frontend command not yet implemented (requires frontend setup).")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@cli.command()
def health() -> None:
    """Run health checks."""
    click.echo("Health check command not yet implemented (requires running API).")
    sys.exit(0)


if __name__ == "__main__":
    cli()