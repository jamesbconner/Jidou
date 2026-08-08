"""Orchestrator for downloading DISCOVERED files from SFTP to the local staging area."""

import asyncio
import hashlib
import logging
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.services.filename_parser import extract_crc32
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)

_HASH_CHUNK_SIZE = 1 << 20  # 1 MiB


def _hash_file(path: Path) -> tuple[str, str]:
    """Compute the SHA-256 and CRC32 of a file in one streaming read pass.

    Args:
        path: Local file to hash.

    Returns:
        Tuple of (sha256_hex, crc32_hex) where crc32_hex is 8-char uppercase.
    """
    sha256 = hashlib.sha256()
    crc = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK_SIZE), b""):
            sha256.update(chunk)
            crc = zlib.crc32(chunk, crc)
    return sha256.hexdigest(), f"{crc & 0xFFFFFFFF:08X}"


def _verify_integrity(file: DownloadedFile, sha256_hex: str, crc32_hex: str) -> str | None:
    """Populate hash columns and return a mismatch error message, if any.

    Args:
        file: The row to update in place with the computed hashes.
        sha256_hex: Computed SHA-256 of the staged file.
        crc32_hex: Computed CRC32 of the staged file.

    Returns:
        An error message if the filename declares a CRC32 that doesn't match
        the computed one, else None.
    """
    file.hash_sha256 = sha256_hex
    file.crc32_computed = crc32_hex
    file.crc32_extracted = extract_crc32(file.original_filename)
    if file.crc32_extracted is not None and file.crc32_extracted != crc32_hex:
        return (
            f"CRC32 mismatch — corrupt download (expected {file.crc32_extracted}, got {crc32_hex})"
        )
    return None


def _staging_path_for(
    remote_path: str, staging_root: str, remote_roots: list[str] | None = None
) -> Path:
    """Return the local staging destination, mirroring only the sub-path within a scan root.

    Only the portion of *remote_path* found *inside* whichever configured
    *remote_roots* entry contains it is mirrored under *staging_root* — the
    root itself is a long, deeply nested prefix shared by every file on
    that SFTP source (e.g. ``/data/sdaa1/myuser/path/to/files/``) and
    carries no useful information. Mirroring it verbatim into every staged
    path routinely pushed the staged path past Windows' ~260-character
    limit and broke transfers, even though only the directories/files
    *within* the configured root (e.g. a show subdirectory) are meaningful.

    For example: remote ``/data/sdaa1/myuser/path/to/files/anime/ep.mkv``
    with a configured root of ``/data/sdaa1/myuser/path/to/files/`` and
    staging root ``k:/staging`` becomes ``k:/staging/anime/ep.mkv`` — not
    ``k:/staging/data/sdaa1/myuser/path/to/files/anime/ep.mkv``.

    When *remote_path* doesn't fall under any entry in *remote_roots* (or
    none are given, e.g. a root of just ``/``), the full path is mirrored
    as before — there's nothing safe to strip.

    Args:
        remote_path: Full path of the file on the remote SFTP server.
        staging_root: Local staging directory root.
        remote_roots: Configured SFTP scan roots (``SFTP_REMOTE_PATHS``).
            The longest entry that is an ancestor of (or equal to)
            *remote_path* is stripped before mirroring.

    Returns:
        Absolute :class:`Path` for the staging destination.

    Raises:
        ValueError: If the resolved destination escapes the staging root
            (e.g. remote path contains ``..`` segments).
    """
    # Strip leading slash so Path joining works correctly
    relative = remote_path.lstrip("/")
    if remote_roots:
        best_match = ""
        for root in remote_roots:
            normalized = root.strip("/")
            matches = normalized and (
                relative == normalized or relative.startswith(normalized + "/")
            )
            if matches and len(normalized) > len(best_match):
                best_match = normalized
        if best_match:
            relative = relative[len(best_match) :].lstrip("/")
    destination = Path(staging_root) / relative
    resolved = destination.resolve()
    staging_resolved = Path(staging_root).resolve()
    if not resolved.is_relative_to(staging_resolved):
        raise ValueError(f"Path traversal detected: {remote_path!r} resolves outside staging root")
    return destination


