"""Tests for ScanOrchestrator."""

from unittest.mock import AsyncMock, MagicMock

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator
from jidou.services.sftp_service import RemoteFile


def _make_remote_file(name="episode.mkv", path="/remote/show/episode.mkv", size=1000):
    return RemoteFile(name=name, path=path, size=size)


def _make_session(existing_file=None):
    """Build a mock session: first execute returns None (or existing file lookup)."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)

    file_result = MagicMock()
    file_result.scalar_one_or_none.return_value = existing_file

    session.execute = AsyncMock(return_value=file_result)
    return session


async def test_run_creates_new_files():
    """New remote files should be added to the session and committed."""
    rf1 = _make_remote_file("ep1.mkv", "/remote/ep1.mkv")
    rf2 = _make_remote_file("ep2.mkv", "/remote/ep2.mkv")

    # Two file lookups → no existing record each time
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)
    session.execute = AsyncMock(return_value=no_existing)

    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(return_value=[rf1, rf2])

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_created == 2
    assert result.files_skipped == 0
    assert result.files_found == 2
    assert result.paths_scanned == 1
    assert session.add.call_count == 2
    session.commit.assert_called_once()


async def test_run_skips_existing_files():
    """Files already tracked (any status) are counted as skipped."""
    rf = _make_remote_file()

    existing = MagicMock()
    existing.status = FileStatus.DOWNLOADED

    session = _make_session(existing_file=existing)
    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(return_value=[rf])

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_skipped == 1
    assert result.files_created == 0
    session.add.assert_not_called()


async def test_run_skips_error_files():
    """Files in ERROR status are skipped; each phase handles its own retries."""
    rf = _make_remote_file()

    existing = MagicMock()
    existing.status = FileStatus.ERROR

    session = _make_session(existing_file=existing)
    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(return_value=[rf])

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_skipped == 1
    assert result.files_created == 0
    session.add.assert_not_called()


async def test_run_dry_run_does_not_commit():
    """In dry_run mode, no rows are added and session.commit is not called."""
    rf1 = _make_remote_file("ep1.mkv", "/remote/ep1.mkv")
    rf2 = _make_remote_file("ep2.mkv", "/remote/ep2.mkv")

    session = _make_session()
    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(return_value=[rf1, rf2])

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run(dry_run=True)

    assert result.files_created == 2
    session.add.assert_not_called()
    session.commit.assert_not_called()


async def test_run_continues_on_sftp_error():
    """If SFTP listing fails for one path, other paths are still processed."""
    rf = _make_remote_file()

    session = _make_session()
    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(side_effect=[Exception("connection error"), [rf]])

    orch = ScanOrchestrator(session, sftp, ["/bad/path", "/good/path"])
    result = await orch.run()

    assert result.paths_scanned == 2
    assert result.files_created == 1


async def test_run_scans_multiple_remote_paths():
    """Each configured remote path is scanned independently."""
    rf1 = _make_remote_file("ep1.mkv", "/path1/ep1.mkv")
    rf2 = _make_remote_file("ep2.mkv", "/path2/ep2.mkv")

    session = _make_session()
    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(side_effect=[[rf1], [rf2]])

    orch = ScanOrchestrator(session, sftp, ["/path1", "/path2"])
    result = await orch.run()

    assert result.paths_scanned == 2
    assert result.files_found == 2
    assert result.files_created == 2
    assert sftp.list_remote_files_recursive.call_count == 2


async def test_run_skips_duplicate_on_constraint_violation():
    """Unique constraint violation (pgcode 23505) skips the file without failing."""
    from sqlalchemy.exc import IntegrityError

    rf = _make_remote_file()

    session = _make_session()

    orig = Exception("unique constraint violated")
    orig.pgcode = "23505"  # type: ignore[attr-defined]
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.side_effect = IntegrityError("stmt", {}, orig)
    session.begin_nested = MagicMock(return_value=nested_ctx)

    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(return_value=[rf])

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_created == 0
    assert result.files_skipped == 1
    session.commit.assert_called_once()


async def test_run_reraises_non_unique_integrity_error():
    """Non-unique integrity errors (FK violation) propagate out of run()."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    rf = _make_remote_file()

    session = _make_session()

    orig = Exception("foreign key constraint violated")
    orig.pgcode = "23503"  # type: ignore[attr-defined]
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.side_effect = IntegrityError("stmt", {}, orig)
    session.begin_nested = MagicMock(return_value=nested_ctx)

    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(return_value=[rf])

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    with pytest.raises(IntegrityError):
        await orch.run()


async def test_on_progress_called_per_path():
    """on_progress callback is called once per remote path with correct index."""
    session = _make_session()
    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(return_value=[])

    on_progress = AsyncMock()
    orch = ScanOrchestrator(session, sftp, ["/path/a", "/path/b"])
    await orch.run(on_progress=on_progress)

    assert on_progress.call_count == 2
    calls = on_progress.call_args_list
    assert calls[0].args == (1, 2, "Scanning /path/a")
    assert calls[1].args == (2, 2, "Scanning /path/b")


async def test_created_files_have_null_show_id():
    """DISCOVERED records must be created with show_id=None (global scan)."""
    rf = _make_remote_file("ep.mkv", "/remote/ep.mkv")

    added_files: list[object] = []
    session = _make_session()
    session.add = MagicMock(side_effect=lambda f: added_files.append(f))

    sftp = MagicMock()
    sftp.list_remote_files_recursive = AsyncMock(return_value=[rf])

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    await orch.run()

    assert len(added_files) == 1
    added = added_files[0]
    assert added.show_id is None  # type: ignore[union-attr]
    assert added.status.value == "discovered"  # type: ignore[union-attr]
