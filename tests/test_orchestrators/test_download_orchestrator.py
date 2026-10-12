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
    file.crc32_extracted = None
    file.crc32_declared = None
    file.crc32_computed = None
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


def test_staging_path_strips_configured_remote_root():
    """Only the sub-path within a configured scan root is mirrored, not the
    root itself -- a deeply nested SFTP prefix shared by every file
    (e.g. a seedbox layout under /data/sdaa1/myuser/path/to/files/) carries
    no useful information and, mirrored verbatim, routinely pushed staged
    paths past Windows' path length limit and broke transfers (#unmatched).
    """
    result = _staging_path_for(
        "/data/sdaa1/myuser/path/to/files/anime/ep.mkv",
        "k:/staging",
        remote_roots=["/data/sdaa1/myuser/path/to/files/"],
    )
    assert result == Path("k:/staging/anime/ep.mkv")


def test_staging_path_strips_configured_root_without_trailing_slash():
    """Trailing-slash normalization: a root configured without one still matches."""
    result = _staging_path_for(
        "/data/downloads/anime/ep.mkv",
        "/staging",
        remote_roots=["/data/downloads"],
    )
    assert result == Path("/staging/anime/ep.mkv")


def test_staging_path_uses_longest_matching_root():
    """When multiple configured roots match, the most specific one wins."""
    result = _staging_path_for(
        "/data/downloads/anime/ep.mkv",
        "/staging",
        remote_roots=["/data/downloads", "/data/downloads/anime"],
    )
    assert result == Path("/staging/ep.mkv")


def test_staging_path_falls_back_to_full_mirror_when_no_root_matches():
    """A remote_path outside every configured root mirrors in full, same as
    today's behavior -- nothing safe to strip.
    """
    result = _staging_path_for(
        "/other/place/ep.mkv",
        "/staging",
        remote_roots=["/data/downloads"],
    )
    assert result == Path("/staging/other/place/ep.mkv")


def test_staging_path_root_of_slash_does_not_strip_anything():
    """A configured root of just "/" (the default) can't safely strip
    anything -- falls back to mirroring the full path, matching the
    behavior when no remote_roots are given at all.
    """
    result = _staging_path_for(
        "/downloads/shows/ep.mkv",
        "/data/staging",
        remote_roots=["/"],
    )
    assert result == Path("/data/staging/downloads/shows/ep.mkv")


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
async def test_run_reclaims_stale_downloading_file():
    """A file left DOWNLOADING by a crashed prior run is retried, with a warning emitted."""
    file1 = _make_file(file_id=1, filename="stuck.mkv", remote_path="/remote/stuck.mkv")
    file1.status = FileStatus.DOWNLOADING

    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result(size=500))

    events = []

    async def on_event(level, msg, ctx):
        events.append((level, msg, ctx))

    orch = DownloadOrchestrator(session, sftp, _STAGING)
    result = await orch.run(on_event=on_event)

    assert result.files_downloaded == 1
    assert file1.status == FileStatus.DOWNLOADED
    warnings = [e for e in events if e[0] == "warning"]
    assert len(warnings) == 1
    assert warnings[0][2] == {"file_id": 1}


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


@patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file)
async def test_run_strips_configured_remote_root_from_staging_path():
    """When remote_paths is configured, the staging path drops the shared
    scan-root prefix instead of mirroring it -- see _staging_path_for.
    """
    file1 = _make_file(remote_path="/data/sdaa1/myuser/path/to/files/anime/ShowName_S01E01.mkv")
    session = _make_session(files=[file1])
    sftp = MagicMock()
    sftp.download_file = AsyncMock(return_value=_make_sftp_result())

    orch = DownloadOrchestrator(
        session, sftp, "/staging", remote_paths=["/data/sdaa1/myuser/path/to/files/"]
    )
    await orch.run()

    call_args = sftp.download_file.call_args
    local_path_used = call_args[0][1]
    assert local_path_used == Path("/staging/anime/ShowName_S01E01.mkv")


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
    assert file1.crc32_computed == "0D4A1185"
    # No [XXXXXXXX] tag in this filename — nothing to extract or compare against.
    assert file1.crc32_extracted is None


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
    assert file1.crc32_extracted == "0D4A1185"
    assert file1.crc32_computed == "0D4A1185"


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
    # Diagnostics are still recorded even on mismatch, pinpointing the
    # divergence: filename declared DEADBEEF, actual bytes hash to 0D4A1185.
    assert file1.crc32_extracted == "DEADBEEF"
    assert file1.crc32_computed == "0D4A1185"


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


