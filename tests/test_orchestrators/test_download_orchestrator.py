"""Tests for DownloadOrchestrator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.download_orchestrator import DownloadOrchestrator
from jidou.services.sftp_service import DownloadResult as SFTPDownloadResult


def _make_sftp_result(size=1000):
    return SFTPDownloadResult(
        remote_path="/remote/ep.mkv",
        local_path="/local/ep.mkv",
        size=size,
        dry_run=False,
        elapsed_seconds=0.5,
    )


def _make_row(
    file_id=1,
    filename="ep.mkv",
    remote_path="/remote/ep.mkv",
    show_id=10,
    local_path="/local/show",
):
    file = MagicMock()
    file.id = file_id
    file.original_filename = filename
    file.remote_path = remote_path
    file.show_id = show_id
    file.status = FileStatus.PENDING
    file.local_path = None
    file.file_size = 0

    show = MagicMock()
    show.id = show_id
    show.local_path = local_path

    return file, show


def _make_session(rows=None):
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    result = MagicMock()
    result.all.return_value = rows or []
    session.execute = AsyncMock(return_value=result)
    return session


async def test_run_downloads_pending_files():
    """PENDING files are transferred and status set to DOWNLOADED."""
    file1, show1 = _make_row(file_id=1, filename="ep1.mkv")
    file2, show2 = _make_row(file_id=2, filename="ep2.mkv")

    session = _make_session(rows=[(file1, show1), (file2, show2)])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result(size=500))

    orch = DownloadOrchestrator(session, sftp)
    result = await orch.run()

    assert result.files_downloaded == 2
    assert result.bytes_downloaded == 1000  # 500 * 2
    assert result.files_failed == 0
    assert file1.status == FileStatus.DOWNLOADED
    assert file2.status == FileStatus.DOWNLOADED
    assert sftp.download_file.call_count == 2


async def test_run_skips_files_without_local_path():
    """Files whose show has no local_path are counted as skipped."""
    file1, show1 = _make_row(local_path=None)
    show1.local_path = None

    session = _make_session(rows=[(file1, show1)])
    sftp = MagicMock()
    sftp.download_file = AsyncMock()

    orch = DownloadOrchestrator(session, sftp)
    result = await orch.run()

    assert result.files_skipped == 1
    assert result.files_downloaded == 0
    sftp.download_file.assert_not_called()


async def test_run_marks_error_on_sftp_failure():
    """If SFTP raises, the file status is set to ERROR with the error message."""
    file1, show1 = _make_row()

    session = _make_session(rows=[(file1, show1)])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=OSError("connection refused"))

    orch = DownloadOrchestrator(session, sftp)
    result = await orch.run()

    assert result.files_failed == 1
    assert result.files_downloaded == 0
    assert file1.status == FileStatus.ERROR
    assert "connection refused" in file1.error_message


async def test_run_dry_run_skips_transfer():
    """In dry_run mode, no SFTP calls are made but files_downloaded is incremented."""
    file1, show1 = _make_row(filename="ep1.mkv")
    file2, show2 = _make_row(file_id=2, filename="ep2.mkv")

    session = _make_session(rows=[(file1, show1), (file2, show2)])
    sftp = MagicMock()
    sftp.download_file = AsyncMock()

    orch = DownloadOrchestrator(session, sftp)
    result = await orch.run(dry_run=True)

    assert result.files_downloaded == 2
    assert result.dry_run is True
    sftp.download_file.assert_not_called()


async def test_run_sets_downloading_before_transfer():
    """File status is set to DOWNLOADING and flushed before the SFTP call."""
    file1, show1 = _make_row()
    status_sequence: list[FileStatus] = []

    session = _make_session(rows=[(file1, show1)])

    async def capture_flush() -> None:
        status_sequence.append(file1.status)

    session.flush = AsyncMock(side_effect=capture_flush)

    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(session, sftp)
    await orch.run()

    # First flush should capture DOWNLOADING status
    assert len(status_sequence) >= 1
    assert status_sequence[0] == FileStatus.DOWNLOADING
