"""Architecture guards for ``jidou.services``.

Two guards: a cyclomatic-complexity ratchet (the ceiling only ever goes down) and a layering
guard that stops services from importing the API or orchestrator layers above them.
"""

import ast
import subprocess  # nosec B404 - runs ruff from the current interpreter, no shell involved
import sys
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parent.parent / "src" / "jidou" / "services"

# Measured maximum is 10 (``show_creation.get_or_create_show_from_tmdb``); refactors lower this,
# never raise it.
_SERVICES_MAX_COMPLEXITY = 10

# Shrinks to empty: Task 10 removes the remaining two.
_KNOWN_UPWARD_IMPORTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("show_creation", "jidou.orchestrators.tmdb_orchestrator"),
        ("show_creation", "jidou.orchestrators.alias_orchestrator"),
    }
)

_UPPER_LAYERS = ("jidou.api", "jidou.orchestrators")


def test_services_cyclomatic_complexity_ratchet() -> None:
    """No function in services may exceed the recorded McCabe complexity."""
    result = subprocess.run(  # nosec B603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            str(SERVICES_DIR),
            "--select",
            "C901",
            "--config",
            f"lint.mccabe.max-complexity={_SERVICES_MAX_COMPLEXITY}",
            "--output-format",
            "concise",
            "--no-cache",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout


def _is_upper_layer(module: str) -> bool:
    """Return True if ``module`` is, or lives under, an upper layer package."""
    return any(module == layer or module.startswith(f"{layer}.") for layer in _UPPER_LAYERS)


def test_services_do_not_import_upper_layers() -> None:
    """Services must not import ``jidou.api`` / ``jidou.orchestrators`` except known cases."""
    found: set[tuple[str, str]] = set()
    paths = sorted(SERVICES_DIR.glob("*.py"))
    # Non-vacuous: the scan must really cover the services, including the former offender.
    assert len(paths) > 10
    assert "pubsub_subscriber" in {p.stem for p in paths}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Walk every node so function-local (deferred) imports are caught too.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                targets = [node.module]
            else:
                continue
            found.update((path.stem, t) for t in targets if _is_upper_layer(t))
    # Exact equality so a stale allowlist entry fails as well as a new violation.
    assert found == _KNOWN_UPWARD_IMPORTS
