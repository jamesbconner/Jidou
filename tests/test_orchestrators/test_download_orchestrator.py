"""Tests for DownloadOrchestrator."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.downloaded_file import FileStatus, IgnoredReason
from jidou.orchestrators.download_orchestrator import (
    DownloadOrchestrator,
    _hash_file,
    _staging_path_for,
)
from jidou.services.sftp_service import DownloadResult as SFTPDownloadResult

_STAGING = "/data/staging"


def _stub_hash_file(path):
    """Stand-in for _hash_file when the test doesn't write a real local file."""
    return "f" * 64, "FFFFFFFF"


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
    file.ignored_reason = None
    file.hash_sha256 = None
    file.crc32 = None
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
# _hash_file unit tests
# ---------------------------------------------------------------------------


def test_hash_file_known_values(tmp_path):
    """SHA-256 and CRC32 match precomputed values for known content."""
    p = tmp_path / "sample.bin"
    p.write_bytes(b"hello world")

    sha256_hex, crc32_hex = _hash_file(p)

    assert sha256_hex == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert crc32_hex == "0D4A1185"


def test_hash_file_empty_file(tmp_path):
    """Hashing an empty file returns the well-known empty-input digests."""
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")

    sha256_hex, crc32_hex = _hash_file(p)

    assert sha256_hex == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert crc32_hex == "00000000"


def test_hash_file_spans_multiple_chunks(tmp_path):
    """Content larger than the chunk size is hashed correctly across reads."""
    import hashlib
    import zlib

    data = b"x" * (3 * (1 << 20) + 17)  # > 3 chunks at the 1 MiB chunk size
    p = tmp_path / "large.bin"
    p.write_bytes(data)

    sha256_hex, crc32_hex = _hash_file(p)

    assert sha256_hex == hashlib.sha256(data).hexdigest()
    assert crc32_hex == f"{zlib.crc32(data) & 0xFFFFFFFF:08X}"


# ---------------------------------------------------------------------------
# DownloadOrchestrator integration tests
# ---------------------------------------------------------------------------


@patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file)
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


@patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file)
async def test_run_routes_noscan_file_to_ignored():
    """A file tagged ignored_reason at discovery goes to IGNORED, not DOWNLOADED."""
    file1 = _make_file(file_id=1, filename="doc.mkv", remote_path="/remote/doc/doc.mkv")
    file1.ignored_reason = IgnoredReason.NOSCAN_PATH
    file2 = _make_file(file_id=2, filename="ep1.mkv", remote_path="/remote/ep1.mkv")

    session = _make_session(files=[file1, file2])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result(size=500))

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    result = await orch.run()

    assert result.files_downloaded == 2
    assert file1.status == FileStatus.IGNORED
    assert file1.local_path is not None  # still downloaded to staging
    assert file2.status == FileStatus.DOWNLOADED


@patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file)
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


@patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file)
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


# ---------------------------------------------------------------------------
# run() — on_progress in dry_run
# ---------------------------------------------------------------------------


async def test_run_dry_run_calls_on_progress():
    """dry_run mode calls on_progress for each file."""
    file1 = _make_file(file_id=1, filename="ep1.mkv")
    file2 = _make_file(file_id=2, filename="ep2.mkv")

    session = _make_session(files=[file1, file2], dry_run=True)
    sftp = MagicMock()

    on_progress = AsyncMock()

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    await orch.run(dry_run=True, on_progress=on_progress)

    # on_progress called once per file
    assert on_progress.call_count == 2
    calls = on_progress.call_args_list
    assert calls[0].args[0] == 1  # idx
    assert calls[0].args[1] == 2  # total
    assert calls[1].args[0] == 2
    assert calls[1].args[1] == 2


# ---------------------------------------------------------------------------
# run() — on_progress after batch downloads
# ---------------------------------------------------------------------------


@patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file)
async def test_run_on_progress_after_batch():
    """on_progress called once per file after batch downloads complete."""
    file1 = _make_file(file_id=1, filename="ep1.mkv")
    file2 = _make_file(file_id=2, filename="ep2.mkv")

    session = _make_session(files=[file1, file2])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result(size=500))

    on_progress = AsyncMock()

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    await orch.run(on_progress=on_progress)

    # on_progress: 1 call at batch start + 2 calls (one per file after download)
    assert on_progress.call_count == 3
    # First call is the batch-start message
    assert on_progress.call_args_list[0].args[0] == 0  # progress_idx at batch start
    # Then per-file messages
    assert on_progress.call_args_list[1].args[0] == 1
    assert on_progress.call_args_list[2].args[0] == 2


# ---------------------------------------------------------------------------
# run() — BaseException during gather (task cancelled)
# ---------------------------------------------------------------------------


async def test_run_outer_exception_on_progress_reset_downloading():
    """Outer exception (outside gather) marks DOWNLOADING files ERROR and flushes."""
    file1 = _make_file(file_id=1, filename="ep1.mkv")

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    batch_result = MagicMock()
    batch_result.scalars.return_value.all.return_value = [file1]

    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, batch_result, empty_result])

    sftp = MagicMock()

    # Track on_progress calls
    on_progress_calls = []

    async def on_progress_with_exception(idx, total, msg):
        on_progress_calls.append((idx, total, msg))
        if len(on_progress_calls) == 1:
            # After the first on_progress call (batch-start message), raise an exception
            raise RuntimeError("Progress callback failed")

    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(session, sftp, _STAGING)

    with pytest.raises(RuntimeError):
        await orch.run(on_progress=on_progress_with_exception)

    # File should be reset to ERROR when exception is raised during processing
    assert file1.status == FileStatus.ERROR
    assert file1.error_message == "Download interrupted"
    # Session should have flushed the reset status
    assert session.flush.call_count > 0


# ---------------------------------------------------------------------------
# run() — per-file on_progress after outer BaseException (non-gather)
# ---------------------------------------------------------------------------


async def test_run_outer_exception_non_gather_resets_downloading():
    """When BaseException is raised outside gather, DOWNLOADING files are marked ERROR."""
    file1 = _make_file(file_id=1, filename="ep1.mkv")

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    batch_result = MagicMock()
    batch_result.scalars.return_value.all.return_value = [file1]

    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, batch_result, empty_result])

    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(session, sftp, _STAGING)

    # Raise an exception after status is set to DOWNLOADING but before gather completes
    gather_calls = 0

    async def raise_on_gather(*tasks, **kwargs):
        nonlocal gather_calls
        gather_calls += 1
        raise RuntimeError("Injected outer exception")

    with (
        patch("asyncio.gather", side_effect=raise_on_gather),
        pytest.raises(RuntimeError),
    ):
        await orch.run()

    # File should be reset to ERROR with "Download interrupted" message
    assert file1.status == FileStatus.ERROR
    assert file1.error_message == "Download interrupted"
    # Session should have tried to persist the error
    assert session.flush.call_count > 0


# ---------------------------------------------------------------------------
# run() — on_event callback
# ---------------------------------------------------------------------------


@patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file)
async def test_on_event_called_for_each_successful_download():
    """on_event emits an info event for every successfully downloaded file."""
    file1 = _make_file(file_id=1, filename="ep1.mkv", remote_path="/remote/ep1.mkv")
    file2 = _make_file(file_id=2, filename="ep2.mkv", remote_path="/remote/ep2.mkv")

    session = _make_session(files=[file1, file2])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result(size=500))

    on_event = AsyncMock()
    orch = DownloadOrchestrator(session, sftp, _STAGING)
    await orch.run(on_event=on_event)

    success_calls = [c for c in on_event.call_args_list if "Downloaded" in c[0][1]]
    assert len(success_calls) == 2
    assert all(c[0][0] == "info" for c in success_calls)


async def test_on_event_called_for_download_failure():
    """on_event emits an error event when a file fails to download."""
    file1 = _make_file()

    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=OSError("connection refused"))

    on_event = AsyncMock()
    orch = DownloadOrchestrator(session, sftp, _STAGING)
    await orch.run(on_event=on_event)

    error_calls = [c for c in on_event.call_args_list if c[0][0] == "error"]
    assert len(error_calls) == 1
    assert "connection refused" in error_calls[0][0][1]


