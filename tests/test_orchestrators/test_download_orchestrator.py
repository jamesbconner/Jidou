"""Tests for DownloadOrchestrator."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.download_orchestrator import (
    DownloadOrchestrator,
    _staging_path_for,
)
from jidou.services.sftp_service import DownloadResult as SFTPDownloadResult

_STAGING = "/data/staging"


def _make_sftp_result(size=1000):
    return SFTPDownloadResult(
        remote_path="/remote/ep.mkv",
        local_path=f"{_STAGING}/remote/ep.mkv",
        size=size,
        dry_run=False,
        elapsed_seconds=0.5,
    )


def _make_file(
    file_id=1,
    filename="ep.mkv",
    remote_path="/remote/ep.mkv",
):
    file = MagicMock()
    file.id = file_id
    file.original_filename = filename
    file.remote_path = remote_path
    file.status = FileStatus.DISCOVERED
    file.local_path = None
    file.file_size = 0
    return file


def _make_session(files=None, dry_run=False):
    """Build a mock session for the batch-parallel orchestrator.

    Non-dry-run sequence:
      1. COUNT query  → scalar_one()
      2. Batch query  → scalars().all()
      3. Empty query  → scalars().all() returning [] (loop exit)
    """
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    files = files or []

    if dry_run:
        result = MagicMock()
        result.scalars.return_value.all.return_value = files
        session.execute = AsyncMock(return_value=result)
    else:
        count_result = MagicMock()
        count_result.scalar_one.return_value = len(files)

        batch_result = MagicMock()
        batch_result.scalars.return_value.all.return_value = files

        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []

        session.execute = AsyncMock(side_effect=[count_result, batch_result, empty_result])

    return session


# ---------------------------------------------------------------------------
# _staging_path_for unit tests
# ---------------------------------------------------------------------------


def test_staging_path_mirrors_remote():
    """Remote path structure is mirrored under the staging root."""
    result = _staging_path_for("/downloads/shows/ShowName_S01E01.mkv", "/data/staging")
    assert result == Path("/data/staging/downloads/shows/ShowName_S01E01.mkv")


def test_staging_path_strips_leading_slash():
    """Leading slash on remote_path does not create double-slash in result."""
    result = _staging_path_for("/ep.mkv", "/staging")
    assert result == Path("/staging/ep.mkv")


def test_staging_path_flat_file():
    """Flat remote file lands at staging root."""
    result = _staging_path_for("flat.mkv", "/staging")
    assert result == Path("/staging/flat.mkv")


def test_staging_path_traversal_raises():
    """Path containing .. that escapes the staging root raises ValueError."""
    import pytest

    with pytest.raises(ValueError, match="Path traversal detected"):
        _staging_path_for("/downloads/../../../etc/passwd", "/data/staging")


# ---------------------------------------------------------------------------
# DownloadOrchestrator integration tests
# ---------------------------------------------------------------------------


async def test_run_downloads_discovered_files():
    """DISCOVERED files are transferred and status set to DOWNLOADED."""
    file1 = _make_file(file_id=1, filename="ep1.mkv", remote_path="/remote/ep1.mkv")
    file2 = _make_file(file_id=2, filename="ep2.mkv", remote_path="/remote/ep2.mkv")

    session = _make_session(files=[file1, file2])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result(size=500))

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    result = await orch.run()

    assert result.files_downloaded == 2
    assert result.bytes_downloaded == 1000  # 500 * 2
    assert result.files_failed == 0
    assert file1.status == FileStatus.DOWNLOADED
    assert file2.status == FileStatus.DOWNLOADED
    assert sftp.download_file.call_count == 2
    # 1 commit to release locks (DOWNLOADING) + 1 commit to persist results
    assert session.commit.call_count == 2


async def test_run_sets_staging_local_path():
    """Downloaded file gets a local_path under the staging root."""
    file1 = _make_file(remote_path="/downloads/shows/ShowName_S01E01.mkv")
    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(session, sftp, "/staging")
    await orch.run()

    call_args = sftp.download_file.call_args
    local_path_used = call_args[0][1]  # second positional arg to download_file
    assert local_path_used == Path("/staging/downloads/shows/ShowName_S01E01.mkv")


async def test_run_marks_error_on_sftp_failure():
    """If SFTP raises, the file status is set to ERROR with the error message."""
    file1 = _make_file()

    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=OSError("connection refused"))

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    result = await orch.run()

    assert result.files_failed == 1
    assert result.files_downloaded == 0
    assert file1.status == FileStatus.ERROR
    assert "connection refused" in file1.error_message
    # claim commit + error commit
    assert session.commit.call_count == 2


async def test_run_dry_run_skips_transfer():
    """In dry_run mode, no SFTP calls are made but files_downloaded is incremented."""
    file1 = _make_file(file_id=1, filename="ep1.mkv")
    file2 = _make_file(file_id=2, filename="ep2.mkv")

    session = _make_session(files=[file1, file2], dry_run=True)
    sftp = MagicMock()
    sftp.download_file = AsyncMock()

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    result = await orch.run(dry_run=True)

    assert result.files_downloaded == 2
    assert result.dry_run is True
    sftp.download_file.assert_not_called()
    session.commit.assert_not_called()


async def test_run_resets_to_error_on_cancellation():
    """CancelledError from a download is caught and recorded as ERROR, not re-raised."""
    file1 = _make_file()

    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=asyncio.CancelledError())

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    result = await orch.run()

    assert result.files_failed == 1
    assert result.files_downloaded == 0
    assert file1.status == FileStatus.ERROR
    assert file1.error_message == "Download interrupted"
    assert session.commit.call_count == 2  # claim + error


async def test_run_sets_downloading_before_transfer():
    """Status is flushed as DOWNLOADING before transfers begin."""
    file1 = _make_file()
    status_at_flush: list[FileStatus] = []

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    batch_result = MagicMock()
    batch_result.scalars.return_value.all.return_value = [file1]

    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []

    session = MagicMock()

    async def capture_flush() -> None:
        status_at_flush.append(file1.status)

    session.flush = AsyncMock(side_effect=capture_flush)
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, batch_result, empty_result])

    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    await orch.run()

    # First flush must see DOWNLOADING (before gather)
    assert len(status_at_flush) >= 1
    assert status_at_flush[0] == FileStatus.DOWNLOADING
    assert session.commit.call_count == 2
