"""SFTP service for remote file access via AsyncSSH.

Provides listing, single-file download, and batch-download operations with
per-file progress callbacks suitable for real-time UI updates.  All network
I/O is async and non-blocking.

Transient connection errors are retried with exponential backoff.  Batch
downloads run concurrently up to ``max_workers`` simultaneous transfers.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import stat
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import asyncssh

from jidou.services.file_filters import (
    is_recently_modified,
    is_valid_directory,
    is_valid_media_file,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Exceptions that represent transient network/connection failures worth retrying.
# Explicit SFTP protocol errors (permission denied, file not found) are NOT
# included — they are permanent and retrying would just repeat the failure.
_TRANSIENT_SFTP_ERRORS: tuple[type[BaseException], ...] = (
    asyncssh.DisconnectError,
    asyncssh.ChannelOpenError,
    ConnectionError,
    TimeoutError,
)


@dataclass
class RemoteFile:
    """Metadata for a single file or directory entry on the remote SFTP server."""

    name: str
    path: str
    size: int
    mtime: datetime | None = field(default=None)
    is_dir: bool = False


@dataclass
class RecursiveListResult:
    """Result of a recursive directory walk, including completeness signals.

    ``fully_walked`` must be checked before treating the walked directory as
    permanently known — a truncated or in-flight-upload walk must not be
    trusted never to change again.
    """

    files: list[RemoteFile] = field(default_factory=list)
    io_failures: int = 0
    recently_modified_skipped: int = 0
    directories_deferred: int = 0

    @property
    def fully_walked(self) -> bool:
        """True only if nothing was lost, skipped, or deferred during the walk.

        False if any subdirectory failed to list (``io_failures``), any file
        was excluded by the upload-grace window (``recently_modified_skipped``),
        or any subdirectory was itself too recently modified to trust its
        contents yet and was skipped without being descended into
        (``directories_deferred``) — a directory's own mtime bumps whenever a
        child is added or removed directly inside it, so a fresh directory
        mtime is a signal that it may still be receiving files. Any of these
        means this walk cannot be trusted as a complete, permanent picture of
        the directory's contents.
        """
        return (
            self.io_failures == 0
            and self.recently_modified_skipped == 0
            and self.directories_deferred == 0
        )


@dataclass
class DownloadResult:
    """Result of a single file download operation."""

    remote_path: str
    local_path: str
    size: int
    dry_run: bool
    elapsed_seconds: float


@dataclass
class UploadResult:
    """Result of a single file upload operation."""

    remote_path: str
    size: int
    dry_run: bool
    elapsed_seconds: float


@dataclass
class CommandResult:
    """Result of a shell command executed on the remote host over SSH."""

    command: str
    exit_status: int
    stdout: str
    stderr: str
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
    Transient connection errors are retried with exponential backoff.

    Args:
        host: Remote SSH host.
        port: SSH port (default 22).
        username: SSH username.
        password: Password authentication (mutually exclusive with *key_path*).
        key_path: Path to an SSH private key file.
        remote_base_path: Default remote directory used when no path is given.
        known_hosts: Known-hosts value passed to asyncssh (``None`` disables
            host-key verification — acceptable for private networks).
        max_workers: Maximum concurrent transfers in :meth:`download_files`.
        max_retries: How many times to retry a transient failure (0 = no retry).
        retry_delay: Initial backoff in seconds; doubles on each subsequent retry.
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
        max_workers: int = 8,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self._key_path = key_path
        self.remote_base_path = remote_base_path
        self._known_hosts = known_hosts
        self._max_workers = max_workers
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    @property
    def max_workers(self) -> int:
        """Maximum concurrent transfers configured for this service."""
        return self._max_workers

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

    async def _execute_with_retry(
        self,
        label: str,
        coro_factory: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Execute a coroutine factory with exponential-backoff retry.

        Retries on transient network errors (:data:`_TRANSIENT_SFTP_ERRORS`).
        Permanent SFTP errors (permission denied, file not found) propagate
        immediately without retrying.

        Args:
            label: Human-readable name used in log messages.
            coro_factory: Zero-argument callable that returns an awaitable.
                Called once per attempt so a fresh connection is opened each
                time (coroutines cannot be awaited more than once).

        Returns:
            The value returned by the awaitable on success.

        Raises:
            Exception: The last exception raised after all retries are exhausted.
        """
        delay = self._retry_delay
        last_exc: BaseException | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await coro_factory()
            except _TRANSIENT_SFTP_ERRORS as exc:
                last_exc = exc
                if attempt == self._max_retries:
                    break
                logger.warning(
                    "%s: attempt %d/%d failed (%s); retrying in %.1fs",
                    label,
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        if last_exc is None:
            raise RuntimeError("retry loop exhausted without capturing an exception")

        logger.error(
            "%s: all %d attempts failed; last error: %s",
            label,
            self._max_retries + 1,
            last_exc,
        )
        raise last_exc

    @staticmethod
    def _parse_mtime(entry: Any) -> datetime | None:
        """Extract and normalise mtime from an asyncssh SFTP entry.

        Args:
            entry: asyncssh ``SFTPName`` instance.

        Returns:
            UTC-aware datetime, or None if mtime is unavailable.
        """
        try:
            ts = entry.attrs.mtime
            if ts is None:
                return None
            return datetime.fromtimestamp(float(ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None

    async def list_remote_files(
        self,
        path: str | None = None,
        pattern: str = "*",
    ) -> list[RemoteFile]:
        """List files at the given remote directory (non-recursive).

        Only regular files that:
        - match *pattern*
        - pass the extension/keyword exclusion rules
        - were not modified within the last 60 seconds (upload grace window)

        are returned.  Subdirectories are never included.  Transient connection
        failures are retried up to ``max_retries`` times.

        Args:
            path: Remote directory path.  Defaults to ``remote_base_path``.
            pattern: Glob pattern applied to filenames (e.g. ``"*.mkv"``).

        Returns:
            List of :class:`RemoteFile` objects, sorted by name, excluding
            ``.`` and ``..`` entries.
        """
        remote_path = path or self.remote_base_path
        logger.info("Listing remote files at %s (pattern=%r)", remote_path, pattern)

        async def _do() -> list[RemoteFile]:
            files: list[RemoteFile] = []
            async with self._connection() as sftp:
                entries = await sftp.readdir(remote_path)
                for entry in entries:
                    name: str = entry.filename
                    if name in (".", ".."):
                        continue
                    if bool(entry.attrs.permissions and stat.S_ISDIR(entry.attrs.permissions)):
                        continue
                    if not fnmatch.fnmatch(name, pattern):
                        continue
                    if not is_valid_media_file(name):
                        logger.debug("Filtered out %s (extension/keyword rule)", name)
                        continue
                    mtime = self._parse_mtime(entry)
                    if mtime is not None and is_recently_modified(mtime):
                        logger.debug("Skipping recently modified file: %s", name)
                        continue
                    size: int = getattr(entry.attrs, "size", 0) or 0
                    files.append(
                        RemoteFile(
                            name=name,
                            path=f"{remote_path.rstrip('/')}/{name}",
                            size=size,
                            mtime=mtime,
                        )
                    )
            files.sort(key=lambda f: f.name)
            return files

        files = await self._execute_with_retry(f"list {remote_path}", _do)
        logger.info("Found %d files at %s", len(files), remote_path)
        return files

    async def _collect_files_recursive(
        self,
        sftp: Any,
        path: str,
        pattern: str,
        result: RecursiveListResult,
    ) -> None:
        """Collect files recursively within an already-open SFTP session.

        Directories that pass ``is_valid_directory()`` are descended into —
        unless the directory's own mtime is within the upload-grace window,
        in which case it is skipped entirely without being read this round
        (see ``directories_deferred``). Files that pass
        ``is_valid_media_file()`` and *pattern* and are not recently modified
        are appended to *result.files*. A subdirectory that fails to list, a
        file skipped for being recently modified, or a subdirectory deferred
        for being too fresh, increments the corresponding counter on *result*
        instead of only being logged — callers that need to know whether the
        walk was complete (e.g. before treating a directory as permanently
        known) must check ``result.fully_walked`` rather than assume a
        returned file list is exhaustive.

        Args:
            sftp: Open asyncssh SFTP client.
            path: Remote directory path to read.
            pattern: Glob pattern applied to filenames.
            result: Accumulator; matched files and failure/skip counts are
                recorded in place.
        """
        try:
            entries = await sftp.readdir(path)
        except Exception as exc:
            logger.warning("Failed to list directory %s, skipping: %s", path, exc)
            result.io_failures += 1
            return
        for entry in entries:
            name: str = entry.filename
            if name in (".", ".."):
                continue
            entry_path = f"{path.rstrip('/')}/{name}"

            if bool(entry.attrs.permissions and stat.S_ISDIR(entry.attrs.permissions)):
                if not is_valid_directory(name):
                    logger.debug("Skipping excluded directory: %s", name)
                    continue
                # A directory's own mtime bumps whenever a child is added or
                # removed directly inside it. A fresh mtime here means this
                # directory may still be receiving files that a readdir()
                # partway through this walk would never observe — defer the
                # whole subtree rather than trust a possibly-incomplete
                # snapshot of it.
                dir_mtime = self._parse_mtime(entry)
                if dir_mtime is not None and is_recently_modified(dir_mtime):
                    logger.debug("Deferring recently modified directory: %s", entry_path)
                    result.directories_deferred += 1
                    continue
                await self._collect_files_recursive(sftp, entry_path, pattern, result)
                continue

            if not fnmatch.fnmatch(name, pattern):
                continue
            if not is_valid_media_file(name):
                logger.debug("Filtered out %s (extension/keyword rule)", name)
                continue

            mtime = self._parse_mtime(entry)
            if mtime is not None and is_recently_modified(mtime):
                logger.debug("Skipping recently modified file: %s", entry_path)
                result.recently_modified_skipped += 1
                continue

            size: int = getattr(entry.attrs, "size", 0) or 0
            result.files.append(RemoteFile(name=name, path=entry_path, size=size, mtime=mtime))

    async def list_remote_files_recursive(
        self,
        path: str | None = None,
        pattern: str = "*",
    ) -> RecursiveListResult:
        """Recursively list files beneath the given remote directory.

        Descends into all subdirectories that pass ``is_valid_directory()``
        (excluding directories like ``sample`` or ``screens``).  Only regular
        files that pass the extension/keyword rules and are not recently
        modified are returned.

        A single SSH connection is opened for the entire traversal.  Transient
        connection failures (at the top level) are retried from the root,
        reopening a fresh connection each time. A failure partway through the
        traversal (a single subdirectory's ``readdir`` raising) is recorded in
        the result rather than aborting the whole walk — check
        ``result.fully_walked`` before treating the directory as permanently
        known.

        Args:
            path: Remote root path.  Defaults to ``remote_base_path``.
            pattern: Glob pattern applied to filenames (e.g. ``"*.mkv"``).

        Returns:
            :class:`RecursiveListResult` with files sorted by name plus
            completeness counters.
        """
        remote_path = path or self.remote_base_path
        logger.info("Recursively listing remote files at %s (pattern=%r)", remote_path, pattern)

        async def _do() -> RecursiveListResult:
            result = RecursiveListResult()
            async with self._connection() as sftp:
                await self._collect_files_recursive(sftp, remote_path, pattern, result)
            result.files.sort(key=lambda f: f.name)
            return result

        result = await self._execute_with_retry(f"recursive list {remote_path}", _do)
        logger.info(
            "Found %d files recursively at %s "
            "(io_failures=%d, recently_modified_skipped=%d, directories_deferred=%d)",
            len(result.files),
            remote_path,
            result.io_failures,
            result.recently_modified_skipped,
            result.directories_deferred,
        )
        return result

    async def list_remote_files_recursive_batch(
        self, paths: list[str], pattern: str = "*"
    ) -> list[tuple[str, RecursiveListResult | BaseException]]:
        """Recursively list files beneath each of *paths*, concurrently, bounded by ``max_workers``.

        Mirrors :meth:`download_files`'s concurrency-bounding pattern but for
        recursive listing, so every caller that needs to walk several
        directories at once gets the same concurrency guarantee automatically
        rather than each one reimplementing its own semaphore. Each path's
        walk is fully independent; a failure walking one path is captured and
        returned alongside the others rather than propagated, so one bad
        directory never cancels the rest of the batch.

        Args:
            paths: Remote directory paths to walk, each independently.
            pattern: Glob pattern applied to filenames within each walk.

        Returns:
            List of ``(path, RecursiveListResult | exception)`` pairs, one
            per input path, in the same order as *paths*.
        """
        semaphore = asyncio.Semaphore(max(1, self._max_workers))

        async def _walk_one(path: str) -> tuple[str, RecursiveListResult | BaseException]:
            async with semaphore:
                try:
                    result = await self.list_remote_files_recursive(path, pattern)
                except Exception as exc:
                    return path, exc
                return path, result

        return await asyncio.gather(*[_walk_one(p) for p in paths])

    async def list_remote_children(self, path: str | None = None) -> list[RemoteFile]:
        """List immediate children of *path* (non-recursive), files and directories alike.

        Unlike :meth:`list_remote_files`, directories ARE included (with
        ``is_dir=True``, ``size=0``) so the caller can decide which ones need
        a full recursive walk — this is the shallow "what top-level entries
        exist here" call used by scan/seed to avoid re-walking already-known
        directories. Files are filtered by the same
        ``is_valid_media_file``/``is_recently_modified`` rules as
        :meth:`list_remote_files`; directories are filtered by
        ``is_valid_directory`` (excluded directories like ``sample`` never
        surface as scan candidates) AND by ``is_recently_modified`` applied to
        the directory's own mtime — a directory whose own mtime is within the
        upload-grace window may still be receiving new top-level entries and
        is excluded entirely this round rather than surfaced as "new," so its
        discovery (and any deep walk of it) is simply deferred to a later
        call once it settles. This has no risk of permanent loss: an excluded
        directory is invisible, not marked known.

        Args:
            path: Remote directory path.  Defaults to ``remote_base_path``.

        Returns:
            List of :class:`RemoteFile`, sorted by name, excluding ``.`` and
            ``..`` entries.
        """
        remote_path = path or self.remote_base_path
        logger.info("Listing remote children at %s", remote_path)

        async def _do() -> list[RemoteFile]:
            entries_out: list[RemoteFile] = []
            async with self._connection() as sftp:
                entries = await sftp.readdir(remote_path)
                for entry in entries:
                    name: str = entry.filename
                    if name in (".", ".."):
                        continue
                    entry_path = f"{remote_path.rstrip('/')}/{name}"
                    is_dir = bool(entry.attrs.permissions and stat.S_ISDIR(entry.attrs.permissions))
                    mtime = self._parse_mtime(entry)
                    if is_dir:
                        if not is_valid_directory(name):
                            logger.debug("Skipping excluded directory: %s", name)
                            continue
                        if mtime is not None and is_recently_modified(mtime):
                            logger.debug("Deferring recently modified directory: %s", name)
                            continue
                        entries_out.append(
                            RemoteFile(name=name, path=entry_path, size=0, mtime=mtime, is_dir=True)
                        )
                        continue

                    if not is_valid_media_file(name):
                        logger.debug("Filtered out %s (extension/keyword rule)", name)
                        continue
                    if mtime is not None and is_recently_modified(mtime):
                        logger.debug("Skipping recently modified file: %s", name)
                        continue
                    size: int = getattr(entry.attrs, "size", 0) or 0
                    entries_out.append(
                        RemoteFile(name=name, path=entry_path, size=size, mtime=mtime)
                    )
            entries_out.sort(key=lambda f: f.name)
            return entries_out

        result = await self._execute_with_retry(f"list children {remote_path}", _do)
        logger.info("Found %d children at %s", len(result), remote_path)
        return result

    async def download_file(
        self,
        remote_path: str,
        local_path: str | Path,
        dry_run: bool = False,
    ) -> DownloadResult:
        """Download a single file from the remote server.

        Transient connection failures are retried with exponential backoff up
        to ``max_retries`` times.

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

        async def _do() -> None:
            async with self._connection() as sftp:
                await sftp.get(remote_path, str(local))

        await self._execute_with_retry(f"download {remote_path}", _do)

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
        """Download multiple files concurrently, emitting per-file progress.

        Up to ``max_workers`` transfers run simultaneously.  Each transfer
        independently retries transient failures via :meth:`download_file`.

        Args:
            remote_paths: Remote file paths to download.
            local_base: Local directory where files are written (filename from
                the remote path is preserved).
            dry_run: Passed through to each :meth:`download_file` call.
            on_progress: Optional callback invoked after each file completes.
                Receives a :class:`DownloadProgress` snapshot.

        Returns:
            List of :class:`DownloadResult` objects in the same order as
            *remote_paths*.

        Raises:
            ValueError: If two or more paths in *remote_paths* share the same
                filename, which would silently overwrite a local file.
        """
        base = Path(local_base)
        total = len(remote_paths)
        batch_start = time.monotonic()

        # Fail fast on basename collisions — two files with the same name from
        # different remote directories would silently overwrite each other.
        basenames = [Path(p).name for p in remote_paths]
        seen: set[str] = set()
        dupes: set[str] = set()
        for n in basenames:
            (dupes if n in seen else seen).add(n)
        if dupes:
            raise ValueError(
                f"Duplicate filenames in remote_paths would overwrite local files: {sorted(dupes)}"
            )

        results: list[DownloadResult | None] = [None] * total
        semaphore = asyncio.Semaphore(self._max_workers)

        async def _download_one(idx: int, remote_path: str) -> None:
            async with semaphore:
                filename = Path(remote_path).name
                local_path = base / filename
                file_start = time.monotonic()
                result = await self.download_file(remote_path, local_path, dry_run=dry_run)
                results[idx] = result
                if on_progress is not None:
                    on_progress(
                        DownloadProgress(
                            filename=filename,
                            bytes_transferred=result.size,
                            total_bytes=result.size,
                            file_index=idx + 1,
                            file_count=total,
                            elapsed_seconds=time.monotonic() - file_start,
                        )
                    )

        await asyncio.gather(*[_download_one(i, p) for i, p in enumerate(remote_paths)])

        logger.info(
            "Batch download complete: %d/%d files in %.2fs (dry_run=%s)",
            total,
            total,
            time.monotonic() - batch_start,
            dry_run,
        )
        # results list is fully populated; cast away the None initialiser type
        return results  # type: ignore[return-value]

    async def download_bytes(
        self,
        remote_path: str,
        dry_run: bool = False,
    ) -> bytes:
        """Download a remote file and return its raw bytes.

        Useful when the caller needs the content in memory (e.g. parsing a
        config file) rather than writing it to a local path.
        Transient connection failures are retried with exponential backoff.

        Args:
            remote_path: Full remote file path.
            dry_run: When ``True`` the transfer is skipped and ``b""`` is returned.

        Returns:
            Raw file content as bytes, or ``b""`` for dry-run.
        """
        start = time.monotonic()

        if dry_run:
            logger.info("[DRY RUN] Would download %s", remote_path)
            return b""

        logger.info("Downloading %s into memory", remote_path)

        async def _do() -> bytes:
            async with self._connection() as sftp, sftp.open(remote_path, "rb") as fh:
                return await fh.read()  # type: ignore[no-any-return]

        data: bytes = await self._execute_with_retry(f"download_bytes {remote_path}", _do)
        elapsed = time.monotonic() - start
        logger.info("Downloaded %s (%d bytes) in %.2fs", remote_path, len(data), elapsed)
        return data

    async def upload_bytes(
        self,
        data: bytes,
        remote_path: str,
        dry_run: bool = False,
    ) -> UploadResult:
        """Write in-memory bytes directly to a remote path.

        Useful for composed configs where no local temp file is needed.
        Transient connection failures are retried with exponential backoff.

        Args:
            data: Raw bytes to write.
            remote_path: Full destination path on the remote server.
            dry_run: When ``True`` the transfer is skipped; the result reports
                ``size=0`` and ``dry_run=True``.

        Returns:
            :class:`UploadResult` with transfer details.
        """
        start = time.monotonic()
        size = len(data)

        if dry_run:
            logger.info("[DRY RUN] Would upload %d bytes → %s", size, remote_path)
            return UploadResult(remote_path=remote_path, size=0, dry_run=True, elapsed_seconds=0.0)

        logger.info("Uploading %d bytes → %s", size, remote_path)

        async def _do() -> None:
            async with self._connection() as sftp, sftp.open(remote_path, "wb") as fh:
                await fh.write(data)

        await self._execute_with_retry(f"upload_bytes {remote_path}", _do)

        elapsed = time.monotonic() - start
        logger.info("Uploaded %d bytes → %s in %.2fs", size, remote_path, elapsed)
        return UploadResult(
            remote_path=remote_path, size=size, dry_run=False, elapsed_seconds=elapsed
        )

    async def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        dry_run: bool = False,
    ) -> UploadResult:
        """Upload a local file to a remote path.

        Transient connection failures are retried with exponential backoff up
        to ``max_retries`` times.

        Args:
            local_path: Path to the local source file.
            remote_path: Full destination path on the remote server.
            dry_run: When ``True`` the transfer is skipped; the result reports
                ``size=0`` and ``dry_run=True``.

        Returns:
            :class:`UploadResult` with transfer details.
        """
        local = Path(local_path)
        start = time.monotonic()

        if dry_run:
            logger.info("[DRY RUN] Would upload %s → %s", local, remote_path)
            return UploadResult(remote_path=remote_path, size=0, dry_run=True, elapsed_seconds=0.0)

        size = local.stat().st_size if local.exists() else 0
        logger.info("Uploading %s → %s", local, remote_path)

        async def _do() -> None:
            async with self._connection() as sftp:
                await sftp.put(str(local), remote_path)

        await self._execute_with_retry(f"upload_file {remote_path}", _do)

        elapsed = time.monotonic() - start
        logger.info("Uploaded %s (%d bytes) → %s in %.2fs", local.name, size, remote_path, elapsed)
        return UploadResult(
            remote_path=remote_path, size=size, dry_run=False, elapsed_seconds=elapsed
        )

    async def run_command(self, command: str, dry_run: bool = False) -> CommandResult:
        """Execute a shell command on the remote host over an SSH exec channel.

        Separate from the SFTP subsystem — opens a plain SSH connection and runs
        *command* non-interactively. Because the remote shell is neither a login
        nor an interactive shell, it does not source ``.bashrc``/``.bash_profile``,
        so shell aliases and functions defined there are not available; use the
        underlying command directly (e.g. ``systemctl stop deluged``, not an alias).

        Args:
            command: Shell command to execute on the remote host.
            dry_run: When ``True`` the command is skipped; the result reports
                ``exit_status=0`` and ``dry_run=True``.

        Returns:
            :class:`CommandResult` with exit status and captured output.

        Raises:
            RuntimeError: If the command exits with a non-zero status.
        """
        start = time.monotonic()

        if dry_run:
            logger.info("[DRY RUN] Would run remote command: %s", command)
            return CommandResult(
                command=command,
                exit_status=0,
                stdout="",
                stderr="",
                dry_run=True,
                elapsed_seconds=0.0,
            )

        logger.info("Running remote command: %s", command)

        async def _do() -> asyncssh.SSHCompletedProcess:
            async with asyncssh.connect(**self._connect_kwargs()) as conn:
                return await conn.run(command, check=False)

        proc = await self._execute_with_retry(f"run_command {command}", _do)
        elapsed = time.monotonic() - start
        stdout = proc.stdout if isinstance(proc.stdout, str) else ""
        stderr = proc.stderr if isinstance(proc.stderr, str) else ""
        exit_status = proc.exit_status if proc.exit_status is not None else -1

        if exit_status != 0:
            logger.error(
                "Remote command failed (exit %d) in %.2fs: %s\nstderr: %s",
                exit_status,
                elapsed,
                command,
                stderr,
            )
            raise RuntimeError(f"Remote command exited {exit_status}: {command}\n{stderr}".strip())

        logger.info("Remote command succeeded in %.2fs: %s", elapsed, command)
        return CommandResult(
            command=command,
            exit_status=exit_status,
            stdout=stdout,
            stderr=stderr,
            dry_run=False,
            elapsed_seconds=elapsed,
        )
