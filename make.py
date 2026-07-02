"""Development task runner for Jidou.

Usage:
    uv run python make.py <command>

Commands:
    check       Run all checks (lint, format, types, security, test)
    lint        Run ruff linter
    format      Run ruff formatter
    types       Run mypy type checker
    security    Run bandit security linter
    test        Run pytest (supports -k, -m, -x, --lf, --cov, -q)
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


def run(cmd: str, check: bool = False, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a shell command.

    Args:
        cmd: Shell command to execute.
        check: If True, exit with the subprocess return code on failure.
        cwd: Working directory for the command.
    """
    result = subprocess.run(cmd, shell=True, cwd=cwd)  # type: ignore[call-arg]
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
    run("uv run bandit -r src/ -l", check=True)


@cli.command()
@click.option("-k", "--keyword", metavar="EXPR", help="Filter tests by name expression.")
@click.option("-m", "--marker", metavar="EXPR", help="Filter tests by marker expression.")
@click.option("-x", "--exitfirst", is_flag=True, help="Stop after the first failure.")
@click.option("--lf", "--last-failed", "last_failed", is_flag=True, help="Re-run last-failed only.")
@click.option("--cov", is_flag=True, help="Enable coverage (term-missing + XML).")
@click.option("-q", "--quiet", is_flag=True, help="Less verbose output.")
def test(
    keyword: str | None,
    marker: str | None,
    exitfirst: bool,
    last_failed: bool,
    cov: bool,
    quiet: bool,
) -> None:
    """Run pytest with optional filters and coverage."""
    args = ["uv run pytest"]
    if quiet:
        args.append("-q")
    else:
        args.append("-v")
    if keyword:
        args.extend(["-k", f'"{keyword}"'])
    if marker:
        args.extend(["-m", f'"{marker}"'])
    if exitfirst:
        args.append("-x")
    if last_failed:
        args.append("--lf")
    if cov:
        args.extend(["--cov=src", "--cov-report=term-missing", "--cov-report=xml"])
    run(" ".join(args), check=True)


@cli.command()
def check() -> None:
    """Run all checks (lint, format, types, security, test)."""
    steps: list[tuple[str, str]] = [
        ("lint", "uv run ruff check src/ tests/"),
        ("format_check", "uv run ruff format --check src/ tests/"),
        ("types", "uv run mypy src/"),
        ("security", "uv run bandit -r src/ -l"),
        ("test", "uv run pytest -v"),
    ]
    failures = 0
    for name, cmd in steps:
        result = run(cmd)
        if result.returncode != 0:
            failures += 1
            click.echo(f"\n{name} failed (exit code {result.returncode})")
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
    """Populate DB with sample shows for local development.

    Requires a running PostgreSQL instance (DATABASE_URL env var).
    """
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from jidou.config import settings

    sample_shows = [
        {"tmdb_id": 1396, "title": "Breaking Bad", "media_type": "tv"},
        {"tmdb_id": 60735, "title": "The Flash", "media_type": "tv"},
        {"tmdb_id": 94997, "title": "House of the Dragon", "media_type": "tv"},
    ]

    async def _run() -> None:
        engine = create_async_engine(settings.database_url)
        async with engine.begin() as conn:
            for show in sample_shows:
                await conn.execute(
                    text(
                        "INSERT INTO shows (tmdb_id, title, media_type)"
                        " VALUES (:tmdb_id, :title, :media_type)"
                        " ON CONFLICT (tmdb_id) DO NOTHING"
                    ),
                    show,
                )
        await engine.dispose()

    asyncio.run(_run())
    click.echo(f"Seeded {len(sample_shows)} sample shows.")


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


@cli.command()
def generate_types() -> None:
    """Generate TypeScript types from the running API's OpenAPI spec.

    Requires the API to be running at http://localhost:8192.
    Start it first with: uv run python make.py docker-up
    """
    run(
        "npx openapi-typescript http://localhost:8192/openapi.json -o frontend/src/types/api.ts",
        check=True,
    )
    click.echo("Types written to frontend/src/types/api.ts")


@cli.command()
def build_frontend() -> None:
    """Build React SPA for production."""
    run("npm run build", cwd="frontend", check=True)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@cli.command()
def health() -> None:
    """Check service health via GET /api/admin/health.

    Requires the API to be running at http://localhost:8192.
    """
    import json

    import httpx2 as httpx

    try:
        r = httpx.get("http://localhost:8192/api/admin/health", timeout=5)
        data = r.json()
        click.echo(json.dumps(data, indent=2))
        if not data.get("healthy"):
            sys.exit(1)
    except httpx.TransportError:
        click.secho("API not reachable at http://localhost:8192", fg="red", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
