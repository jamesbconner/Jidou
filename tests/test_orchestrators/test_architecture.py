"""Architecture guards for ``jidou.orchestrators``.

Three ratchets that may only tighten: a cyclomatic-complexity ceiling, a ban on
importing FastAPI (orchestrators must raise domain exceptions, not HTTP ones),
and a ban on importing another orchestrator's private names.
"""

import ast
import subprocess  # nosec B404 - test-only: invokes ruff via the current interpreter
import sys
from pathlib import Path

_ORCH_DIR = Path(__file__).resolve().parents[2] / "src" / "jidou" / "orchestrators"

# Measured: the worst offender is path_import_orchestrator.py _process_show_entries (21). Lower this
# as orchestrators are simplified; never raise it.
_ORCH_MAX_COMPLEXITY = 21

# Empty: orchestrators raise the domain errors in ``errors.py``; only ``jidou.main`` maps them
# to HTTP.
_KNOWN_FASTAPI_IMPORTERS: frozenset[str] = frozenset()

# Empty: shared helpers live in private modules such as ``_events``, which may be imported freely.
_KNOWN_PRIVATE_IMPORTS: frozenset[tuple[str, str]] = frozenset()


def _orchestrator_files() -> list[Path]:
    """Return every orchestrator module, sorted for stable failure output."""
    return sorted(_ORCH_DIR.glob("*.py"))


def test_orchestrators_cyclomatic_complexity_ratchet() -> None:
    """No orchestrator function may exceed the current complexity ceiling."""
    # Shell out to ruff so the rule and threshold match what CI lints with.
    proc = subprocess.run(  # nosec B603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            str(_ORCH_DIR),
            "--select",
            "C901",
            "--config",
            f"lint.mccabe.max-complexity={_ORCH_MAX_COMPLEXITY}",
            "--output-format",
            "concise",
            "--no-cache",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_orchestrators_do_not_import_fastapi() -> None:
    """Only the allowlisted modules may import fastapi, and the list must not go stale."""
    importers: set[str] = set()
    for path in _orchestrator_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            if any(n == "fastapi" or n.startswith("fastapi.") for n in names):
                importers.add(path.stem)
    assert importers == _KNOWN_FASTAPI_IMPORTERS


def test_no_private_names_imported_across_orchestrators() -> None:
    """A public orchestrator module's underscore-prefixed names stay private to it."""
    found: set[tuple[str, str]] = set()
    for path in _orchestrator_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module):
                continue
            prefix = "jidou.orchestrators."
            if not node.module.startswith(prefix):
                continue
            source = node.module[len(prefix) :]
            if source.startswith("_"):
                continue  # private helper modules may be imported freely
            found.update((path.stem, a.name) for a in node.names if a.name.startswith("_"))
    assert found == _KNOWN_PRIVATE_IMPORTS