def _post_download_status(file: DownloadedFile) -> FileStatus:
    """Return the status a file transitions to once its transfer completes.

    Files tagged with ``ignored_reason`` at discovery time (noscan-path
    files) go straight to ``IGNORED`` instead of ``DOWNLOADED`` so they
    never enter the parse/match pipeline.

    Args:
        file: The file whose transfer just completed.

    Returns:
        ``FileStatus.IGNORED`` if ``file.ignored_reason`` is set, else
        ``FileStatus.DOWNLOADED``.
    """
    return FileStatus.IGNORED if file.ignored_reason else FileStatus.DOWNLOADED


@dataclass
class DownloadResult:
    """Result of a batch SFTP download operation."""

    files_downloaded: int
    bytes_downloaded: int
    files_failed: int
    dry_run: bool


class DownloadOrchestrator:
    """Download DISCOVERED DownloadedFile records from SFTP to a local staging area.

    Files land under ``local_staging_path`` with their directory structure
    *relative to the configured scan root* preserved (see
    :func:`_staging_path_for`) — not the full remote path, which on a
    deeply nested SFTP layout can push staged paths past Windows' path
    length limit for no benefit. ``show_id`` is still NULL at this stage;
    the parse phase links each file to a show after download.

    Args:
        session: Active async SQLAlchemy session (must be created with
            ``expire_on_commit=False`` so file objects remain usable after
            each intermediate commit).
        sftp: Configured SFTPService instance.
        local_staging_path: Root directory for staging downloads.
        remote_paths: Configured SFTP scan roots (``SFTP_REMOTE_PATHS``),
            used to strip the common remote prefix from each file's
            staging destination. Defaults to mirroring the full remote
            path when not given.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        local_staging_path: str,
        remote_paths: list[str] | None = None,
    ) -> None:
        self.session = session
        self.sftp = sftp
        self.local_staging_path = local_staging_path
        self.remote_paths = remote_paths

    async def run(
        self,
        dry_run: bool = False,
        max_workers: int = 8,
        stale_downloading_seconds: int = 3600,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
        on_event: Callable[[str, str, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        """Download all DISCOVERED files, updating status to DOWNLOADED or ERROR.

        In non-dry-run mode files are processed in batches of up to
        ``max_workers``.  Each batch is claimed atomically with
        ``SELECT … FOR UPDATE SKIP LOCKED``, marked DOWNLOADING, committed
        (locks released so other workers can proceed), then downloaded in
        parallel via ``asyncio.gather``.  DB status updates happen
        sequentially after the parallel transfers complete.

        Args:
            dry_run: Log what would be downloaded without performing transfers.
            max_workers: Maximum concurrent SFTP transfers per batch.
            stale_downloading_seconds: A DOWNLOADING row untouched for longer
                than this is treated as abandoned (e.g. a crash between
                marking it DOWNLOADING and recording its outcome) and
                reclaimed by this run instead of being skipped forever.
            on_progress: Optional async callback(current, total, message).
                Called sequentially after each batch; callers may raise
                TaskCancelledError inside the callback to abort the run.
            on_event: Optional async callback(level, message, ctx) for
                structured per-file event log entries.

        Returns:
            DownloadResult with counts.
        """

        async def _emit(level: str, msg: str, ctx: dict[str, Any] | None = None) -> None:
            if on_event:
                try:
                    await on_event(level, msg, ctx)
                except Exception:
                    logger.warning("Event logging failed; continuing", exc_info=True)

        files_downloaded = 0
        bytes_downloaded = 0
        files_failed = 0

        # Only retry ERROR files that never reached staging (local_path IS NULL).
        # Parse and route failures also land in ERROR but have a staging local_path;
        # re-downloading them would undo pipeline progress.
        #
        # Also reclaim DOWNLOADING rows stale beyond stale_downloading_seconds: a
        # crash (or a failed final status-commit) between marking a file DOWNLOADING
        # and recording its outcome otherwise leaves it stuck there forever, since
        # no other query ever re-selects DOWNLOADING rows.
        stale_cutoff = datetime.now(UTC) - timedelta(seconds=stale_downloading_seconds)
        base_where = (
            (DownloadedFile.status == FileStatus.DISCOVERED)
            | ((DownloadedFile.status == FileStatus.ERROR) & (DownloadedFile.local_path.is_(None)))
            | (
                (DownloadedFile.status == FileStatus.DOWNLOADING)
                & (DownloadedFile.updated_at < stale_cutoff)
            )
        )

        if dry_run:
            stmt = select(DownloadedFile).where(base_where)
            rows = list((await self.session.execute(stmt)).scalars().all())
            total = len(rows)

            for idx, file in enumerate(rows, 1):
                if on_progress:
                    await on_progress(idx, total, f"Downloading {file.original_filename}")
                local_path = _staging_path_for(
                    file.remote_path, self.local_staging_path, self.remote_paths
                )
                logger.info("[DRY RUN] Would download %s → %s", file.remote_path, local_path)
                await _emit(
                    "info",
                    f"[Dry run] Would download {file.original_filename!r} → {local_path}",
                    {"file_id": file.id, "dest": str(local_path)},
                )
                files_downloaded += 1

            logger.info(
                "Download complete: %d downloaded, %d failed, %d bytes (dry_run=%s)",
                files_downloaded,
                files_failed,
                bytes_downloaded,
                dry_run,
            )
            return DownloadResult(
                files_downloaded=files_downloaded,
                bytes_downloaded=bytes_downloaded,
                files_failed=files_failed,
                dry_run=dry_run,
            )

        # Count upfront for accurate progress reporting (no lock held).
        count_stmt = select(func.count(DownloadedFile.id)).where(base_where)
        total = (await self.session.execute(count_stmt)).scalar_one()

        progress_idx = 0

        while True:
            # Claim up to max_workers eligible rows; other workers skip locked rows.
            stmt = (
                select(DownloadedFile)
                .where(base_where)
                .with_for_update(skip_locked=True, of=DownloadedFile)
                .limit(max_workers)
            )

            batch = list((await self.session.execute(stmt)).scalars().all())
            if not batch:
                break

            # Mark all batch files DOWNLOADING before releases the locks.
            pending: list[tuple[DownloadedFile, Path]] = []
            for file in batch:
                if file.status == FileStatus.DOWNLOADING:
                    logger.warning(
                        "Reclaiming stale DOWNLOADING file (stuck since %s): %s",
                        file.updated_at,
                        file.remote_path,
                    )
                    await _emit(
                        "warning",
                        f"Retrying stuck download {file.original_filename!r} "
                        "(left DOWNLOADING by a previous, apparently crashed run)",
                        {"file_id": file.id},
                    )
                local_path = _staging_path_for(
                    file.remote_path, self.local_staging_path, self.remote_paths
                )
                file.status = FileStatus.DOWNLOADING
                pending.append((file, local_path))

            # Flush DOWNLOADING status and commit to release FOR UPDATE locks.
            await self.session.flush()
            await self.session.commit()

            gather_cleanup_done = False
            try:
                if on_progress and pending:
                    await on_progress(progress_idx, total, f"Downloading {len(pending)} files")

                tasks = [
                    asyncio.ensure_future(self.sftp.download_file(file.remote_path, local_path))
                    for file, local_path in pending
                ]

                try:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                except BaseException:
                    # Outer task cancelled while gather was in flight.
                    # Tasks that completed successfully must be credited, not reset.
                    for (file, local_path), task in zip(pending, tasks, strict=True):
                        if task.done() and not task.cancelled() and task.exception() is None:
                            r = task.result()
                            sha256_hex, crc32_hex = await asyncio.to_thread(_hash_file, local_path)
                            mismatch = _verify_integrity(file, sha256_hex, crc32_hex)
                            if mismatch is not None:
                                file.status = FileStatus.ERROR
                                file.error_message = mismatch
                                file.local_path = None
                                files_failed += 1
                                await _emit(
                                    "error",
                                    f"{mismatch}: {file.original_filename!r}",
                                    {"file_id": file.id},
                                )
                            else:
                                file.status = _post_download_status(file)
                                file.local_path = str(local_path)
                                file.file_size = r.size
                                file.error_message = None
                                files_downloaded += 1
                                bytes_downloaded += r.size
                                suffix = (
                                    " (noscan — excluded from matching)"
                                    if file.ignored_reason
                                    else ""
                                )
                                await _emit(
                                    "info",
                                    f"Downloaded {file.original_filename!r}{suffix}",
                                    {"file_id": file.id, "bytes": r.size},
                                )
                        elif file.status == FileStatus.DOWNLOADING:
                            file.status = FileStatus.ERROR
                            file.error_message = "Download interrupted"
                            files_failed += 1
                            await _emit(
                                "error",
                                f"Download interrupted: {file.original_filename!r}",
                                {"file_id": file.id},
                            )
                    try:
                        await self.session.flush()
                        await self.session.commit()
                    except Exception:
                        logger.warning(
                            "Could not persist interrupted statuses; "
                            "manual recovery via PATCH /files/<id> may be required"
                        )
                    gather_cleanup_done = True
                    raise

                # Update statuses sequentially — safe because all SFTP I/O is done.
                for (file, local_path), result in zip(pending, results, strict=True):
                    if isinstance(result, BaseException):
                        error_msg = (
                            "Download interrupted"
                            if isinstance(result, asyncio.CancelledError)
                            else str(result)
                        )
                        logger.error("Failed to download %s: %s", file.remote_path, result)
                        file.status = FileStatus.ERROR
                        file.error_message = error_msg
                        files_failed += 1
                        await _emit(
                            "error",
                            f"Failed to download {file.original_filename!r}: {error_msg}",
                            {"file_id": file.id, "error": error_msg},
                        )
                    else:
                        sha256_hex, crc32_hex = await asyncio.to_thread(_hash_file, local_path)
                        mismatch = _verify_integrity(file, sha256_hex, crc32_hex)
                        if mismatch is not None:
                            logger.error("%s: %s", mismatch, file.remote_path)
                            file.status = FileStatus.ERROR
                            file.error_message = mismatch
                            file.local_path = None
                            files_failed += 1
                            await _emit(
                                "error",
                                f"{mismatch}: {file.original_filename!r}",
                                {"file_id": file.id},
                            )
                            continue
                        file.status = _post_download_status(file)
                        file.local_path = str(local_path)
                        file.file_size = result.size
                        file.error_message = None
                        files_downloaded += 1
                        bytes_downloaded += result.size
                        suffix = " (noscan — excluded from matching)" if file.ignored_reason else ""
                        await _emit(
                            "info",
                            f"Downloaded {file.original_filename!r}{suffix}",
                            {"file_id": file.id, "bytes": result.size},
                        )

                await self.session.flush()
                await self.session.commit()

                # Emit progress after committing so the DB reflects final state.
                if on_progress:
                    for file, _ in pending:
                        progress_idx += 1
                        msg = (
                            f"Downloaded {file.original_filename}"
                            if file.status in (FileStatus.DOWNLOADED, FileStatus.IGNORED)
                            else f"Failed {file.original_filename}"
                        )
                        await on_progress(progress_idx, total, msg)

            except BaseException:
                if not gather_cleanup_done:
                    for file, _ in pending:
                        if file.status == FileStatus.DOWNLOADING:
                            file.status = FileStatus.ERROR
                            file.error_message = "Download interrupted"
                            files_failed += 1
                            await _emit(
                                "error",
                                f"Download interrupted: {file.original_filename!r}",
                                {"file_id": file.id},
                            )
                    try:
                        await self.session.flush()
                        await self.session.commit()
                    except Exception:
                        logger.warning(
                            "Could not persist interrupted statuses; "
                            "manual recovery via PATCH /files/<id> may be required"
                        )
                raise

        logger.info(
            "Download complete: %d downloaded, %d failed, %d bytes (dry_run=%s)",
            files_downloaded,
            files_failed,
            bytes_downloaded,
            dry_run,
        )
        return DownloadResult(
            files_downloaded=files_downloaded,
            bytes_downloaded=bytes_downloaded,
            files_failed=files_failed,
            dry_run=dry_run,
        )