async def test_on_event_called_in_dry_run():
    """on_event emits a dry-run info event for each file."""
    file1 = _make_file(file_id=1, filename="ep1.mkv")
    file2 = _make_file(file_id=2, filename="ep2.mkv")

    session = _make_session(files=[file1, file2], dry_run=True)
    sftp = MagicMock()

    on_event = AsyncMock()
    orch = DownloadOrchestrator(session, sftp, _STAGING)
    await orch.run(dry_run=True, on_event=on_event)

    dry_run_calls = [c for c in on_event.call_args_list if "Dry run" in c[0][1]]
    assert len(dry_run_calls) == 2


# ---------------------------------------------------------------------------
# run() — download integrity verification (SHA-256 / CRC32)
# ---------------------------------------------------------------------------


def _make_writing_download(data: bytes):
    """Build a download_file side_effect that stages real bytes on disk.

    Mirrors what SFTPService.download_file actually does (writes the
    transferred bytes to local_path) so the post-download hashing step has
    a real file to read.
    """

    async def _do(remote_path: str, local_path, dry_run: bool = False):
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return SFTPDownloadResult(
            remote_path=remote_path,
            local_path=str(local_path),
            size=len(data),
            dry_run=False,
            elapsed_seconds=0.1,
        )

    return _do


async def test_run_populates_hash_columns_on_success(tmp_path):
    """A successful download gets hash_sha256 and crc32 computed from the bytes."""
    file1 = _make_file(filename="Show.S01E01.mkv", remote_path="/remote/ep.mkv")

    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=_make_writing_download(b"hello world"))

    orch = DownloadOrchestrator(session, sftp, str(tmp_path))
    result = await orch.run()

    assert result.files_downloaded == 1
    assert file1.status == FileStatus.DOWNLOADED
    assert file1.hash_sha256 == ("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
    assert file1.crc32 == "0D4A1185"


async def test_run_matching_crc32_tag_downloads_successfully(tmp_path):
    """A filename-declared CRC32 that matches the computed one is a normal success."""
    file1 = _make_file(filename="Show.S01E01.[0D4A1185].mkv", remote_path="/remote/ep.mkv")

    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=_make_writing_download(b"hello world"))

    orch = DownloadOrchestrator(session, sftp, str(tmp_path))
    result = await orch.run()

    assert result.files_downloaded == 1
    assert result.files_failed == 0
    assert file1.status == FileStatus.DOWNLOADED
    assert file1.local_path is not None
    assert file1.crc32 == "0D4A1185"


async def test_run_mismatched_crc32_tag_marks_error_and_clears_local_path(tmp_path):
    """A corrupt transfer (bytes don't match the filename's CRC32 tag) is flagged."""
    file1 = _make_file(filename="Show.S01E01.[DEADBEEF].mkv", remote_path="/remote/ep.mkv")

    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=_make_writing_download(b"hello world"))

    orch = DownloadOrchestrator(session, sftp, str(tmp_path))
    result = await orch.run()

    assert result.files_failed == 1
    assert result.files_downloaded == 0
    assert file1.status == FileStatus.ERROR
    assert file1.error_message == (
        "CRC32 mismatch — corrupt download (expected DEADBEEF, got 0D4A1185)"
    )
    # Cleared so the existing ERROR + local_path IS NULL predicate retries it.
    assert file1.local_path is None
    # Diagnostics are still recorded even on mismatch.
    assert file1.crc32 == "0D4A1185"


async def test_run_retries_mismatched_file_on_next_run(tmp_path):
    """After a CRC32 mismatch clears local_path, a follow-up run re-downloads it."""
    file1 = _make_file(filename="Show.S01E01.[DEADBEEF].mkv", remote_path="/remote/ep.mkv")
    file1.status = FileStatus.ERROR  # simulate the state after the first failed run

    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=_make_writing_download(b"hello world"))

    orch = DownloadOrchestrator(session, sftp, str(tmp_path))
    result = await orch.run()

    # base_where matches ERROR rows with local_path IS NULL (set by _make_file default)
    assert sftp.download_file.call_count == 1
    assert result.files_failed == 1
    assert file1.status == FileStatus.ERROR
    assert file1.local_path is None