# ---------------------------------------------------------------------------
# Characterization: full ordered trace of events / flush / commit / progress
# ---------------------------------------------------------------------------

_Trace = list[tuple]


def _traced_session(files: list, trace: _Trace) -> MagicMock:
    """Build a batch-mode session whose flush/commit append to *trace*."""
    session = _make_session(files=files)

    async def _flush() -> None:
        trace.append(("flush",))

    async def _commit() -> None:
        trace.append(("commit",))

    session.flush = AsyncMock(side_effect=_flush)
    session.commit = AsyncMock(side_effect=_commit)
    return session


def _trace_callbacks(trace: _Trace):
    async def on_event(level, message, ctx):
        trace.append(("event", level, message, dict(ctx) if ctx else ctx))

    async def on_progress(current, total, message):
        trace.append(("progress", current, total, message))

    return on_event, on_progress


def _hash_by_name(mismatch_names: set[str], raise_names: set[str]):
    """Return a _hash_file stand-in keyed on the staged file name."""

    def _hash(path):
        name = Path(path).name
        if name in raise_names:
            raise OSError(f"disk read failed: {name}")
        if name in mismatch_names:
            return "a" * 64, "00000000"
        return "f" * 64, "FFFFFFFF"

    return _hash


def _sftp_with_outcomes(outcomes: dict[str, object]) -> MagicMock:
    """sftp whose download_file returns a result of given size, or raises, per remote path."""

    async def _download(remote_path, local_path):
        outcome = outcomes[remote_path]
        if isinstance(outcome, BaseException):
            raise outcome
        return _make_sftp_result(size=int(outcome))  # type: ignore[call-overload]

    sftp = MagicMock()
    sftp.download_file = AsyncMock(side_effect=_download)
    return sftp


async def test_characterize_normal_batch_mixed_outcomes_trace():
    """Mixed batch: ok, sftp error, CRC mismatch, noscan, cancelled task, in exact order."""
    ok = _make_file(1, "ok.mkv", "/remote/ok.mkv")
    err = _make_file(2, "err.mkv", "/remote/err.mkv")
    bad = _make_file(3, "bad [DEADBEEF].mkv", "/remote/bad.mkv")
    # A stale value that a mismatch must clear so the row is retried.
    bad.local_path = "/stale/partial"
    ign = _make_file(4, "ign.mkv", "/remote/ign.mkv")
    ign.ignored_reason = IgnoredReason.NOSCAN_PATH
    can = _make_file(5, "can.mkv", "/remote/can.mkv")
    trace: _Trace = []
    session = _traced_session([ok, err, bad, ign, can], trace)
    sftp = _sftp_with_outcomes(
        {
            "/remote/ok.mkv": 10,
            "/remote/err.mkv": RuntimeError("boom"),
            "/remote/bad.mkv": 20,
            "/remote/ign.mkv": 30,
            "/remote/can.mkv": asyncio.CancelledError(),
        }
    )
    on_event, on_progress = _trace_callbacks(trace)

    with patch(
        "jidou.orchestrators.download_orchestrator._hash_file",
        new=_hash_by_name({"bad.mkv"}, set()),
    ):
        result = await DownloadOrchestrator(session, sftp, _STAGING).run(
            on_event=on_event, on_progress=on_progress
        )

    assert (result.files_downloaded, result.bytes_downloaded, result.files_failed) == (2, 40, 3)
    mismatch_msg = trace[5][2]
    assert mismatch_msg.startswith("CRC32 mismatch — corrupt download")
    assert mismatch_msg.endswith(": 'bad [DEADBEEF].mkv'")
    assert trace == [
        ("flush",),
        ("commit",),
        ("progress", 0, 5, "Downloading 5 files"),
        ("event", "info", "Downloaded 'ok.mkv'", {"file_id": 1, "bytes": 10}),
        ("event", "error", "Failed to download 'err.mkv': boom", {"file_id": 2, "error": "boom"}),
        ("event", "error", mismatch_msg, {"file_id": 3}),
        (
            "event",
            "info",
            "Downloaded 'ign.mkv' (noscan — excluded from matching)",
            {"file_id": 4, "bytes": 30},
        ),
        (
            "event",
            "error",
            "Failed to download 'can.mkv': Download interrupted",
            {"file_id": 5, "error": "Download interrupted"},
        ),
        ("flush",),
        ("commit",),
        ("progress", 1, 5, "Downloaded ok.mkv"),
        ("progress", 2, 5, "Failed err.mkv"),
        ("progress", 3, 5, "Failed bad [DEADBEEF].mkv"),
        ("progress", 4, 5, "Downloaded ign.mkv"),
        ("progress", 5, 5, "Failed can.mkv"),
    ]
    assert [f.status for f in (ok, err, bad, ign, can)] == [
        FileStatus.DOWNLOADED,
        FileStatus.ERROR,
        FileStatus.ERROR,
        FileStatus.IGNORED,
        FileStatus.ERROR,
    ]
    assert err.error_message == "boom"
    assert can.error_message == "Download interrupted"
    assert bad.local_path is None
    assert ok.local_path == f"{_STAGING}/remote/ok.mkv"
    assert (ok.file_size, ign.file_size) == (10, 30)
    assert ok.error_message is None
    assert ok.hash_sha256 == "f" * 64


