"""Characterization of the exact task-row write sequence of the two import workers.

``import_tasks._path_import`` and ``db_import_tasks._db_import`` run through the
REAL ``run_task_workflow``, ``update_task_status``, ``check_task_cancelled`` and
``append_task_event``; only the database session and Redis are faked. The fake
session records, in order, every commit (with a snapshot of the task row and the
index of the session that committed it), every event append, every rollback and
every published WebSocket message. Pinning that log lets the ``set_total``
harness callback (DF-15) replace the workers' direct ``update_task_status`` calls
without changing a single observable write.
"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Select

from jidou.models.task import TaskStatus
from jidou.orchestrators.path_import_orchestrator import PathImportResult

_TASK_ID = "seq-task"

Log = list[tuple[Any, ...]]


class _Recorder:
    """In-memory task row plus an ordered log of everything observable."""

    def __init__(self) -> None:
        # Mirrors the placeholder row the API creates before the worker starts.
        self.row = SimpleNamespace(
            celery_task_id=_TASK_ID,
            task_type="placeholder",
            status=TaskStatus.PENDING,
            progress_current=0,
            progress_total=0,
            progress_message=None,
            result_summary=None,
            completed_at=None,
            dry_run=False,
            event_log=[],
        )
        self.log: Log = []
        self.sessions = 0


class _FakeSession:
    def __init__(self, rec: _Recorder) -> None:
        self._rec = rec
        self.idx = rec.sessions
        rec.sessions += 1

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, stmt: object) -> MagicMock:
        if isinstance(stmt, Select):
            result = MagicMock()
            result.scalar_one_or_none.return_value = self._rec.row
            return result
        # append_task_event's single UPDATE ... event_log || <json list>
        params = stmt.compile().params  # type: ignore[attr-defined]
        payload = next(v for v in params.values() if isinstance(v, str) and v.startswith("[{"))
        event = json.loads(payload)[0]
        self._rec.log.append(("event", self.idx, event["level"], event["msg"], event.get("ctx")))
        return MagicMock()

    async def commit(self) -> None:
        r = self._rec.row
        self._rec.log.append(
            (
                "commit",
                self.idx,
                str(r.status),
                r.progress_total,
                r.progress_current,
                r.progress_message,
            )
        )

    async def rollback(self) -> None:
        self._rec.log.append(("rollback", self.idx))

    async def refresh(self, _obj: object) -> None:
        return None


@pytest.fixture
def rec() -> _Recorder:
    return _Recorder()


@pytest.fixture
def harness_env(rec: _Recorder):
    """Fake the DB session factory and Redis publishing for the real harness."""

    @asynccontextmanager
    async def fake_task_sessionmaker() -> AsyncIterator[Callable[[], _FakeSession]]:
        yield lambda: _FakeSession(rec)

    async def fake_emit(message: dict[str, object]) -> None:
        data = message.get("data")
        if message["type"] == "progress":
            rec.log.append(("emit", "progress", data))
        elif message["type"] == "event":
            return  # already captured as an "event" entry by the session
        else:
            rec.log.append(
                ("emit", message["type"], sorted(data) if isinstance(data, dict) else data)
            )

    with (
        patch("jidou.workers._harness.task_sessionmaker", fake_task_sessionmaker),
        patch("jidou.workers._harness.emit_progress", fake_emit),
        patch("jidou.services.progress.emit_progress", fake_emit),
    ):
        yield rec


def _path_result(**kw: Any) -> PathImportResult:
    base: dict[str, Any] = {
        "shows_processed": 2,
        "shows_created": 1,
        "shows_found": 1,
        "shows_not_found": 0,
        "episodes_tracked": 3,
        "episodes_unmatched": 0,
        "show_results": [],
    }
    base.update(kw)
    return PathImportResult(**base)


def _fake_path_orchestrator(*, fail_after_progress: bool) -> type:
    class FakePathOrchestrator:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def run(self, entries: object, *, on_progress: Any) -> PathImportResult:
            await on_progress(1, 2, "Show A")
            if fail_after_progress:
                raise RuntimeError("tmdb exploded")
            await on_progress(2, 2, "Show B")
            return _path_result()

    return FakePathOrchestrator


async def _run_path_import(
    entries: list[object], content: str, *, fail: bool, mode: str = "full"
) -> None:
    from jidou.workers.import_tasks import _path_import

    with (
        patch("jidou.workers.import_tasks.parse_file", return_value=entries),
        patch("jidou.workers.import_tasks.TMDBService"),
        patch("jidou.workers.import_tasks.create_llm_service"),
        patch(
            "jidou.workers.import_tasks.PathImportOrchestrator",
            _fake_path_orchestrator(fail_after_progress=fail),
        ),
    ):
        await _path_import(_TASK_ID, content, "anime", False, mode)


@pytest.mark.asyncio
async def test_path_import_success_row_sequence(harness_env: _Recorder) -> None:
    entries = [MagicMock(show_dir="A"), MagicMock(show_dir="A"), MagicMock(show_dir="B")]
    await _run_path_import(entries, "/x/A/e1.mkv\n/x/B/e1.mkv\n", fail=False)

    assert harness_env.log == EXPECTED_PATH_SUCCESS
    assert harness_env.row.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_path_import_zero_entries_warns_before_total(harness_env: _Recorder) -> None:
    """The warn event (work session) precedes the progress_total write."""
    await _run_path_import([], "garbage\n", fail=False)

    assert harness_env.log == EXPECTED_PATH_ZERO_ENTRIES


@pytest.mark.asyncio
async def test_path_import_mid_run_failure_row_sequence(harness_env: _Recorder) -> None:
    entries = [MagicMock(show_dir="A"), MagicMock(show_dir="B")]
    with pytest.raises(RuntimeError, match="tmdb exploded"):
        await _run_path_import(entries, "/x/A/e1.mkv\n/x/B/e1.mkv\n", fail=True)

    assert harness_env.log == EXPECTED_PATH_FAILURE
    assert harness_env.row.status == TaskStatus.FAILED


def _fake_restores(*, fail_in_episodes: bool) -> list[Any]:
    from jidou.workers.db_import_tasks import _RestoreCounts

    async def shows(session: Any, task_id: str, rows: list[Any], progress: Any) -> Any:
        for row in rows:
            await progress.advance(f"Shows: {row['tmdb_id']}")
        return _RestoreCounts(created=len(rows)), {}

    async def episodes(
        session: Any, task_id: str, rows: list[Any], show_id_map: Any, progress: Any
    ) -> Any:
        for _ in rows:
            await progress.advance_every(1, "Episodes")
            if fail_in_episodes:
                raise RuntimeError("db exploded")
        return _RestoreCounts(created=len(rows))

    async def watchlist(
        session: Any, task_id: str, rows: list[Any], show_id_map: Any, progress: Any
    ) -> Any:
        for _ in rows:
            progress.count()
        return _RestoreCounts(created=len(rows))

    return [shows, episodes, watchlist]


async def _run_db_import(*, fail: bool) -> None:
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps(
        {
            "shows": [{"tmdb_id": 1, "title": "S1"}, {"tmdb_id": 2, "title": "S2"}],
            "episodes": [{"tmdb_id": 10}, {"tmdb_id": 11}],
            "watchlist": [{"show_id": 1}],
        }
    )
    shows, episodes, watchlist = _fake_restores(fail_in_episodes=fail)
    with (
        patch("jidou.workers.db_import_tasks._restore_shows", shows),
        patch("jidou.workers.db_import_tasks._restore_episodes", episodes),
        patch("jidou.workers.db_import_tasks._restore_watchlist", watchlist),
    ):
        await _db_import(_TASK_ID, content)


@pytest.mark.asyncio
async def test_db_import_success_row_sequence(harness_env: _Recorder) -> None:
    await _run_db_import(fail=False)

    assert harness_env.log == EXPECTED_DB_SUCCESS
    assert harness_env.row.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_db_import_mid_run_failure_row_sequence(harness_env: _Recorder) -> None:
    with pytest.raises(RuntimeError, match="db exploded"):
        await _run_db_import(fail=True)

    assert harness_env.log == EXPECTED_DB_FAILURE
    assert harness_env.row.status == TaskStatus.FAILED


# Entry shapes: ("commit", session_idx, status, progress_total, progress_current, message),
# ("event", session_idx, level, msg, ctx), ("emit", ws_type, payload). Session 0 is the
# work session; session 1 is the harness's failure-path session.
EXPECTED_PATH_SUCCESS: Log = [
    ("commit", 0, "pending", 0, 0, None),
    ("commit", 0, "running", 0, 0, "Parsing file…"),
    ("commit", 0, "running", 2, 0, "Found 2 unique show(s) in 3 entries"),
    ("commit", 0, "running", 2, 1, "Show A"),
    ("emit", "progress", {"current": 1, "message": "Show A", "total": 2}),
    ("commit", 0, "running", 2, 2, "Show B"),
    ("emit", "progress", {"current": 2, "message": "Show B", "total": 2}),
    ("commit", 0, "completed", 2, 2, "Done — 1 created, 1 found, 3 episodes tracked"),
    ("emit", "complete", ["summary"]),
]

EXPECTED_PATH_ZERO_ENTRIES: Log = [
    ("commit", 0, "pending", 0, 0, None),
    ("commit", 0, "running", 0, 0, "Parsing file…"),
    (
        "event",
        0,
        "warn",
        "Parsed 0 usable entries from 1 non-blank line(s) — check the file's encoding (UTF-16 "
        "exports from PowerShell's `>` redirection are a common cause) and that each line is an "
        "absolute path ending in a recognized media extension.",
        None,
    ),
    ("commit", 0, "running", 0, 0, "Parsing file…"),
    ("commit", 0, "running", 0, 0, "Found 0 unique show(s) in 0 entries"),
    ("commit", 0, "running", 2, 1, "Show A"),
    ("emit", "progress", {"current": 1, "message": "Show A", "total": 2}),
    ("commit", 0, "running", 2, 2, "Show B"),
    ("emit", "progress", {"current": 2, "message": "Show B", "total": 2}),
    ("commit", 0, "completed", 2, 2, "Done — 1 created, 1 found, 3 episodes tracked"),
    ("emit", "complete", ["summary"]),
]

EXPECTED_PATH_FAILURE: Log = [
    ("commit", 0, "pending", 0, 0, None),
    ("commit", 0, "running", 0, 0, "Parsing file…"),
    ("commit", 0, "running", 2, 0, "Found 2 unique show(s) in 2 entries"),
    ("commit", 0, "running", 2, 1, "Show A"),
    ("emit", "progress", {"current": 1, "message": "Show A", "total": 2}),
    ("event", 1, "error", "Task failed: tmdb exploded", None),
    ("commit", 1, "running", 2, 1, "Show A"),
    ("commit", 1, "failed", 2, 1, "Failed: tmdb exploded"),
    ("emit", "error", ["error"]),
]

EXPECTED_DB_SUCCESS: Log = [
    ("commit", 0, "pending", 0, 0, None),
    ("commit", 0, "running", 0, 0, "Parsing backup file…"),
    ("commit", 0, "running", 5, 0, "Found 2 shows, 2 episodes, 1 watchlist entries"),
    ("commit", 0, "running", 5, 1, "Shows: 1"),
    ("emit", "progress", {"current": 1, "message": "Shows: 1", "total": 5}),
    ("commit", 0, "running", 5, 2, "Shows: 2"),
    ("emit", "progress", {"current": 2, "message": "Shows: 2", "total": 5}),
    ("commit", 0, "running", 5, 3, "Episodes: 3"),
    ("emit", "progress", {"current": 3, "message": "Episodes: 3", "total": 5}),
    ("commit", 0, "running", 5, 4, "Episodes: 4"),
    ("emit", "progress", {"current": 4, "message": "Episodes: 4", "total": 5}),
    (
        "commit",
        0,
        "completed",
        5,
        5,
        "Done — 2 shows created, 0 updated; 2 episodes created, 0 updated",
    ),
    ("emit", "complete", ["summary"]),
]

EXPECTED_DB_FAILURE: Log = [
    ("commit", 0, "pending", 0, 0, None),
    ("commit", 0, "running", 0, 0, "Parsing backup file…"),
    ("commit", 0, "running", 5, 0, "Found 2 shows, 2 episodes, 1 watchlist entries"),
    ("commit", 0, "running", 5, 1, "Shows: 1"),
    ("emit", "progress", {"current": 1, "message": "Shows: 1", "total": 5}),
    ("commit", 0, "running", 5, 2, "Shows: 2"),
    ("emit", "progress", {"current": 2, "message": "Shows: 2", "total": 5}),
    ("commit", 0, "running", 5, 3, "Episodes: 3"),
    ("emit", "progress", {"current": 3, "message": "Episodes: 3", "total": 5}),
    ("event", 1, "error", "Task failed: db exploded", None),
    ("commit", 1, "running", 5, 3, "Episodes: 3"),
    ("commit", 1, "failed", 5, 3, "Failed: db exploded"),
    ("emit", "error", ["error"]),
]
