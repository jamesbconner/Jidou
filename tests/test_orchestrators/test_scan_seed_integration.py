"""Integration regression test: SeedOrchestrator's ScannedDirectory backfill must
prevent ScanOrchestrator from re-discovering an already-seeded library.

This is the critical invariant issue #355's redesign depends on: without the
backfill, the first regular scan after seeding an existing library would treat
every already-known directory as brand new and deep-walk the whole thing again,
defeating the entire point of the shallow-scan-plus-lazy-deep-walk design.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.scanned_directory import ScannedDirectory
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator
from jidou.orchestrators.seed_orchestrator import SeedOrchestrator
from jidou.services.sftp_service import RecursiveListResult, RemoteFile


class _SharedFakeDB:
    """In-memory stand-in for the two tables both orchestrators touch, shared
    across a SeedOrchestrator run followed by a ScanOrchestrator run."""

    def __init__(self) -> None:
        self.downloaded_file_paths: set[str] = set()
        self.scanned_directory_paths: set[str] = set()

    def add(self, obj: Any) -> None:
        if isinstance(obj, DownloadedFile):
            self.downloaded_file_paths.add(obj.remote_path)
        elif isinstance(obj, ScannedDirectory):
            self.scanned_directory_paths.add(obj.remote_path)
        else:
            raise AssertionError(f"unexpected object added: {obj!r}")


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeRow:
    def __init__(self, remote_path: str, status: str) -> None:
        self.remote_path = remote_path
        self.status = status


class _FakeNested:
    async def __aenter__(self) -> "_FakeNested":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakeSession:
    """Session stub backed by a _SharedFakeDB, serving both orchestrators'
    raw session.execute() usage (SeedOrchestrator's file-status lookup)."""

    def __init__(self, db: _SharedFakeDB) -> None:
        self.db = db
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.db.add(obj)

    async def commit(self) -> None:
        self.commits += 1

    def begin_nested(self) -> _FakeNested:
        return _FakeNested()

    async def execute(self, stmt: Any) -> _FakeResult:
        # Serves SeedOrchestrator's raw DownloadedFile.remote_path/status lookup.
        rows = [_FakeRow(p, FileStatus.SEEDED.value) for p in self.db.downloaded_file_paths]
        return _FakeResult(rows)


def _patched_chunked_existing_paths(db: _SharedFakeDB):
    """Patch chunked_existing_paths in both orchestrator modules to read from *db*."""

    async def fake(
        session: Any, column: Any, paths: list[str], chunk_size: int = 1_000
    ) -> set[str]:
        target = (
            db.scanned_directory_paths
            if column is ScannedDirectory.remote_path
            else db.downloaded_file_paths
        )
        return {p for p in paths if p in target}

    return (
        patch("jidou.orchestrators.scan_orchestrator.chunked_existing_paths", new=fake),
        patch("jidou.orchestrators.seed_orchestrator.chunked_existing_paths", new=fake),
    )


@pytest.mark.asyncio
async def test_scan_after_seed_finds_nothing_new_and_never_deep_walks() -> None:
    """After seeding, a scan of the same paths creates zero new files/directories
    and never deep-walks anything already seeded."""
    db = _SharedFakeDB()
    session = _FakeSession(db)
    show_dir = RemoteFile(name="Show A", path="/remote/Show A", size=0, is_dir=True)
    files = [
        RemoteFile(name="ep01.mkv", path="/remote/Show A/ep01.mkv", size=1000),
        RemoteFile(name="ep02.mkv", path="/remote/Show A/ep02.mkv", size=1000),
    ]

    patch_scan, patch_seed = _patched_chunked_existing_paths(db)

    # --- Step 1: seed the library ---
    seed_sftp = MagicMock()
    seed_sftp.list_remote_files_recursive = AsyncMock(return_value=RecursiveListResult(files=files))
    seed_sftp.list_remote_children = AsyncMock(return_value=[show_dir])

    with patch_seed:
        seed_result = await SeedOrchestrator(session, seed_sftp, ["/remote"]).run(dry_run=False)

    assert seed_result.files_seeded == 2
    assert db.downloaded_file_paths == {"/remote/Show A/ep01.mkv", "/remote/Show A/ep02.mkv"}
    assert db.scanned_directory_paths == {"/remote/Show A"}

    # --- Step 2: scan the same remote path ---
    scan_sftp = MagicMock()
    scan_sftp.max_workers = 8
    scan_sftp.list_remote_children = AsyncMock(return_value=[show_dir])
    # If the scan ever deep-walks "Show A" again, this call would need a
    # return value it doesn't have — asserting it's never called (below) is
    # the real proof, but leaving this unconfigured makes any accidental call
    # fail loudly too.
    scan_sftp.list_remote_files_recursive = AsyncMock()

    with patch_scan:
        scan_result = await ScanOrchestrator(session, scan_sftp, ["/remote"]).run()

    assert scan_result.files_created == 0
    assert scan_result.files_found == 0
    assert scan_result.dirs_discovered == 0
    scan_sftp.list_remote_files_recursive.assert_not_called()
