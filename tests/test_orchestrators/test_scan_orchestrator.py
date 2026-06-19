"""Tests for ScanOrchestrator."""

from unittest.mock import AsyncMock, MagicMock

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator
from jidou.services.sftp_service import RemoteFile


def _make_show(show_id=1, title="Test Show", remote_path="/remote/show"):
    show = MagicMock()
    show.id = show_id
    show.title = title
    show.remote_path = remote_path
    return show


def _make_remote_file(name="episode.mkv", path="/remote/show/episode.mkv", size=1000):
    return RemoteFile(name=name, path=path, size=size)


def _make_session(shows=None, existing_file=None):
    """Build a mock session: first execute returns shows, rest return file lookups."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    show_result = MagicMock()
    show_result.scalars.return_value.all.return_value = shows or []

    file_result = MagicMock()
    file_result.scalar_one_or_none.return_value = existing_file

    session.execute = AsyncMock(side_effect=[show_result] + [file_result] * 20)
    return session


async def test_run_creates_new_files():
    """New remote files should be added to the session and committed."""
    show = _make_show()
    rf1 = _make_remote_file("ep1.mkv", "/remote/ep1.mkv")
    rf2 = _make_remote_file("ep2.mkv", "/remote/ep2.mkv")

    session = _make_session(shows=[show])
    sftp = MagicMock()
    sftp.list_remote_files = AsyncMock(return_value=[rf1, rf2])

    orch = ScanOrchestrator(session, sftp)
    result = await orch.run()

    assert result.files_created == 2
    assert result.files_skipped == 0
    assert result.files_found == 2
    assert session.add.call_count == 2
    session.commit.assert_called_once()


async def test_run_skips_existing_non_error_files():
    """Files already in DOWNLOADED status should be counted as skipped."""
    show = _make_show()
    rf = _make_remote_file()

    existing = MagicMock()
    existing.status = FileStatus.DOWNLOADED

    session = _make_session(shows=[show], existing_file=existing)
    sftp = MagicMock()
    sftp.list_remote_files = AsyncMock(return_value=[rf])

    orch = ScanOrchestrator(session, sftp)
    result = await orch.run()

    assert result.files_skipped == 1
    assert result.files_created == 0
    session.add.assert_not_called()


async def test_run_resets_error_files_to_pending():
    """Files in ERROR status should be reset to PENDING and counted as created."""
    show = _make_show()
    rf = _make_remote_file()

    existing = MagicMock()
    existing.status = FileStatus.ERROR
    existing.error_message = "previous error"

    session = _make_session(shows=[show], existing_file=existing)
    sftp = MagicMock()
    sftp.list_remote_files = AsyncMock(return_value=[rf])

    orch = ScanOrchestrator(session, sftp)
    result = await orch.run()

    assert result.files_created == 1
    assert existing.status == FileStatus.PENDING
    assert existing.error_message is None
    session.add.assert_not_called()


async def test_run_dry_run_does_not_commit():
    """In dry_run mode, no rows are added and session.commit is not called."""
    show = _make_show()
    rf1 = _make_remote_file("ep1.mkv", "/remote/ep1.mkv")
    rf2 = _make_remote_file("ep2.mkv", "/remote/ep2.mkv")

    session = _make_session(shows=[show])
    sftp = MagicMock()
    sftp.list_remote_files = AsyncMock(return_value=[rf1, rf2])

    orch = ScanOrchestrator(session, sftp)
    result = await orch.run(dry_run=True)

    assert result.files_created == 2
    session.add.assert_not_called()
    session.commit.assert_not_called()


async def test_run_continues_on_sftp_error():
    """If SFTP listing fails for one show, other shows are still processed."""
    show1 = _make_show(show_id=1, remote_path="/bad/path")
    show2 = _make_show(show_id=2, remote_path="/good/path")
    rf = _make_remote_file()

    session = _make_session(shows=[show1, show2])
    sftp = MagicMock()
    sftp.list_remote_files = AsyncMock(
        side_effect=[Exception("connection error"), [rf]]
    )

    orch = ScanOrchestrator(session, sftp)
    result = await orch.run()

    assert result.shows_scanned == 2
    assert result.files_created == 1


async def test_on_progress_called_per_show():
    """on_progress callback is called once per show with correct index."""
    show1 = _make_show(show_id=1, title="Show A")
    show2 = _make_show(show_id=2, title="Show B")

    session = _make_session(shows=[show1, show2])
    sftp = MagicMock()
    sftp.list_remote_files = AsyncMock(return_value=[])

    on_progress = AsyncMock()
    orch = ScanOrchestrator(session, sftp)
    await orch.run(on_progress=on_progress)

    assert on_progress.call_count == 2
    calls = on_progress.call_args_list
    assert calls[0].args == (1, 2, "Scanning Show A")
    assert calls[1].args == (2, 2, "Scanning Show B")