async def test_characterize_stale_downloading_warning_event_precedes_commit():
    """The stale-reclaim warning is emitted during claiming, before flush/commit."""
    stale = _make_file(1, "old.mkv", "/remote/old.mkv")
    stale.status = FileStatus.DOWNLOADING
    stale.updated_at = "yesterday"
    trace: _Trace = []
    session = _traced_session([stale], trace)
    sftp = _sftp_with_outcomes({"/remote/old.mkv": 5})
    on_event, _ = _trace_callbacks(trace)

    with patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file):
        await DownloadOrchestrator(session, sftp, _STAGING).run(on_event=on_event)

    assert trace[:3] == [
        (
            "event",
            "warning",
            "Retrying stuck download 'old.mkv' "
            "(left DOWNLOADING by a previous, apparently crashed run)",
            {"file_id": 1},
        ),
        ("flush",),
        ("commit",),
    ]


async def test_characterize_mid_file_hash_failure_normal_path():
    """A hash error on file 2 propagates; files 2 and 3 are failed 'interrupted', file 1 kept."""
    f1 = _make_file(1, "a.mkv", "/remote/a.mkv")
    f2 = _make_file(2, "b.mkv", "/remote/b.mkv")
    f3 = _make_file(3, "c.mkv", "/remote/c.mkv")
    trace: _Trace = []
    session = _traced_session([f1, f2, f3], trace)
    sftp = _sftp_with_outcomes({"/remote/a.mkv": 1, "/remote/b.mkv": 2, "/remote/c.mkv": 3})
    on_event, on_progress = _trace_callbacks(trace)

    with (
        patch(
            "jidou.orchestrators.download_orchestrator._hash_file",
            new=_hash_by_name(set(), {"b.mkv"}),
        ),
        pytest.raises(OSError, match=r"disk read failed: b\.mkv"),
    ):
        await DownloadOrchestrator(session, sftp, _STAGING).run(
            on_event=on_event, on_progress=on_progress
        )

    assert trace == [
        ("flush",),
        ("commit",),
        ("progress", 0, 3, "Downloading 3 files"),
        ("event", "info", "Downloaded 'a.mkv'", {"file_id": 1, "bytes": 1}),
        ("event", "error", "Download interrupted: 'b.mkv'", {"file_id": 2}),
        ("event", "error", "Download interrupted: 'c.mkv'", {"file_id": 3}),
        ("flush",),
        ("commit",),
    ]
    assert f1.status == FileStatus.DOWNLOADED
    assert f2.status == f3.status == FileStatus.ERROR
    assert f2.error_message == f3.error_message == "Download interrupted"
    # The hash columns were never written for the file that failed to hash.
    assert f2.hash_sha256 is None


