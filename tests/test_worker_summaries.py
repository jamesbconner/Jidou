"""Golden tests pinning each worker's WorkflowResult (summary, message, complete summary).

Each test captures the ``work`` closure a worker hands to ``run_task_workflow``, runs it against
a fixed orchestrator result and compares against literals recorded from the current code. A
refactor of the workers must leave every value byte-for-byte identical.
"""

from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators.download_orchestrator import DownloadResult
from jidou.orchestrators.parse_orchestrator import ParseResult
from jidou.orchestrators.path_import_orchestrator import PathImportResult, ShowImportResult
from jidou.orchestrators.route_orchestrator import RouteResult
from jidou.orchestrators.scan_orchestrator import ScanResult
from jidou.orchestrators.seed_orchestrator import SeedResult
from jidou.orchestrators.show_metadata_backfill_orchestrator import MetadataBackfillResult
from jidou.workers import (
    backfill_tasks,
    download_tasks,
    import_tasks,
    match_tasks,
    route_tasks,
    scan_tasks,
    seed_tasks,
)
from jidou.workers._harness import WorkflowResult

_TASK_ID = "golden-task-id"


async def _run_work(
    module_name: str,
    impl: Callable[[], Awaitable[str]],
    orchestrator: str,
    result: object,
    extra_patches: tuple[str, ...] = (),
) -> WorkflowResult:
    """Invoke a worker's async impl and run the captured ``work`` closure.

    Args:
        module_name: Worker module name under ``jidou.workers``.
        impl: Zero-arg callable that awaits the worker's async implementation.
        orchestrator: Orchestrator class name imported in the worker module.
        result: Value the orchestrator's ``run`` returns.
        extra_patches: Names in the worker module to replace with mocks (SFTP, TMDB, LLM...).

    Returns:
        The WorkflowResult produced by the captured ``work`` closure.
    """
    base = f"jidou.workers.{module_name}"
    with ExitStack() as stack:
        run_workflow = stack.enter_context(
            patch(f"{base}.run_task_workflow", new_callable=AsyncMock, return_value=_TASK_ID)
        )
        stack.enter_context(
            patch(f"{base}.{orchestrator}.run", new_callable=AsyncMock, return_value=result)
        )
        for name in extra_patches:
            stack.enter_context(patch(f"{base}.{name}"))
        await impl()
        work = run_workflow.call_args.args[2]
        wr: WorkflowResult = await work(MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
    return wr


def _snapshot(wr: WorkflowResult) -> dict[str, Any]:
    """Reduce a WorkflowResult to the fields the golden tests pin."""
    return {
        "progress_current": wr.progress_current,
        "progress_total": wr.progress_total,
        "message": wr.message,
        "result_summary": wr.result_summary,
        "complete_summary": wr.complete_summary,
        "errors": wr.errors,
    }


def _import_result(mode: str) -> PathImportResult:
    """Build a PathImportResult whose every field is non-default."""
    return PathImportResult(
        shows_processed=3,
        shows_created=1,
        shows_found=1,
        shows_not_found=1,
        episodes_tracked=7,
        episodes_unmatched=2,
        episodes_already_tracked=1,
        show_results=[
            ShowImportResult(
                show_dir="Show",
                tmdb_id=1234,
                tmdb_title="Show Title",
                action="created",
                episodes_tracked=7,
                episodes_unmatched=2,
                episodes_already_tracked=1,
                unmatched_paths=["/x/Show/ep99.mkv"],
                already_tracked_paths=["/x/Show/ep01-dup.mkv"],
            )
        ],
        mode=mode,
    )


_IMPORT_SHOW_RESULTS: list[dict[str, object]] = [
    {
        "show_dir": "Show",
        "tmdb_id": 1234,
        "tmdb_title": "Show Title",
        "action": "created",
        "episodes_tracked": 7,
        "episodes_unmatched": 2,
        "episodes_already_tracked": 1,
        "unmatched_paths": ["/x/Show/ep99.mkv"],
        "already_tracked_paths": ["/x/Show/ep01-dup.mkv"],
    }
]


def _import_summary(mode: str) -> dict[str, object]:
    """Expected import result_summary for ``mode`` (only ``mode`` varies)."""
    return {
        "shows_processed": 3,
        "shows_created": 1,
        "shows_found": 1,
        "shows_not_found": 1,
        "episodes_tracked": 7,
        "episodes_unmatched": 2,
        "episodes_already_tracked": 1,
        "show_results": _IMPORT_SHOW_RESULTS,
        "dry_run": False,
        "mode": mode,
    }


# Literals recorded from the pre-refactor code; do not edit to make a refactor pass.
GOLDEN: dict[str, dict[str, Any]] = {
    "route": {
        "progress_current": 4,
        "progress_total": 4,
        "message": "Route complete: 3 files",
        "result_summary": {"files_routed": 3, "files_failed": 1, "dry_run": True},
        "complete_summary": {"files_routed": 3, "dry_run": True},
        "errors": [],
    },
    "match": {
        "progress_current": 5,
        "progress_total": 5,
        "message": "Parse complete: 3 matched",
        "result_summary": {
            "files_processed": 5,
            "files_matched": 3,
            "files_unmatched": 1,
            "files_failed": 1,
            "dry_run": False,
        },
        "complete_summary": {"files_matched": 3, "dry_run": False},
        "errors": [],
    },
    "download": {
        "progress_current": 3,
        "progress_total": 3,
        "message": "Download complete: 2 files",
        "result_summary": {
            "files_downloaded": 2,
            "bytes_downloaded": 2048,
            "files_failed": 1,
            "dry_run": False,
        },
        "complete_summary": {"files_downloaded": 2, "dry_run": False},
        "errors": [],
    },
    "scan": {
        "progress_current": 2,
        "progress_total": 2,
        "message": (
            "Scan complete: 4 new files found, 6 already known, 1 new directories discovered"
        ),
        "result_summary": {
            "paths_scanned": 2,
            "files_found": 10,
            "files_created": 4,
            "files_skipped": 6,
            "dirs_discovered": 1,
            "dry_run": False,
        },
        "complete_summary": {"files_created": 4, "dry_run": False},
        "errors": [],
    },
    "seed": {
        "progress_current": 9,
        "progress_total": 9,
        "message": "Seed complete: 7 files seeded",
        "result_summary": {
            "paths_scanned": 2,
            "paths_failed": 0,
            "files_found": 9,
            "files_seeded": 7,
            "files_skipped": 2,
            "skipped_by_status": {"routed": 2},
            "dry_run": True,
        },
        "complete_summary": None,
        "errors": [],
    },
    "backfill": {
        "progress_current": 4,
        "progress_total": 4,
        "message": "Backfilled 3 show(s), 1 failed",
        "result_summary": {
            "shows_checked": 4,
            "shows_updated": 3,
            "shows_failed": 1,
            "updated_titles": ["A", "B", "C"],
            "failed_titles": ["D"],
            "dry_run": False,
        },
        "complete_summary": None,
        "errors": [],
    },
    "import_full": {
        "progress_current": 3,
        "progress_total": 3,
        "message": "Done \u2014 1 created, 1 found, 7 episodes tracked",
        "result_summary": _import_summary("full"),
        "complete_summary": None,
        "errors": [],
    },
    "import_shows_only": {
        "progress_current": 3,
        "progress_total": 3,
        "message": "Done \u2014 1 created, 1 found (episode matching skipped)",
        "result_summary": _import_summary("shows_only"),
        "complete_summary": None,
        "errors": [],
    },
}


async def test_route_summary() -> None:
    wr = await _run_work(
        "route_tasks",
        lambda: route_tasks._route_files(_TASK_ID, dry_run=True),
        "RouteOrchestrator",
        RouteResult(3, 1, True),
    )
    assert _snapshot(wr) == GOLDEN["route"]


async def test_match_summary() -> None:
    wr = await _run_work(
        "match_tasks",
        lambda: match_tasks._match_files(_TASK_ID, dry_run=False),
        "ParseOrchestrator",
        ParseResult(5, 3, 1, 1, False),
        extra_patches=("create_llm_service",),
    )
    assert _snapshot(wr) == GOLDEN["match"]


async def test_download_summary() -> None:
    wr = await _run_work(
        "download_tasks",
        lambda: download_tasks._download_files(_TASK_ID, dry_run=False),
        "DownloadOrchestrator",
        DownloadResult(2, 2048, 1, False),
        extra_patches=("create_sftp_service",),
    )
    assert _snapshot(wr) == GOLDEN["download"]


async def test_scan_summary() -> None:
    wr = await _run_work(
        "scan_tasks",
        lambda: scan_tasks._scan_remote(_TASK_ID, dry_run=False),
        "ScanOrchestrator",
        ScanResult(2, 10, 4, 6, 1),
        extra_patches=("create_sftp_service",),
    )
    assert _snapshot(wr) == GOLDEN["scan"]


async def test_seed_summary() -> None:
    wr = await _run_work(
        "seed_tasks",
        lambda: seed_tasks._seed_remote(_TASK_ID, dry_run=True),
        "SeedOrchestrator",
        SeedResult(2, 0, 9, 7, 2, {"routed": 2}, True),
        extra_patches=("create_sftp_service",),
    )
    assert _snapshot(wr) == GOLDEN["seed"]


async def test_backfill_summary() -> None:
    wr = await _run_work(
        "backfill_tasks",
        lambda: backfill_tasks._backfill(_TASK_ID, dry_run=False),
        "ShowMetadataBackfillOrchestrator",
        MetadataBackfillResult(4, 3, 1, ["A", "B", "C"], ["D"]),
        extra_patches=("TMDBService",),
    )
    assert _snapshot(wr) == GOLDEN["backfill"]


@pytest.mark.parametrize("mode", ["full", "shows_only"])
async def test_import_summary(mode: str) -> None:
    entry = MagicMock(show_dir="Show")
    # parse_file / task-status / event writes are patched so no DB or file parsing happens.
    with (
        patch("jidou.workers.import_tasks.parse_file", return_value=[entry]),
        patch("jidou.workers.import_tasks.append_task_event", new_callable=AsyncMock),
    ):
        wr = await _run_work(
            "import_tasks",
            lambda: import_tasks._path_import(_TASK_ID, "/x/Show/ep01.mkv", "anime", False, mode),
            "PathImportOrchestrator",
            _import_result(mode),
            extra_patches=("TMDBService", "create_llm_service"),
        )
    assert _snapshot(wr) == GOLDEN[f"import_{mode}"]
