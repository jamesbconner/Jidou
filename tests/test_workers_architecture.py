"""Architecture guards for ``jidou.workers``.

Three guards: a cyclomatic-complexity ratchet (the ceiling only ever goes down), an include-list
guard that keeps ``celery_app.conf.include`` in step with the task modules on disk, and a
visibility-timeout invariant that keeps the broker from redelivering a still-running task.
"""

import importlib
import subprocess  # nosec B404 - runs ruff from the current interpreter, no shell involved
import sys
from pathlib import Path

from jidou.workers.celery_app import celery_app

WORKERS_DIR = Path(__file__).resolve().parent.parent / "src" / "jidou" / "workers"

# Measured max is 9 (``run_task_workflow``) after the db-import decomposition; only ever lower this.
_WORKERS_MAX_COMPLEXITY = 8


def test_workers_cyclomatic_complexity_ratchet() -> None:
    """No function in workers may exceed the recorded McCabe complexity."""
    result = subprocess.run(  # nosec B603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            str(WORKERS_DIR),
            "--select",
            "C901",
            "--config",
            f"lint.mccabe.max-complexity={_WORKERS_MAX_COMPLEXITY}",
            "--output-format",
            "concise",
            "--no-cache",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout


def test_every_task_module_is_included() -> None:
    """Every worker module defining a ``@shared_task`` must be in Celery's include list.

    A task module missing from ``include`` is never imported by the worker, so its tasks silently
    fail to register and messages for them are rejected as unknown.
    """
    task_modules = {
        f"jidou.workers.{path.stem}"
        for path in WORKERS_DIR.glob("*.py")
        if "@shared_task" in path.read_text(encoding="utf-8")
    }
    assert task_modules == set(celery_app.conf.include)


def test_visibility_timeout_exceeds_every_task_time_limit() -> None:
    """The broker visibility timeout must exceed every registered task's hard time limit.

    With ``task_acks_late`` the ack is withheld until a task finishes; if the visibility timeout
    were shorter than a task's runtime, Redis would redeliver it while it is still running.
    """
    for module in celery_app.conf.include:
        importlib.import_module(module)

    visibility_timeout = celery_app.conf.broker_transport_options["visibility_timeout"]
    default_limit = celery_app.conf.task_time_limit
    jidou_tasks = [task for name, task in celery_app.tasks.items() if name.startswith("jidou.")]
    assert jidou_tasks, "no jidou tasks registered; the include list failed to load"
    for task in jidou_tasks:
        limit = task.time_limit or default_limit
        assert visibility_timeout > limit, (
            f"{task.name}: time limit {limit}s >= visibility_timeout {visibility_timeout}s"
        )
