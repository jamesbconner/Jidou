"""Make script for common development tasks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parent


def _run(cmd: list[str], dry_run: bool = False) -> int:
    """Run a command, optionally in dry-run mode."""
    if dry_run:
        click.secho(f"  [dry-run] {' '.join(cmd)}", fg="yellow")
        return 0
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode


@click.group()
@click.version_option()
def cli() -> None:
    """Jidou development tasks."""
    pass


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show commands without running.")
def lint(dry_run: bool) -> None:
    """Run linter (ruff check)."""
    click.secho("Linting...", fg="green")
    sys.exit(_run(["uv", "run", "ruff", "check", "."], dry_run))


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show commands without running.")
def format(dry_run: bool) -> None:
    """Run formatter (ruff format)."""
    click.secho("Formatting...", fg="green")
    sys.exit(_run(["uv", "run", "ruff", "format", "."], dry_run))


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show commands without running.")
def types(dry_run: bool) -> None:
    """Run type checker (mypy)."""
    click.secho("Type checking...", fg="green")
    sys.exit(_run(["uv", "run", "mypy", "src/"], dry_run))


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show commands without running.")
def security(dry_run: bool) -> None:
    """Run security scan (bandit)."""
    click.secho("Security scanning...", fg="green")
    sys.exit(_run(["uv", "run", "bandit", "-r", "src/", "-ll"], dry_run))


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show commands without running.")
@click.option("--cov/--no-cov", default=True, help="Include coverage report.")
def test(dry_run: bool, cov: bool) -> None:
    """Run tests (pytest)."""
    click.secho("Running tests...", fg="green")
    cmd = ["uv", "run", "pytest", "-v"]
    if cov:
        cmd.extend(["--cov=src", "--cov-report=term-missing"])
    sys.exit(_run(cmd, dry_run))


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show commands without running.")
def check(dry_run: bool) -> None:
    """Run all checks (lint, format, types, security, test)."""
    click.secho("Running all checks...", fg="green")
    errors = 0
    errors += _run(["uv", "run", "ruff", "check", "."], dry_run)
    errors += _run(["uv", "run", "ruff", "format", "--check", "."], dry_run)
    errors += _run(["uv", "run", "mypy", "src/"], dry_run)
    errors += _run(["uv", "run", "bandit", "-r", "src/", "-ll"], dry_run)
    errors += _run(
        ["uv", "run", "pytest", "-v", "--cov=src", "--cov-report=term-missing"],
        dry_run,
    )
    sys.exit(errors)


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show commands without running.")
def clean(dry_run: bool) -> None:
    """Remove build artifacts and caches."""
    import shutil

    click.secho("Cleaning...", fg="green")
    for pattern in [
        "**/__pycache__",
        "*.pyc",
        "*.pyo",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".bandit",
        "htmlcov",
        ".coverage",
        ".coverage.*",
        "build",
        "dist",
        "*.egg-info",
    ]:
        for path in PROJECT_ROOT.glob(pattern):
            if path.name == "src":
                continue
            if dry_run:
                click.secho(f"  [dry-run] rm {path}", fg="yellow")
            else:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                click.secho(f"  removed {path.relative_to(PROJECT_ROOT)}", fg="cyan")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show commands without running.")
def install(dry_run: bool) -> None:
    """Install the project with dev dependencies."""
    click.secho("Installing dependencies...", fg="green")
    sys.exit(_run(["uv", "sync", "--extra", "dev"], dry_run))


if __name__ == "__main__":
    cli()
