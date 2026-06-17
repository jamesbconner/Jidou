"""SFTP service for remote file access via AsyncSSH.

Provides listing, single-file download, and batch-download operations with
per-file progress callbacks suitable for real-time UI updates.  All network
I/O is async and non-blocking.
"""

from __future__ import annotations

import fnmatch
import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncssh

logger = logging.getLogger(__name__)


@dataclass
class RemoteFile:
    """Metadata for a single file on the remote SFTP server."""

    name: str
    path: str
    size: int


@dataclass
class DownloadResult:
    """Result of a single file download operation."""

    remote_path: str
    local_path: str
    size: int
    dry_run: bool
    elapsed_seconds: float


@dataclass
class DownloadProgress:
    """Progress snapshot emitted after each file in a batch download."""

    filename: str
    bytes_transferred: int
    total_bytes: int
    file_index: int
    file_count: int
    elapsed_seconds: float


class SFTPService:
    """AsyncSSH-based SFTP client for remote file access.

    Each public method opens its own short-lived SSH connection so the service
    remains stateless and safe to use concurrently from multiple coroutines.

    Args:
        host: Remote SSH host.
        port: SSH port (default 22).
        username: SSH username.
        password: Password authentication (mutually exclusive with *key_path*).
        key_path: Path to an SSH private key file.
        remote_base_path: Default remote directory used when no path is given.
        known_hosts: Known-hosts value passed to asyncssh (``None`` disables
            host-key verification — acceptable for private networks).
    """

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str | None = None,
        password: str | None = None,
        key_path: str | None = None,
        remote_base_path: str = "/",
        known_hosts: Any = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self._key_path = key_path
        self.remote_base_path = remote_base_path
        self._known_hosts = known_hosts

    def _connect_kwargs(self) -> dict[str, Any]:
        """Build keyword arguments for ``asyncssh.connect()``."""
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "known_hosts": self._known_hosts,
        }
        if self._password:
            kwargs["password"] = self._password
        if self._key_path:
            kwargs["client_keys"] = [self._key_path]
        return kwargs

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[Any]:
        """Open a short-lived SSH + SFTP session.

        Yields:
            An active ``asyncssh.SFTPClient`` ready for use.
        """
        async with (
            asyncssh.connect(**self._connect_kwargs()) as conn,
            conn.start_sftp_client() as sftp,
        ):
            yield sftp

    async def list_remote_files(
        self,
        path: str | None = None,
        pattern: str = "*",
    ) -> list[RemoteFile]:
        """List files at the given remote directory.

        Args:
            path: Remote directory path.  Defaults to ``remote_base_path``.
            pattern: Glob pattern applied to filenames (e.g. ``"*.mkv"``).

        Returns:
            List of :class:`RemoteFile` objects, sorted by name, excluding
            ``.`` and ``..`` entries.
        """
        remote_path = path or self.remote_base_path
        logger.info("Listing remote files at %s (pattern=%r)", remote_path, pattern)

        files: list[RemoteFile] = []
        async with self._connection() as sftp:
            entries = await sftp.readdir(remote_path)
            for entry in entries:
                name: str = entry.filename
                if name in (".", ".."):
                    continue
                if not fnmatch.fnmatch(name, pattern):
                    continue
                size: int = getattr(entry.attrs, "size", 0) or 0
                files.append(
                    RemoteFile(
                        name=name,
                        path=f"{remote_path.rstrip('/')}/{name}",
                        size=size,
                    )
                )

        files.sort(key=lambda f: f.name)
        logger.info("Found %d files at %s", len(files), remote_path)
        return files

    async def download_file(
        self,
        remote_path: str,
        local_path: str | Path,
        dry_run: bool = False,
    ) -> DownloadResult:
        """Download a single file from the remote server.

        Args:
            remote_path: Full remote file path.
            local_path: Local destination path (parent dirs are created if needed).
            dry_run: When ``True`` the transfer is skipped; the result reports
                ``size=0`` and ``dry_run=True``.

        Returns:
            :class:`DownloadResult` with transfer details.
        """
        local = Path(local_path)
        start = time.monotonic()

        if dry_run:
            logger.info("[DRY RUN] Would download %s → %s", remote_path, local)
            return DownloadResult(
                remote_path=remote_path,
                local_path=str(local),
                size=0,
                dry_run=True,
                elapsed_seconds=0.0,
            )

        local.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading %s → %s", remote_path, local)

        async with self._connection() as sftp:
            await sftp.get(remote_path, str(local))

        size = local.stat().st_size if local.exists() else 0
        elapsed = time.monotonic() - start
        logger.info("Downloaded %s (%d bytes) in %.2fs", remote_path, size, elapsed)
        return DownloadResult(
            remote_path=remote_path,
            local_path=str(local),
            size=size,
            dry_run=False,
            elapsed_seconds=elapsed,
        )

    async def download_files(
        self,
        remote_paths: list[str],
        local_base: str | Path,
        dry_run: bool = False,
        on_progress: Callable[[DownloadProgress], None] | None = None,
    ) -> list[DownloadResult]:
        """Download multiple files sequentially, emitting per-file progress.

        Args:
            remote_paths: Remote file paths to download.
            local_base: Local directory where files are written (filename from
                the remote path is preserved).
            dry_run: Passed through to each :meth:`download_file` call.
            on_progress: Optional callback invoked after each file completes.
                Receives a :class:`DownloadProgress` snapshot.

        Returns:
            List of :class:`DownloadResult` objects, one per input path.
        """
        base = Path(local_base)
        results: list[DownloadResult] = []
        total = len(remote_paths)
        batch_start = time.monotonic()

        for idx, remote_path in enumerate(remote_paths, start=1):
            filename = Path(remote_path).name
            local_path = base / filename
            file_start = time.monotonic()

            result = await self.download_file(remote_path, local_path, dry_run=dry_run)
            results.append(result)

            if on_progress is not None:
                on_progress(
                    DownloadProgress(
                        filename=filename,
                        bytes_transferred=result.size,
                        total_bytes=result.size,
                        file_index=idx,
                        file_count=total,
                        elapsed_seconds=time.monotonic() - file_start,
                    )
                )

        logger.info(
            "Batch download complete: %d/%d files in %.2fs (dry_run=%s)",
            len(results),
            total,
            time.monotonic() - batch_start,
            dry_run,
        )
        return results
