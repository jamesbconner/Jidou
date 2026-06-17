"""Tests for the SFTPService."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.sftp_service import DownloadProgress, SFTPService


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


def _make_entry(filename: str, size: int) -> MagicMock:
    """Build a mock asyncssh SFTP directory entry."""
    entry = MagicMock()
    entry.filename = filename
    entry.attrs = MagicMock()
    entry.attrs.size = size
    return entry


def _make_conn(mock_sftp: AsyncMock) -> MagicMock:
    """Build the two-level async context manager that asyncssh.connect() returns."""
    sftp_cm = MagicMock()
    sftp_cm.__aenter__ = AsyncMock(return_value=mock_sftp)
    sftp_cm.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.start_sftp_client = MagicMock(return_value=sftp_cm)
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
                _make_entry("show_s01e01.mkv", 1024),
                _make_entry("show_s01e02.mkv", 2048),
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
                _make_entry("ep01.mkv", 1024),
                _make_entry("ep01.srt", 512),
                _make_entry("ep01.nfo", 100),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files(pattern="*.mkv")

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
        mock_sftp.readdir = AsyncMock(return_value=[_make_entry("file.mkv", 500)])

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
                _make_entry("ep03.mkv", 300),
                _make_entry("ep01.mkv", 100),
                _make_entry("ep02.mkv", 200),
            ]
        )

        with patch("asyncssh.connect", return_value=_make_conn(mock_sftp)):
            files = await sftp_service.list_remote_files()

        assert [f.name for f in files] == ["ep01.mkv", "ep02.mkv", "ep03.mkv"]


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
