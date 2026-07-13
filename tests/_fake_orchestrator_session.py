"""Shared fake AsyncSession/DB helpers for ScanOrchestrator/SeedOrchestrator tests.

A minimal in-memory stand-in for the parts of AsyncSession that both
orchestrators touch directly -- add(), commit(), begin_nested(), and the one
raw execute() SeedOrchestrator still issues for per-file status lookups.
Existence checks routed through chunked_existing_paths must be patched
separately via make_chunked_existing_paths_fake() below, since this module
doesn't attempt to introspect SQLAlchemy Core statements.

A single FakeOrchestratorDB instance can be shared across multiple sequential
orchestrator runs (e.g. seed then scan) to assert on end-to-end state, which
is what the seed/scan integration regression test needs.
"""

from __future__ import annotations

from typing import Any


class FakeOrchestratorDB:
    """In-memory stand-in for the downloaded_files/scanned_directories tables."""

    def __init__(
        self,
        existing_files: dict[str, str] | None = None,
        existing_dirs: set[str] | None = None,
    ) -> None:
        self.downloaded_file_status: dict[str, str] = dict(existing_files or {})
        self.scanned_directory_paths: set[str] = set(existing_dirs or set())

    def record(self, obj: Any) -> None:
        """Update in-memory state for a newly add()-ed ORM object."""
        from jidou.models.downloaded_file import DownloadedFile
        from jidou.models.scanned_directory import ScannedDirectory

        if isinstance(obj, DownloadedFile):
            status = obj.status.value if hasattr(obj.status, "value") else str(obj.status)
            self.downloaded_file_status[obj.remote_path] = status
        elif isinstance(obj, ScannedDirectory):
            self.scanned_directory_paths.add(obj.remote_path)
        else:
            raise AssertionError(f"unexpected object added to FakeOrchestratorDB: {obj!r}")


class FakeNested:
    """Minimal async context manager for begin_nested()."""

    async def __aenter__(self) -> FakeNested:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False  # propagate exceptions


class FakeResult:
    """Minimal stand-in for a SQLAlchemy Result -- only .all() is used."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class FakeRow:
    """Minimal stand-in for a (remote_path, status) result row."""

    def __init__(self, remote_path: str, status: str) -> None:
        self.remote_path = remote_path
        self.status = status


class FakeOrchestratorSession:
    """Fake AsyncSession for ScanOrchestrator/SeedOrchestrator tests.

    Tracks every object passed to add() (both in ``.added`` for direct
    inspection and in the backing ``FakeOrchestratorDB`` for cross-run
    state), and answers the one raw execute() SeedOrchestrator issues
    directly (a DownloadedFile.remote_path/status lookup) from the DB's
    ``downloaded_file_status``.
    """

    def __init__(self, db: FakeOrchestratorDB | None = None) -> None:
        self.db = db or FakeOrchestratorDB()
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self.db.record(obj)

    async def commit(self) -> None:
        self.commits += 1

    def begin_nested(self) -> FakeNested:
        return FakeNested()

    async def execute(self, stmt: Any) -> FakeResult:
        rows = [FakeRow(path, status) for path, status in self.db.downloaded_file_status.items()]
        return FakeResult(rows)


def make_chunked_existing_paths_fake(db: FakeOrchestratorDB):  # type: ignore[no-untyped-def]
    """Return an async fake for ``chunked_existing_paths`` backed by *db*.

    Dispatches on whether the ``column`` argument is
    ``DownloadedFile.remote_path`` or ``ScannedDirectory.remote_path`` so one
    fake serves both orchestrators' existence checks.

    Args:
        db: The shared in-memory DB state to answer existence checks from.

    Returns:
        An async callable matching ``chunked_existing_paths``'s signature.
    """
    from jidou.models.downloaded_file import DownloadedFile
    from jidou.models.scanned_directory import ScannedDirectory

    async def fake(
        session: Any, column: Any, paths: list[str], chunk_size: int = 1_000
    ) -> set[str]:
        if column is ScannedDirectory.remote_path:
            target = db.scanned_directory_paths
        elif column is DownloadedFile.remote_path:
            target = set(db.downloaded_file_status.keys())
        else:
            raise AssertionError(f"unexpected column: {column!r}")
        return {p for p in paths if p in target}

    return fake
