"""Integration regression test: SeedOrchestrator's ScannedDirectory backfill must
prevent ScanOrchestrator from re-discovering an already-seeded library.

This is the critical invariant issue #355's redesign depends on: without the
backfill, the first regular scan after seeding an existing library would treat
every already-known directory as brand new and deep-walk the whole thing again,
defeating the entire point of the shallow-scan-plus-lazy-deep-walk design.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators.scan_orchestrator import ScanOrchestrator
from jidou.orchestrators.seed_orchestrator import SeedOrchestrator
from jidou.services.sftp_service import RecursiveListResult, RemoteFile
from tests._fake_orchestrator_session import (
    FakeOrchestratorDB,
    FakeOrchestratorSession,
    make_chunked_existing_paths_fake,
)


def _patched_chunked_existing_paths(db: FakeOrchestratorDB):
    """Patch chunked_existing_paths in both orchestrator modules to read from *db*."""
    fake = make_chunked_existing_paths_fake(db)
    return (
        patch("jidou.orchestrators.scan_orchestrator.chunked_existing_paths", new=fake),
        patch("jidou.orchestrators.seed_orchestrator.chunked_existing_paths", new=fake),
    )


@pytest.mark.asyncio
async def test_scan_after_seed_finds_nothing_new_and_never_deep_walks() -> None:
    """After seeding, a scan of the same paths creates zero new files/directories
    and never deep-walks anything already seeded."""
    db = FakeOrchestratorDB()
    session = FakeOrchestratorSession(db)
    show_dir = RemoteFile(name="Show A", path="/remote/Show A", size=0, is_dir=True)
    files = [
        RemoteFile(name="ep01.mkv", path="/remote/Show A/ep01.mkv", size=1000),
        RemoteFile(name="ep02.mkv", path="/remote/Show A/ep02.mkv", size=1000),
    ]

    patch_scan, patch_seed = _patched_chunked_existing_paths(db)

    # --- Step 1: seed the library ---
    seed_sftp = MagicMock()
    seed_sftp.list_remote_children = AsyncMock(return_value=[show_dir])
    seed_sftp.list_remote_files_recursive_batch = AsyncMock(
        return_value=[("/remote/Show A", RecursiveListResult(files=files))]
    )

    with patch_seed:
        seed_result = await SeedOrchestrator(session, seed_sftp, ["/remote"]).run(dry_run=False)

    assert seed_result.files_seeded == 2
    assert set(db.downloaded_file_status.keys()) == {
        "/remote/Show A/ep01.mkv",
        "/remote/Show A/ep02.mkv",
    }
    assert db.scanned_directory_paths == {"/remote/Show A"}

    # --- Step 2: scan the same remote path ---
    scan_sftp = MagicMock()
    scan_sftp.max_workers = 8
    scan_sftp.list_remote_children = AsyncMock(return_value=[show_dir])
    # If the scan ever deep-walks "Show A" again, this call would need a
    # return value it doesn't have — asserting it's never called (below) is
    # the real proof, but leaving this unconfigured makes any accidental call
    # fail loudly too.
    scan_sftp.list_remote_files_recursive_batch = AsyncMock()

    with patch_scan:
        scan_result = await ScanOrchestrator(session, scan_sftp, ["/remote"]).run()

    assert scan_result.files_created == 0
    assert scan_result.files_found == 0
    assert scan_result.dirs_discovered == 0
    scan_sftp.list_remote_files_recursive_batch.assert_not_called()


@pytest.mark.asyncio
async def test_scan_after_seed_still_discovers_a_genuinely_new_directory() -> None:
    """A directory that appears AFTER seeding is still picked up by the next scan.

    Complements the "nothing new" regression above -- confirms the ScannedDirectory
    backfill doesn't over-mark and accidentally blind future scans to real new content.
    """
    db = FakeOrchestratorDB()
    session = FakeOrchestratorSession(db)
    old_dir = RemoteFile(name="Show A", path="/remote/Show A", size=0, is_dir=True)
    old_files = [RemoteFile(name="ep01.mkv", path="/remote/Show A/ep01.mkv", size=1000)]

    patch_scan, patch_seed = _patched_chunked_existing_paths(db)

    seed_sftp = MagicMock()
    seed_sftp.list_remote_children = AsyncMock(return_value=[old_dir])
    seed_sftp.list_remote_files_recursive_batch = AsyncMock(
        return_value=[("/remote/Show A", RecursiveListResult(files=old_files))]
    )
    with patch_seed:
        await SeedOrchestrator(session, seed_sftp, ["/remote"]).run(dry_run=False)

    # A new show arrives after seeding.
    new_dir = RemoteFile(name="Show B", path="/remote/Show B", size=0, is_dir=True)
    new_files = [RemoteFile(name="ep01.mkv", path="/remote/Show B/ep01.mkv", size=2000)]

    scan_sftp = MagicMock()
    scan_sftp.max_workers = 8
    scan_sftp.list_remote_children = AsyncMock(return_value=[old_dir, new_dir])
    scan_sftp.list_remote_files_recursive_batch = AsyncMock(
        return_value=[("/remote/Show B", RecursiveListResult(files=new_files))]
    )

    with patch_scan:
        scan_result = await ScanOrchestrator(session, scan_sftp, ["/remote"]).run()

    assert scan_result.dirs_discovered == 1
    assert scan_result.files_created == 1
    # Only the genuinely new directory is deep-walked -- the old one is skipped.
    scan_sftp.list_remote_files_recursive_batch.assert_called_once_with(["/remote/Show B"])