async def test_characterize_mismatch_then_hash_failure_normal_path():
    """A CRC mismatch (counted failed) followed by a hash error on the next file."""
    f1 = _make_file(1, "a [DEADBEEF].mkv", "/remote/a.mkv")
    f2 = _make_file(2, "b.mkv", "/remote/b.mkv")
    trace: _Trace = []
    session = _traced_session([f1, f2], trace)
    sftp = _sftp_with_outcomes({"/remote/a.mkv": 1, "/remote/b.mkv": 2})
    on_event, _ = _trace_callbacks(trace)

    with (
        patch(
            "jidou.orchestrators.download_orchestrator._hash_file",
            new=_hash_by_name({"a.mkv"}, {"b.mkv"}),
        ),
        pytest.raises(OSError),
    ):
        await DownloadOrchestrator(session, sftp, _STAGING).run(on_event=on_event)

    assert [(t[0], t[1], t[3]) for t in trace if t[0] == "event"] == [
        ("event", "error", {"file_id": 1}),
        ("event", "error", {"file_id": 2}),
    ]
    assert trace[2][2].startswith("CRC32 mismatch")
    assert trace[3][2] == "Download interrupted: 'b.mkv'"
    assert f1.local_path is None
    assert f1.status == f2.status == FileStatus.ERROR


async def _gather_then_cancel(*tasks, **kwargs):
    """Stand-in for asyncio.gather: let the tasks settle, then simulate outer cancellation."""
    for _ in range(5):
        await asyncio.sleep(0)
    raise asyncio.CancelledError


