"""Tests for DownloadOrchestrator."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.download_orchestrator import DownloadOrchestrator, _local_path_for
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
    show_remote_path="/remote",
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
    show.remote_path = show_remote_path

    return file, show


def _make_session(rows=None, dry_run=False):
    """Build a mock session.

    Args:
        rows: List of (file, show) tuples to process.
        dry_run: If True, mock returns all rows via .all() (batch path).
                 If False, mock returns COUNT then one row at a time via .first().
    """
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    rows = rows or []

    if dry_run:
        result = MagicMock()
        result.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
    else:
        # Non-dry-run: COUNT query first, then one row per execute(), then None sentinel
        count_result = MagicMock()
        count_result.scalar_one.return_value = len(rows)

        row_results = []
        for row in rows:
            r = MagicMock()
            r.first.return_value = row
            row_results.append(r)

        end_result = MagicMock()
        end_result.first.return_value = None

        session.execute = AsyncMock(side_effect=[count_result, *row_results, end_result])

    return session


# ---------------------------------------------------------------------------
# _local_path_for unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "remote_path, show_remote, show_local, expected",
    [
        # Flat file at show root: basename only
        ("/sftp/Show/ep.mkv", "/sftp/Show", "/media/Show", "/media/Show/ep.mkv"),
        # Season subdirectory is mirrored into local tree
        (
            "/sftp/Show/Season 01/ep.mkv",
            "/sftp/Show",
            "/media/Show",
            "/media/Show/Season 01/ep.mkv",
        ),
        # Trailing slash on show_remote is normalised away
        (
            "/sftp/Show/Season 02/ep.mkv",
            "/sftp/Show/",
            "/media/Show",
            "/media/Show/Season 02/ep.mkv",
        ),
        # Fallback: remote_path not under show_remote → bare filename, no crash
        (
            "/other/path/ep.mkv",
            "/sftp/Show",
            "/media/Show",
            "/media/Show/ep.mkv",
        ),
        # show_remote_path is "/" (filesystem root): rstrip yields ""; must not crash
        (
            "/Show/Season 01/ep.mkv",
            "/",
            "/media/Show",
            "/media/Show/Show/Season 01/ep.mkv",
        ),
        # show_remote_path is None: fall back to bare filename, not relative-to-root
        ("/remote/Show/Season 01/ep.mkv", None, "/media/Show", "/media/Show/ep.mkv"),
        # show_remote_path is empty string: same bare-filename fallback
        ("/remote/Show/Season 01/ep.mkv", "", "/media/Show", "/media/Show/ep.mkv"),
    ],
)
def test_local_path_for(remote_path, show_remote, show_local, expected):
    """_local_path_for mirrors season subdirectories and falls back to basename."""
    result = _local_path_for(remote_path, show_remote, show_local)
    assert result == Path(expected)


def test_local_path_for_two_seasons_differ():
    """Files with identical basenames in different seasons resolve to distinct paths."""
    path_s1 = _local_path_for("/sftp/Show/Season 01/ep01.mkv", "/sftp/Show", "/media/Show")
    path_s2 = _local_path_for("/sftp/Show/Season 02/ep01.mkv", "/sftp/Show", "/media/Show")
    assert path_s1 != path_s2
    assert path_s1 == Path("/media/Show/Season 01/ep01.mkv")
    assert path_s2 == Path("/media/Show/Season 02/ep01.mkv")


# ---------------------------------------------------------------------------
# DownloadOrchestrator integration tests
# ---------------------------------------------------------------------------


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
    # 2 claim commits + 2 finish commits
    assert session.commit.call_count == 4


async def test_run_uses_season_subdirectory_path():
    """File in a season subdirectory is downloaded to the mirrored local path."""
    file1, show1 = _make_row(
        remote_path="/sftp/Show/Season 01/ep01.mkv",
        show_remote_path="/sftp/Show",
        local_path="/media/Show",
    )
    session = _make_session(rows=[(file1, show1)])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(session, sftp)
    await orch.run()

    call_args = sftp.download_file.call_args
    local_path_used = call_args[0][1]  # second positional arg to download_file
    assert local_path_used == Path("/media/Show/Season 01/ep01.mkv")


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
    # One commit to release the FOR UPDATE lock on the skipped row
    assert session.commit.call_count == 1


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
    # claim commit + error commit
    assert session.commit.call_count == 2


async def test_run_dry_run_skips_transfer():
    """In dry_run mode, no SFTP calls are made but files_downloaded is incremented."""
    file1, show1 = _make_row(filename="ep1.mkv")
    file2, show2 = _make_row(file_id=2, filename="ep2.mkv")

    session = _make_session(rows=[(file1, show1), (file2, show2)], dry_run=True)
    sftp = MagicMock()
    sftp.download_file = AsyncMock()

    orch = DownloadOrchestrator(session, sftp)
    result = await orch.run(dry_run=True)

    assert result.files_downloaded == 2
    assert result.dry_run is True
    sftp.download_file.assert_not_called()
    session.commit.assert_not_called()


async def test_run_skips_no_local_path_without_infinite_loop():
    """Files whose show has no local_path are skipped and excluded from re-selection."""
    file1, show1 = _make_row(file_id=1, local_path=None)
    show1.local_path = None
    file2, show2 = _make_row(file_id=2, filename="ep2.mkv")

    # First COUNT; then file1 (no local_path); then file2; then None sentinel.
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2

    row1_result = MagicMock()
    row1_result.first.return_value = (file1, show1)

    row2_result = MagicMock()
    row2_result.first.return_value = (file2, show2)

    end_result = MagicMock()
    end_result.first.return_value = None

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, row1_result, row2_result, end_result])

    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(session, sftp)
    result = await orch.run()

    assert result.files_skipped == 1
    assert result.files_downloaded == 1
    # The loop must not spin on file1; exactly 4 execute() calls expected
    assert session.execute.call_count == 4


async def test_run_resets_to_error_on_cancellation():
    """CancelledError mid-transfer resets file to ERROR and re-raises."""
    file1, show1 = _make_row()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    row_result = MagicMock()
    row_result.first.return_value = (file1, show1)

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, row_result])

    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=asyncio.CancelledError())

    orch = DownloadOrchestrator(session, sftp)

    with pytest.raises(asyncio.CancelledError):
        await orch.run()

    assert file1.status == FileStatus.ERROR
    assert file1.error_message == "Download interrupted"


async def test_run_sets_downloading_before_transfer():
    """Status is flushed as DOWNLOADING before SFTP call; lock is released at first commit."""
    file1, show1 = _make_row()
    status_at_flush: list[FileStatus] = []

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    row_result = MagicMock()
    row_result.first.return_value = (file1, show1)

    end_result = MagicMock()
    end_result.first.return_value = None

    session = MagicMock()

    async def capture_flush() -> None:
        status_at_flush.append(file1.status)

    session.flush = AsyncMock(side_effect=capture_flush)
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, row_result, end_result])

    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(session, sftp)
    await orch.run()

    # First flush must capture DOWNLOADING (before SFTP call)
    assert len(status_at_flush) >= 1
    assert status_at_flush[0] == FileStatus.DOWNLOADING
    # Two commits: claim (lock release) + finish (persist DOWNLOADED)
    assert session.commit.call_count == 2
