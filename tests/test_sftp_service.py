"""Tests for the SFTPService."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from jidou.services.sftp_service import CommandResult, DownloadProgress, SFTPService, UploadResult


@pytest.fixture
def sftp_service() -> SFTPService:
    """SFTPService configured for a test host."""
    return SFTPService(
        host="sftp.example.com",
        port=22,
        username="testuser",
        password="testpass",
        remote_base_path="/remote/data",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    filename: str,
    size: int,
    is_dir: bool = False,
    mtime: int | None = None,
) -> MagicMock:
    """Build a mock asyncssh SFTP directory entry."""
    import stat as _stat

    entry = MagicMock()
    entry.filename = filename
    entry.attrs = MagicMock()
    entry.attrs.size = size
    # asyncssh 2.x uses permissions; set the S_IFDIR/S_IFREG bits accordingly.
    entry.attrs.permissions = _stat.S_IFDIR | 0o755 if is_dir else _stat.S_IFREG | 0o644
    entry.attrs.mtime = mtime
    return entry


def _make_conn(mock_sftp: AsyncMock) -> MagicMock:
    """Build the two-level async context manager that asyncssh.connect() returns."""
    sftp_cm = MagicMock()
    sftp_cm.__aenter__.return_value = mock_sftp
    sftp_cm.__aexit__.return_value = False

    conn = MagicMock()
    conn.__aenter__.return_value = conn
    conn.__aexit__.return_value = False
    conn.start_sftp_client = MagicMock(return_value=sftp_cm)
    return conn


def _old_mtime() -> int:
    """Unix timestamp for 10 minutes ago (well outside the upload grace window)."""
    return int(time.time()) - 600


class _FakeProc:
    """Stand-in for asyncssh.SSHCompletedProcess."""

    def __init__(self, exit_status: int, stdout: str = "", stderr: str = "") -> None:
        self.exit_status = exit_status
        self.stdout = stdout
        self.stderr = stderr


def _make_exec_conn(proc: object) -> MagicMock:
    """Build the single-level async context manager asyncssh.connect() returns for exec."""
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.run = AsyncMock(return_value=proc)
    return conn


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestSFTPServiceInit:
    def test_stores_connection_params(self, sftp_service: SFTPService) -> None:
        """Constructor stores host, port, and credentials."""
        assert sftp_service.host == "sftp.example.com"
        assert sftp_service.port == 22
        assert sftp_service.username == "testuser"
        assert sftp_service.remote_base_path == "/remote/data"

    def test_connect_kwargs_password_auth(self, sftp_service: SFTPService) -> None:
        """_connect_kwargs() includes password when set."""
        kwargs = sftp_service._connect_kwargs()
        assert kwargs["password"] == "testpass"
        assert "client_keys" not in kwargs

    def test_connect_kwargs_key_auth(self) -> None:
        """_connect_kwargs() includes client_keys when key_path is set."""
        svc = SFTPService(host="h", username="u", key_path="/home/u/.ssh/id_rsa")
        kwargs = svc._connect_kwargs()
        assert kwargs["client_keys"] == ["/home/u/.ssh/id_rsa"]
        assert "password" not in kwargs

    def test_max_workers_property_returns_configured_value(self) -> None:
        """max_workers exposes the constructor value read-only."""
        svc = SFTPService(host="h", username="u", max_workers=16)
        assert svc.max_workers == 16


# ---------------------------------------------------------------------------
# _execute_with_retry — this is the core resilience logic behind every
# network call; paramiko/asyncssh connections can drop mid-transfer, so
# these tests pin down exactly what gets retried, what doesn't, and the
# backoff timing.
# ---------------------------------------------------------------------------


class TestExecuteWithRetry:
    @pytest.mark.asyncio
    async def test_succeeds_after_transient_failures(self, sftp_service: SFTPService) -> None:
        """A transient error on early attempts does not prevent eventual success."""
        attempts = 0

        async def factory() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise asyncssh.DisconnectError(2, "connection reset")
            return "ok"

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await sftp_service._execute_with_retry("test op", factory)

        assert result == "ok"
        assert attempts == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries_and_raises_last_error(self, sftp_service: SFTPService) -> None:
        """After max_retries attempts, the most recent transient error is re-raised."""
        sftp_service._max_retries = 2  # 3 total attempts
        attempts = 0

        async def factory() -> str:
            nonlocal attempts
            attempts += 1
            raise asyncssh.DisconnectError(2, f"failure {attempts}")

        with (
            patch("asyncio.sleep", new=AsyncMock()),
            pytest.raises(asyncssh.DisconnectError, match="failure 3"),
        ):
            await sftp_service._execute_with_retry("test op", factory)

        assert attempts == 3  # initial attempt + 2 retries

    @pytest.mark.asyncio
    async def test_permanent_error_is_not_retried(self, sftp_service: SFTPService) -> None:
        """Non-transient SFTP errors (e.g. file not found) propagate on the first attempt."""
        attempts = 0

        async def factory() -> None:
            nonlocal attempts
            attempts += 1
            raise asyncssh.SFTPError(2, "no such file")

        with pytest.raises(asyncssh.SFTPError):
            await sftp_service._execute_with_retry("test op", factory)

        assert attempts == 1

    @pytest.mark.asyncio
    async def test_backoff_delay_doubles_between_attempts(self, sftp_service: SFTPService) -> None:
        """Each retry waits twice as long as the previous, starting at retry_delay."""
        sftp_service._retry_delay = 1.0
        sftp_service._max_retries = 3
        delays: list[float] = []

        async def factory() -> None:
            raise ConnectionError("refused")

        async def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        with (
            patch("asyncio.sleep", side_effect=fake_sleep),
            pytest.raises(ConnectionError),
        ):
            await sftp_service._execute_with_retry("test op", factory)

        assert delays == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_zero_max_retries_fails_after_single_attempt(
        self, sftp_service: SFTPService
    ) -> None:
        """max_retries=0 means one attempt total; failure raises immediately."""
        sftp_service._max_retries = 0
        attempts = 0

        async def factory() -> None:
            nonlocal attempts
            attempts += 1
            raise TimeoutError("timed out")

        with pytest.raises(TimeoutError):
            await sftp_service._execute_with_retry("test op", factory)

        assert attempts == 1


# ---------------------------------------------------------------------------
# _parse_mtime
# ---------------------------------------------------------------------------


class TestParseMtime:
    def test_returns_none_when_mtime_is_none(self, sftp_service: SFTPService) -> None:
        """Missing mtime attribute yields None rather than raising."""
        entry = _make_entry("ep01.mkv", 100, mtime=None)
        assert sftp_service._parse_mtime(entry) is None

    def test_returns_none_on_non_numeric_mtime(self, sftp_service: SFTPService) -> None:
        """A malformed (non-numeric) mtime value is swallowed and returns None."""
        entry = _make_entry("ep01.mkv", 100)
        entry.attrs.mtime = "not-a-timestamp"
        assert sftp_service._parse_mtime(entry) is None

    def test_returns_none_when_fromtimestamp_raises_oserror(
        self, sftp_service: SFTPService
    ) -> None:
        """An out-of-range timestamp that datetime rejects returns None, not a crash."""
        entry = _make_entry("ep01.mkv", 100, mtime=_old_mtime())

        with patch(
            "jidou.services.sftp_service.datetime",
        ) as mock_datetime:
            mock_datetime.fromtimestamp.side_effect = OSError("timestamp out of range")
            assert sftp_service._parse_mtime(entry) is None


# ---------------------------------------------------------------------------
# list_remote_files
# ---------------------------------------------------------------------------


class TestListRemoteFiles:
    @pytest.mark.asyncio
    async def test_returns_files_excluding_dot_entries(self, sftp_service: SFTPService) -> None:
        """Dot and dot-dot entries are filtered out."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[
                _make_entry("show_s01e01.mkv", 1024, mtime=_old_mtime()),
                _make_entry("show_s01e02.mkv", 2048, mtime=_old_mtime()),
                _make_entry(".", 0),
                _make_entry("..", 0),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert len(files) == 2
        assert files[0].name == "show_s01e01.mkv"
        assert files[0].size == 1024

    @pytest.mark.asyncio
    async def test_filters_by_glob_pattern(self, sftp_service: SFTPService) -> None:
        """Only filenames matching the pattern are returned."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[
                _make_entry("ep01.mkv", 1024, mtime=_old_mtime()),
                _make_entry("ep01.srt", 512, mtime=_old_mtime()),
                _make_entry("ep01.nfo", 100, mtime=_old_mtime()),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files(pattern="*.mkv")

        assert len(files) == 1
        assert files[0].name == "ep01.mkv"

    @pytest.mark.asyncio
    async def test_excludes_nfo_by_extension_filter(self, sftp_service: SFTPService) -> None:
        """NFO and other excluded extensions are dropped even without a glob pattern."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[
                _make_entry("ep01.mkv", 1024, mtime=_old_mtime()),
                _make_entry("show.nfo", 500, mtime=_old_mtime()),
                _make_entry("cover.jpg", 200, mtime=_old_mtime()),
                _make_entry("checksums.sfv", 100, mtime=_old_mtime()),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert len(files) == 1
        assert files[0].name == "ep01.mkv"

    @pytest.mark.asyncio
    async def test_excludes_sample_files_by_keyword(self, sftp_service: SFTPService) -> None:
        """Files containing 'sample' in their name are excluded."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[
                _make_entry("ep01.mkv", 1024, mtime=_old_mtime()),
                _make_entry("sample.mkv", 50, mtime=_old_mtime()),
                _make_entry("ep01-sample.mkv", 60, mtime=_old_mtime()),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert len(files) == 1
        assert files[0].name == "ep01.mkv"

    @pytest.mark.asyncio
    async def test_excludes_recently_modified_files(self, sftp_service: SFTPService) -> None:
        """Files modified within the last 60 seconds are skipped (upload in progress)."""
        fresh_mtime = int(time.time()) - 5  # 5 seconds ago
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[
                _make_entry("ep01.mkv", 1024, mtime=_old_mtime()),
                _make_entry("ep02.mkv", 2048, mtime=fresh_mtime),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert len(files) == 1
        assert files[0].name == "ep01.mkv"

    @pytest.mark.asyncio
    async def test_files_with_no_mtime_are_included(self, sftp_service: SFTPService) -> None:
        """Files whose mtime cannot be read are included (fail open)."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[
                _make_entry("ep01.mkv", 1024, mtime=None),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert len(files) == 1
        assert files[0].mtime is None

    @pytest.mark.asyncio
    async def test_skips_directories(self, sftp_service: SFTPService) -> None:
        """Directory entries are not included in results."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[
                _make_entry("ep01.mkv", 1024, mtime=_old_mtime()),
                _make_entry("Season 02", 0, is_dir=True),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert len(files) == 1
        assert files[0].name == "ep01.mkv"

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_empty_directory(self, sftp_service: SFTPService) -> None:
        """Empty directory returns an empty list (excluding . and ..)."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(return_value=[_make_entry(".", 0), _make_entry("..", 0)])

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert files == []

    @pytest.mark.asyncio
    async def test_uses_custom_path(self, sftp_service: SFTPService) -> None:
        """Explicit path overrides remote_base_path."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[_make_entry("file.mkv", 500, mtime=_old_mtime())]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files(path="/custom/path")

        mock_sftp.readdir.assert_called_once_with("/custom/path")
        assert files[0].path == "/custom/path/file.mkv"

    @pytest.mark.asyncio
    async def test_results_are_sorted_by_name(self, sftp_service: SFTPService) -> None:
        """Files are returned in alphabetical order."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(
            return_value=[
                _make_entry("ep03.mkv", 300, mtime=_old_mtime()),
                _make_entry("ep01.mkv", 100, mtime=_old_mtime()),
                _make_entry("ep02.mkv", 200, mtime=_old_mtime()),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert [f.name for f in files] == ["ep01.mkv", "ep02.mkv", "ep03.mkv"]


# ---------------------------------------------------------------------------
# list_remote_files_recursive
# ---------------------------------------------------------------------------


class TestListRemoteFilesRecursive:
    @pytest.mark.asyncio
    async def test_descends_into_subdirectory(self, sftp_service: SFTPService) -> None:
        """Files inside a subdirectory are returned."""
        root_entries = [
            _make_entry("Season 01", 0, is_dir=True),
        ]
        season_entries = [
            _make_entry("ep01.mkv", 1000, mtime=_old_mtime()),
            _make_entry("ep02.mkv", 2000, mtime=_old_mtime()),
        ]

        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(side_effect=[root_entries, season_entries])

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive(path="/show")

        assert len(files) == 2
        assert files[0].name == "ep01.mkv"
        assert files[0].path == "/show/Season 01/ep01.mkv"

    @pytest.mark.asyncio
    async def test_skips_excluded_directories(self, sftp_service: SFTPService) -> None:
        """Directories matching exclusion keywords are not descended into."""
        root_entries = [
            _make_entry("Season 01", 0, is_dir=True),
            _make_entry("screens", 0, is_dir=True),
            _make_entry("sample", 0, is_dir=True),
        ]
        season_entries = [
            _make_entry("ep01.mkv", 1000, mtime=_old_mtime()),
        ]

        mock_sftp = AsyncMock()
        # Only Season 01 should be read; screens and sample should be skipped
        mock_sftp.readdir = AsyncMock(side_effect=[root_entries, season_entries])

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive(path="/show")

        assert len(files) == 1
        # Only Season 01 was read
        assert mock_sftp.readdir.call_count == 2

    @pytest.mark.asyncio
    async def test_excludes_nfo_files_in_subdirectory(self, sftp_service: SFTPService) -> None:
        """NFO files inside subdirectories are excluded."""
        root_entries = [_make_entry("Season 01", 0, is_dir=True)]
        season_entries = [
            _make_entry("ep01.mkv", 1000, mtime=_old_mtime()),
            _make_entry("show.nfo", 200, mtime=_old_mtime()),
        ]

        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(side_effect=[root_entries, season_entries])

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive(path="/show")

        assert len(files) == 1
        assert files[0].name == "ep01.mkv"

    @pytest.mark.asyncio
    async def test_mixes_root_files_and_subdir_files(self, sftp_service: SFTPService) -> None:
        """Files at root and inside subdirectories are all returned."""
        root_entries = [
            _make_entry("special.mkv", 500, mtime=_old_mtime()),
            _make_entry("Season 01", 0, is_dir=True),
        ]
        season_entries = [
            _make_entry("ep01.mkv", 1000, mtime=_old_mtime()),
        ]

        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(side_effect=[root_entries, season_entries])

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive(path="/show")

        names = {f.name for f in files}
        assert names == {"special.mkv", "ep01.mkv"}

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_tree(self, sftp_service: SFTPService) -> None:
        """An entirely empty directory tree returns an empty list."""
        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(return_value=[_make_entry(".", 0), _make_entry("..", 0)])

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive()

        assert files == []

    @pytest.mark.asyncio
    async def test_results_sorted_by_name(self, sftp_service: SFTPService) -> None:
        """Results are alphabetically sorted regardless of discovery order."""
        root_entries = [
            _make_entry("ep03.mkv", 300, mtime=_old_mtime()),
            _make_entry("ep01.mkv", 100, mtime=_old_mtime()),
            _make_entry("ep02.mkv", 200, mtime=_old_mtime()),
        ]

        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(return_value=root_entries)

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive()

        assert [f.name for f in files] == ["ep01.mkv", "ep02.mkv", "ep03.mkv"]

    @pytest.mark.asyncio
    async def test_readdir_failure_on_subdirectory_is_skipped(
        self, sftp_service: SFTPService
    ) -> None:
        """A readdir error on one subdirectory is logged and skipped; others succeed."""
        import stat as _stat

        season1 = MagicMock()
        season1.filename = "Season 01"
        season1.attrs = MagicMock()
        season1.attrs.permissions = _stat.S_IFDIR | 0o755

        season2 = MagicMock()
        season2.filename = "Season 02"
        season2.attrs = MagicMock()
        season2.attrs.permissions = _stat.S_IFDIR | 0o755

        root_entries = [season1, season2]

        mock_sftp = AsyncMock()

        async def readdir_side_effect(path: str):
            if "Season 01" in path:
                raise OSError("permission denied")
            if "Season 02" in path:
                return [_make_entry("ep01.mkv", 500, mtime=_old_mtime())]
            return root_entries

        mock_sftp.readdir = AsyncMock(side_effect=readdir_side_effect)

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive(path="/show")

        # Season 01 failed but Season 02 should still be returned
        assert len(files) == 1
        assert files[0].name == "ep01.mkv"

    @pytest.mark.asyncio
    async def test_pattern_filters_files_in_subdirectory(self, sftp_service: SFTPService) -> None:
        """Glob pattern is applied to files found inside subdirectories too."""
        root_entries = [_make_entry("Season 01", 0, is_dir=True)]
        season_entries = [
            _make_entry("ep01.mkv", 1000, mtime=_old_mtime()),
            _make_entry("ep01.srt", 50, mtime=_old_mtime()),
        ]

        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(side_effect=[root_entries, season_entries])

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive(path="/show", pattern="*.mkv")

        assert len(files) == 1
        assert files[0].name == "ep01.mkv"

    @pytest.mark.asyncio
    async def test_excludes_recently_modified_file_in_subdirectory(
        self, sftp_service: SFTPService
    ) -> None:
        """A file still being uploaded inside a subdirectory is skipped, like at the root."""
        fresh_mtime = int(time.time()) - 5
        root_entries = [_make_entry("Season 01", 0, is_dir=True)]
        season_entries = [
            _make_entry("ep01.mkv", 1000, mtime=_old_mtime()),
            _make_entry("ep02.mkv", 1000, mtime=fresh_mtime),
        ]

        mock_sftp = AsyncMock()
        mock_sftp.readdir = AsyncMock(side_effect=[root_entries, season_entries])

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files_recursive(path="/show")

        assert len(files) == 1
        assert files[0].name == "ep01.mkv"


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_dry_run_skips_transfer(self, sftp_service: SFTPService, tmp_path: Path) -> None:
        """dry_run=True must not open any SSH connection."""
        with patch("asyncssh.connect") as mock_connect:
            result = await sftp_service.download_file(
                "/remote/show.mkv", tmp_path / "show.mkv", dry_run=True
            )

        mock_connect.assert_not_called()
        assert result.dry_run is True
        assert result.size == 0

    @pytest.mark.asyncio
    async def test_dry_run_result_fields(self, sftp_service: SFTPService, tmp_path: Path) -> None:
        """dry_run result carries correct remote_path and local_path."""
        local = tmp_path / "out.mkv"
        with patch("asyncssh.connect"):
            result = await sftp_service.download_file("/remote/out.mkv", local, dry_run=True)

        assert result.remote_path == "/remote/out.mkv"
        assert result.local_path == str(local)
        assert result.elapsed_seconds == 0.0

    @pytest.mark.asyncio
    async def test_download_calls_sftp_get(self, sftp_service: SFTPService, tmp_path: Path) -> None:
        """Non-dry-run must call sftp.get() with correct paths."""
        local = tmp_path / "show.mkv"
        local.write_bytes(b"x" * 256)  # simulate file written by asyncssh

        mock_sftp = AsyncMock()
        mock_sftp.get = AsyncMock()

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            result = await sftp_service.download_file("/remote/show.mkv", local, dry_run=False)

        mock_sftp.get.assert_called_once_with("/remote/show.mkv", str(local))
        assert result.dry_run is False
        assert result.size == 256

    @pytest.mark.asyncio
    async def test_download_creates_parent_dirs(
        self, sftp_service: SFTPService, tmp_path: Path
    ) -> None:
        """Parent directories are created automatically before download."""
        local = tmp_path / "season1" / "ep01.mkv"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(b"data")

        mock_sftp = AsyncMock()
        mock_sftp.get = AsyncMock()

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            await sftp_service.download_file("/remote/ep01.mkv", local, dry_run=False)

        assert local.parent.exists()


# ---------------------------------------------------------------------------
# download_files
# ---------------------------------------------------------------------------


class TestDownloadFiles:
    @pytest.mark.asyncio
    async def test_returns_one_result_per_file(
        self, sftp_service: SFTPService, tmp_path: Path
    ) -> None:
        """download_files returns a DownloadResult for every remote path."""
        for name in ("a.mkv", "b.mkv"):
            (tmp_path / name).write_bytes(b"x" * 100)

        mock_sftp = AsyncMock()
        mock_sftp.get = AsyncMock()

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            results = await sftp_service.download_files(
                ["/remote/a.mkv", "/remote/b.mkv"],
                tmp_path,
            )

        assert len(results) == 2
        assert results[0].remote_path == "/remote/a.mkv"
        assert results[1].remote_path == "/remote/b.mkv"

    @pytest.mark.asyncio
    async def test_emits_progress_after_each_file(
        self, sftp_service: SFTPService, tmp_path: Path
    ) -> None:
        """on_progress callback is called once per file with correct indices."""
        (tmp_path / "a.mkv").write_bytes(b"x" * 50)
        (tmp_path / "b.mkv").write_bytes(b"x" * 100)

        mock_sftp = AsyncMock()
        mock_sftp.get = AsyncMock()

        events: list[DownloadProgress] = []

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            await sftp_service.download_files(
                ["/remote/a.mkv", "/remote/b.mkv"],
                tmp_path,
                on_progress=events.append,
            )

        assert len(events) == 2
        assert events[0].file_index == 1
        assert events[0].file_count == 2
        assert events[1].file_index == 2

    @pytest.mark.asyncio
    async def test_dry_run_emits_progress_with_size_zero(
        self, sftp_service: SFTPService, tmp_path: Path
    ) -> None:
        """Progress events in dry-run mode report size=0."""
        events: list[DownloadProgress] = []

        with patch("asyncssh.connect"):
            await sftp_service.download_files(
                ["/remote/a.mkv"],
                tmp_path,
                dry_run=True,
                on_progress=events.append,
            )

        assert events[0].bytes_transferred == 0

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_results(
        self, sftp_service: SFTPService, tmp_path: Path
    ) -> None:
        """download_files with an empty list returns [] without connecting."""
        with patch("asyncssh.connect") as mock_connect:
            results = await sftp_service.download_files([], tmp_path)

        mock_connect.assert_not_called()
        assert results == []

    @pytest.mark.asyncio
    async def test_duplicate_basenames_raises_before_connecting(
        self, sftp_service: SFTPService, tmp_path: Path
    ) -> None:
        """Duplicate basenames must raise ValueError before any SSH connection is made."""
        with (
            patch("asyncssh.connect") as mock_connect,
            pytest.raises(ValueError, match="Duplicate filenames"),
        ):
            await sftp_service.download_files(
                ["/shows/s01/extra.mkv", "/shows/s02/extra.mkv"],
                tmp_path,
            )

        mock_connect.assert_not_called()


# ---------------------------------------------------------------------------
# download_bytes
# ---------------------------------------------------------------------------


class TestDownloadBytes:
    @pytest.mark.asyncio
    async def test_dry_run_returns_empty_bytes_without_connecting(
        self, sftp_service: SFTPService
    ) -> None:
        """dry_run=True must not open any SSH connection and returns b''."""
        with patch("asyncssh.connect") as mock_connect:
            result = await sftp_service.download_bytes("/remote/config.json", dry_run=True)

        mock_connect.assert_not_called()
        assert result == b""

    @pytest.mark.asyncio
    async def test_download_bytes_reads_and_returns_content(
        self, sftp_service: SFTPService
    ) -> None:
        """Non-dry-run opens the remote file for read and returns its bytes."""
        payload = b'{"shows": []}'
        mock_fh = AsyncMock()
        mock_fh.__aenter__ = AsyncMock(return_value=mock_fh)
        mock_fh.read = AsyncMock(return_value=payload)
        mock_sftp = AsyncMock()
        mock_sftp.open = MagicMock(return_value=mock_fh)

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            result = await sftp_service.download_bytes("/remote/config.json")

        mock_sftp.open.assert_called_once_with("/remote/config.json", "rb")
        assert result == payload

    @pytest.mark.asyncio
    async def test_download_bytes_retries_transient_failure(
        self, sftp_service: SFTPService
    ) -> None:
        """A transient connection error is retried and eventually succeeds."""
        payload = b"recovered content"
        mock_fh = AsyncMock()
        mock_fh.__aenter__ = AsyncMock(return_value=mock_fh)
        mock_fh.read = AsyncMock(return_value=payload)
        mock_sftp = AsyncMock()
        mock_sftp.open = MagicMock(return_value=mock_fh)

        attempts = 0
        real_connect = _make_conn(mock_sftp)

        def flaky_connect(**kwargs: object) -> MagicMock:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise asyncssh.DisconnectError(2, "connection reset")
            return real_connect

        with (
            patch("asyncssh.connect", side_effect=flaky_connect),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await sftp_service.download_bytes("/remote/config.json")

        assert result == payload
        assert attempts == 2


# ---------------------------------------------------------------------------
# upload_bytes
# ---------------------------------------------------------------------------


class TestUploadBytes:
    @pytest.mark.asyncio
    async def test_dry_run_skips_transfer(self, sftp_service: SFTPService) -> None:
        """dry_run=True must not open any SSH connection."""
        with patch("asyncssh.connect") as mock_connect:
            result = await sftp_service.upload_bytes(b"hello", "/remote/config.json", dry_run=True)

        mock_connect.assert_not_called()
        assert result.dry_run is True
        assert result.size == 0
        assert result.elapsed_seconds == 0.0

    @pytest.mark.asyncio
    async def test_dry_run_result_fields(self, sftp_service: SFTPService) -> None:
        """dry_run result carries the correct remote_path."""
        with patch("asyncssh.connect"):
            result = await sftp_service.upload_bytes(b"data", "/remote/out.json", dry_run=True)

        assert result.remote_path == "/remote/out.json"
        assert isinstance(result, UploadResult)

    @pytest.mark.asyncio
    async def test_upload_bytes_calls_sftp_open_and_write(self, sftp_service: SFTPService) -> None:
        """Non-dry-run must call sftp.open() in write mode and write the data."""
        payload = b"rss config content"
        mock_fh = AsyncMock()
        # Ensure async-with yields mock_fh itself as `fh`
        mock_fh.__aenter__ = AsyncMock(return_value=mock_fh)
        mock_sftp = AsyncMock()
        mock_sftp.open = MagicMock(return_value=mock_fh)

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            result = await sftp_service.upload_bytes(payload, "/remote/rss.json")

        mock_sftp.open.assert_called_once_with("/remote/rss.json", "wb")
        mock_fh.write.assert_called_once_with(payload)
        assert result.dry_run is False
        assert result.size == len(payload)
        assert result.remote_path == "/remote/rss.json"

    @pytest.mark.asyncio
    async def test_upload_bytes_size_matches_payload(self, sftp_service: SFTPService) -> None:
        """UploadResult.size equals len(data)."""
        data = b"x" * 1024
        mock_fh = AsyncMock()
        mock_fh.__aenter__ = AsyncMock(return_value=mock_fh)
        mock_sftp = AsyncMock()
        mock_sftp.open = MagicMock(return_value=mock_fh)

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            result = await sftp_service.upload_bytes(data, "/remote/file")

        assert result.size == 1024


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------


class TestUploadFile:
    @pytest.mark.asyncio
    async def test_dry_run_skips_transfer(self, sftp_service: SFTPService, tmp_path: Path) -> None:
        """dry_run=True must not open any SSH connection."""
        local = tmp_path / "config.json"
        local.write_bytes(b"content")

        with patch("asyncssh.connect") as mock_connect:
            result = await sftp_service.upload_file(local, "/remote/config.json", dry_run=True)

        mock_connect.assert_not_called()
        assert result.dry_run is True
        assert result.size == 0
        assert result.elapsed_seconds == 0.0

    @pytest.mark.asyncio
    async def test_dry_run_result_fields(self, sftp_service: SFTPService, tmp_path: Path) -> None:
        """dry_run result carries the correct remote_path."""
        local = tmp_path / "out.json"
        local.write_bytes(b"data")

        with patch("asyncssh.connect"):
            result = await sftp_service.upload_file(local, "/remote/out.json", dry_run=True)

        assert result.remote_path == "/remote/out.json"
        assert isinstance(result, UploadResult)

    @pytest.mark.asyncio
    async def test_upload_file_calls_sftp_put(
        self, sftp_service: SFTPService, tmp_path: Path
    ) -> None:
        """Non-dry-run must call sftp.put() with correct local and remote paths."""
        local = tmp_path / "show.mkv"
        local.write_bytes(b"x" * 512)

        mock_sftp = AsyncMock()
        mock_sftp.put = AsyncMock()

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            result = await sftp_service.upload_file(local, "/remote/show.mkv")

        mock_sftp.put.assert_called_once_with(str(local), "/remote/show.mkv")
        assert result.dry_run is False
        assert result.size == 512
        assert result.remote_path == "/remote/show.mkv"

    @pytest.mark.asyncio
    async def test_upload_file_size_from_local_stat(
        self, sftp_service: SFTPService, tmp_path: Path
    ) -> None:
        """UploadResult.size is read from the local file's stat."""
        local = tmp_path / "payload.bin"
        local.write_bytes(b"y" * 256)

        mock_sftp = AsyncMock()
        mock_sftp.put = AsyncMock()

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            result = await sftp_service.upload_file(local, "/remote/payload.bin")

        assert result.size == 256


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------


class TestRunCommand:
    @pytest.mark.asyncio
    async def test_dry_run_skips_execution(self, sftp_service: SFTPService) -> None:
        """dry_run=True must not open any SSH connection."""
        with patch("asyncssh.connect") as mock_connect:
            result = await sftp_service.run_command("systemctl stop deluged", dry_run=True)

        mock_connect.assert_not_called()
        assert result.dry_run is True
        assert result.exit_status == 0
        assert result.elapsed_seconds == 0.0

    @pytest.mark.asyncio
    async def test_successful_command_returns_result(self, sftp_service: SFTPService) -> None:
        """A zero-exit command returns a populated CommandResult, no exception."""
        proc = _FakeProc(exit_status=0, stdout="ok\n", stderr="")

        with patch("asyncssh.connect", return_value=_make_exec_conn(proc)) as mock_connect:
            result = await sftp_service.run_command("systemctl stop deluged")

        mock_connect.assert_called_once()
        assert isinstance(result, CommandResult)
        assert result.command == "systemctl stop deluged"
        assert result.exit_status == 0
        assert result.stdout == "ok\n"
        assert result.dry_run is False

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises_runtime_error(self, sftp_service: SFTPService) -> None:
        """A non-zero exit status raises, surfacing stderr in the message."""
        proc = _FakeProc(exit_status=1, stdout="", stderr="unit not found")

        with (
            patch("asyncssh.connect", return_value=_make_exec_conn(proc)),
            pytest.raises(RuntimeError, match="unit not found"),
        ):
            await sftp_service.run_command("systemctl stop deluged")

    @pytest.mark.asyncio
    async def test_retries_on_transient_connection_error(self, sftp_service: SFTPService) -> None:
        """Transient connection failures are retried like other SFTP operations."""
        proc = _FakeProc(exit_status=0)
        real_conn = _make_exec_conn(proc)
        attempts = 0

        def flaky_connect(**kwargs: object) -> MagicMock:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise asyncssh.DisconnectError(2, "connection reset")
            return real_conn

        with (
            patch("asyncssh.connect", side_effect=flaky_connect),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await sftp_service.run_command("systemctl start deluged")

        assert attempts == 2
        assert result.exit_status == 0
