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


def run(cmd: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command.

    Args:
        cmd: Shell command to execute.
        check: If True, exit with the subprocess return code on failure.
    """
    result = subprocess.run(cmd, shell=True)  # type: ignore[call-arg]
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


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
    run("uv run ruff check src/ tests/", check=True)


@cli.command()
def format() -> None:
    """Run ruff formatter."""
    run("uv run ruff format src/ tests/", check=True)


@cli.command()
def format_check() -> None:
    """Check ruff formatting (read-only)."""
    run("uv run ruff format --check src/ tests/", check=True)


@cli.command()
def types() -> None:
    """Run mypy type checker."""
    run("uv run mypy src/", check=True)


@cli.command()
def security() -> None:
    """Run bandit security linter."""
    run("uv run bandit -r src/ -ll", check=True)


@cli.command()
def test() -> None:
    """Run pytest."""
    run("uv run pytest -v", check=True)


@cli.command()
def check() -> None:
    """Run all checks (lint, format, types, security, test)."""
    failures = 0
    steps = [lint, format_check, types, security, test]
    for step in steps:
        try:
            step()
        except SystemExit as exc:
            failures += 1
            click.echo(f"\n{step.__name__}() failed (exit code {exc.code})")
    if failures:
        click.echo(f"\n{failures}/{len(steps)} step(s) failed")
        sys.exit(failures)


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--profile", default="default", help="Docker Compose profile to use")
def docker_up(profile: str) -> None:
    """Start Docker Compose services."""
    run(f"docker compose --profile {profile} up --build -d", check=True)


@cli.command()
@click.option("--profile", default="default", help="Docker Compose profile to use")
def docker_down(profile: str) -> None:
    """Stop Docker Compose services."""
    run(f"docker compose --profile {profile} down", check=True)


@cli.command()
@click.option("--profile", default="default", help="Docker Compose profile to use")
def docker_build(profile: str) -> None:
    """Rebuild Docker images."""
    run(f"docker compose --profile {profile} build --no-cache", check=True)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@cli.command()
def migrate() -> None:
    """Run Alembic migrations."""
    run("uv run alembic upgrade head", check=True)


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