async def test_characterize_cancel_path_credits_finished_and_fails_rest():
    """Outer cancel: finished transfers credited, mismatch failed, errored ones 'interrupted'."""
    ok = _make_file(1, "ok.mkv", "/remote/ok.mkv")
    bad = _make_file(2, "bad [DEADBEEF].mkv", "/remote/bad.mkv")
    err = _make_file(3, "err.mkv", "/remote/err.mkv")
    ign = _make_file(4, "ign.mkv", "/remote/ign.mkv")
    ign.ignored_reason = IgnoredReason.NOSCAN_PATH
    trace: _Trace = []
    session = _traced_session([ok, bad, err, ign], trace)
    sftp = _sftp_with_outcomes(
        {
            "/remote/ok.mkv": 10,
            "/remote/bad.mkv": 20,
            "/remote/err.mkv": RuntimeError("boom"),
            "/remote/ign.mkv": 30,
        }
    )
    on_event, on_progress = _trace_callbacks(trace)

    with (
        patch("asyncio.gather", new=_gather_then_cancel),
        patch(
            "jidou.orchestrators.download_orchestrator._hash_file",
            new=_hash_by_name({"bad.mkv"}, set()),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await DownloadOrchestrator(session, sftp, _STAGING).run(
            on_event=on_event, on_progress=on_progress
        )

    assert trace[:3] == [("flush",), ("commit",), ("progress", 0, 4, "Downloading 4 files")]
    assert trace[3] == ("event", "info", "Downloaded 'ok.mkv'", {"file_id": 1, "bytes": 10})
    assert trace[4][:2] == ("event", "error")
    assert trace[4][2].startswith("CRC32 mismatch")
    assert trace[4][3] == {"file_id": 2}
    assert trace[5] == ("event", "error", "Download interrupted: 'err.mkv'", {"file_id": 3})
    assert trace[6] == (
        "event",
        "info",
        "Downloaded 'ign.mkv' (noscan — excluded from matching)",
        {"file_id": 4, "bytes": 30},
    )
    # Cleanup persists exactly once (no second pass from the outer handler).
    assert trace[7:] == [("flush",), ("commit",)]
    assert [f.status for f in (ok, bad, err, ign)] == [
        FileStatus.DOWNLOADED,
        FileStatus.ERROR,
        FileStatus.ERROR,
        FileStatus.IGNORED,
    ]
    assert bad.local_path is None
    assert ok.file_size == 10
    assert err.error_message == "Download interrupted"


async def test_characterize_cancel_path_hash_failure_falls_to_outer_handler():
    """A hash error inside the cancel cleanup replaces the cancel and triggers the outer handler."""
    f1 = _make_file(1, "a.mkv", "/remote/a.mkv")
    f2 = _make_file(2, "b.mkv", "/remote/b.mkv")
    f3 = _make_file(3, "c.mkv", "/remote/c.mkv")
    trace: _Trace = []
    session = _traced_session([f1, f2, f3], trace)
    sftp = _sftp_with_outcomes({"/remote/a.mkv": 1, "/remote/b.mkv": 2, "/remote/c.mkv": 3})
    on_event, _ = _trace_callbacks(trace)

    with (
        patch("asyncio.gather", new=_gather_then_cancel),
        patch(
            "jidou.orchestrators.download_orchestrator._hash_file",
            new=_hash_by_name(set(), {"b.mkv"}),
        ),
        pytest.raises(OSError),
    ):
        await DownloadOrchestrator(session, sftp, _STAGING).run(on_event=on_event)

    assert trace == [
        ("flush",),
        ("commit",),
        ("event", "info", "Downloaded 'a.mkv'", {"file_id": 1, "bytes": 1}),
        ("event", "error", "Download interrupted: 'b.mkv'", {"file_id": 2}),
        ("event", "error", "Download interrupted: 'c.mkv'", {"file_id": 3}),
        ("flush",),
        ("commit",),
    ]
    assert f1.status == FileStatus.DOWNLOADED
    assert f2.status == f3.status == FileStatus.ERROR


async def test_characterize_on_progress_failure_after_commit_marks_nothing_twice():
    """on_progress raising after the results commit: finished files stay, no re-fail."""
    f1 = _make_file(1, "a.mkv", "/remote/a.mkv")
    trace: _Trace = []
    session = _traced_session([f1], trace)
    sftp = _sftp_with_outcomes({"/remote/a.mkv": 1})
    on_event, _ = _trace_callbacks(trace)

    async def on_progress(current, total, message):
        trace.append(("progress", current, total, message))
        if current == 1:
            raise RuntimeError("cancel requested")

    with (
        patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file),
        pytest.raises(RuntimeError, match="cancel requested"),
    ):
        await DownloadOrchestrator(session, sftp, _STAGING).run(
            on_event=on_event, on_progress=on_progress
        )

    assert trace == [
        ("flush",),
        ("commit",),
        ("progress", 0, 1, "Downloading 1 files"),
        ("event", "info", "Downloaded 'a.mkv'", {"file_id": 1, "bytes": 1}),
        ("flush",),
        ("commit",),
        ("progress", 1, 1, "Downloaded a.mkv"),
        # Outer handler: nothing is DOWNLOADING any more, but it still flush+commits.
        ("flush",),
        ("commit",),
    ]
    assert f1.status == FileStatus.DOWNLOADED


async def test_characterize_persist_failure_is_logged_and_original_error_raised(caplog):
    """If the interrupted-status commit itself fails, warn and re-raise the original error."""
    f1 = _make_file(1, "a.mkv", "/remote/a.mkv")
    session = _make_session(files=[f1])
    session.commit = AsyncMock(side_effect=[None, RuntimeError("db down")])
    sftp = _sftp_with_outcomes({"/remote/a.mkv": 1})

    async def on_progress(current, total, message):
        raise ValueError("stop")

    with (
        caplog.at_level("WARNING", logger="jidou.orchestrators.download_orchestrator"),
        pytest.raises(ValueError, match="stop"),
    ):
        await DownloadOrchestrator(session, sftp, _STAGING).run(on_progress=on_progress)

    assert f1.status == FileStatus.ERROR
    assert "Could not persist interrupted statuses" in caplog.text


async def test_characterize_dry_run_trace_and_log(caplog):
    """Dry run: progress then event per file, no commit/sftp, summary log with counts."""
    f1 = _make_file(1, "a.mkv", "/remote/a.mkv")
    f2 = _make_file(2, "b.mkv", "/remote/b.mkv")
    trace: _Trace = []
    session = _make_session(files=[f1, f2], dry_run=True)
    sftp = MagicMock()
    sftp.download_file = AsyncMock()
    on_event, on_progress = _trace_callbacks(trace)

    with caplog.at_level("INFO", logger="jidou.orchestrators.download_orchestrator"):
        result = await DownloadOrchestrator(session, sftp, _STAGING).run(
            dry_run=True, on_event=on_event, on_progress=on_progress
        )

    dest_a = str(Path(_STAGING) / "remote/a.mkv")
    dest_b = str(Path(_STAGING) / "remote/b.mkv")
    assert (result.files_downloaded, result.files_failed, result.bytes_downloaded) == (2, 0, 0)
    assert result.dry_run is True
    assert trace == [
        ("progress", 1, 2, "Downloading a.mkv"),
        (
            "event",
            "info",
            f"[Dry run] Would download 'a.mkv' → {dest_a}",
            {"file_id": 1, "dest": dest_a},
        ),
        ("progress", 2, 2, "Downloading b.mkv"),
        (
            "event",
            "info",
            f"[Dry run] Would download 'b.mkv' → {dest_b}",
            {"file_id": 2, "dest": dest_b},
        ),
    ]
    sftp.download_file.assert_not_called()
    session.commit.assert_not_called()
    assert "Download complete: 2 downloaded, 0 failed, 0 bytes (dry_run=True)" in caplog.text


async def test_characterize_final_log_counts_and_mismatch_error_log(caplog):
    """Normal path logs 'Download complete' with counts, and logger.error for CRC mismatches."""
    ok = _make_file(1, "ok.mkv", "/remote/ok.mkv")
    bad = _make_file(2, "bad [DEADBEEF].mkv", "/remote/bad.mkv")
    session = _make_session(files=[ok, bad])
    sftp = _sftp_with_outcomes({"/remote/ok.mkv": 7, "/remote/bad.mkv": 9})

    with (
        caplog.at_level("INFO", logger="jidou.orchestrators.download_orchestrator"),
        patch(
            "jidou.orchestrators.download_orchestrator._hash_file",
            new=_hash_by_name({"bad.mkv"}, set()),
        ),
    ):
        await DownloadOrchestrator(session, sftp, _STAGING).run()

    assert "Download complete: 1 downloaded, 1 failed, 7 bytes (dry_run=False)" in caplog.text
    assert "CRC32 mismatch — corrupt download" in caplog.text
    assert "/remote/bad.mkv" in caplog.text


async def test_characterize_cancel_path_does_not_log_mismatch(caplog):
    """Only the normal path writes the mismatch logger.error (pins log_mismatch=False)."""
    bad = _make_file(1, "bad [DEADBEEF].mkv", "/remote/bad.mkv")
    session = _make_session(files=[bad])
    sftp = _sftp_with_outcomes({"/remote/bad.mkv": 9})

    with (
        caplog.at_level("ERROR", logger="jidou.orchestrators.download_orchestrator"),
        patch("asyncio.gather", new=_gather_then_cancel),
        patch(
            "jidou.orchestrators.download_orchestrator._hash_file",
            new=_hash_by_name({"bad.mkv"}, set()),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await DownloadOrchestrator(session, sftp, _STAGING).run()

    assert "CRC32 mismatch" not in caplog.text
    assert bad.status == FileStatus.ERROR


@pytest.mark.parametrize("cancel", [False, True], ids=["normal", "cancel"])
async def test_record_transfer_is_shared_by_normal_and_cancel_paths(cancel):
    """Both the normal result loop and the cancel cleanup record transfers via one helper."""
    original = DownloadOrchestrator._record_transfer
    calls: list[str] = []

    async def spy(self, file, local_path, size, sink, *, log_mismatch):
        calls.append(file.original_filename)
        return await original(self, file, local_path, size, sink, log_mismatch=log_mismatch)

    f1 = _make_file(1, "a.mkv", "/remote/a.mkv")
    f2 = _make_file(2, "b.mkv", "/remote/b.mkv")
    f3 = _make_file(3, "c.mkv", "/remote/c.mkv")
    session = _make_session(files=[f1, f2, f3])
    # c fails to transfer, so only a and b are successfully completed transfers.
    sftp = _sftp_with_outcomes(
        {"/remote/a.mkv": 1, "/remote/b.mkv": 2, "/remote/c.mkv": RuntimeError("boom")}
    )
    orch = DownloadOrchestrator(session, sftp, _STAGING)

    with (
        patch.object(DownloadOrchestrator, "_record_transfer", new=spy),
        patch("jidou.orchestrators.download_orchestrator._hash_file", new=_stub_hash_file),
    ):
        if cancel:
            with (
                patch("asyncio.gather", new=_gather_then_cancel),
                pytest.raises(asyncio.CancelledError),
            ):
                await orch.run()
        else:
            await orch.run()

    assert calls == ["a.mkv", "b.mkv"]
    assert f1.status == f2.status == FileStatus.DOWNLOADED
    assert f3.status == FileStatus.ERROR
