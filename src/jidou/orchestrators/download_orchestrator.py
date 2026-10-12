"""Orchestrator for downloading DISCOVERED files from SFTP to the local staging area."""

import asyncio
import hashlib
import logging
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.orchestrators._events import EventSink
from jidou.services.callbacks import OnEvent, OnProgress
from jidou.services.filename_parser import extract_crc32
from jidou.services.sftp_service import DownloadResult as SFTPDownloadResult
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


@dataclass
class _Tally:
    """Running totals for one download run, turned into a :class:`DownloadResult` at the end."""

    downloaded: int = 0
    failed: int = 0
    bytes: int = 0

    def record(self, ok: bool, size: int) -> None:
        """Count one finished transfer as downloaded (with its size) or failed.

        Args:
            ok: Whether the transfer was recorded successfully.
            size: Transferred size in bytes, counted only when ``ok``.
        """
        if ok:
            self.downloaded += 1
            self.bytes += size
        else:
            self.failed += 1


# One claimed batch: each row paired with its local staging destination.
_Pending = list[tuple[DownloadedFile, Path]]


def _complete(tally: _Tally, dry_run: bool) -> DownloadResult:
    """Log the run summary and build the :class:`DownloadResult`.

    Args:
        tally: Final running totals.
        dry_run: Whether this was a dry run.

    Returns:
        The result for the caller.
    """
    logger.info(
        "Download complete: %d downloaded, %d failed, %d bytes (dry_run=%s)",
        tally.downloaded,
        tally.failed,
        tally.bytes,
        dry_run,
    )
    return DownloadResult(
        files_downloaded=tally.downloaded,
        bytes_downloaded=tally.bytes,
        files_failed=tally.failed,
        dry_run=dry_run,
    )


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
        on_progress: OnProgress | None = None,
        on_event: OnEvent | None = None,
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

        sink = EventSink(on_event, swallow_errors=True)
        tally = _Tally()

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
            return await self._dry_run_preview(base_where, on_progress, sink)

        # Count upfront for accurate progress reporting (no lock held).
        count_stmt = select(func.count(DownloadedFile.id)).where(base_where)
        total = (await self.session.execute(count_stmt)).scalar_one()

        progress_idx = 0

        # An empty claim means nothing eligible is left.
        while pending := await self._claim_batch(base_where, max_workers, sink):
            gather_cleanup_done = False
            try:
                if on_progress:
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
                    await self._credit_finished_transfers(pending, tasks, tally, sink)
                    await self._persist_best_effort()
                    gather_cleanup_done = True
                    raise

                # Update statuses sequentially — safe because all SFTP I/O is done.
                await self._apply_results(pending, results, tally, sink)

                await self.session.flush()
                await self.session.commit()

                # Emit progress after committing so the DB reflects final state.
                progress_idx = await self._report_batch_progress(
                    pending, progress_idx, total, on_progress
                )

            except BaseException:
                if not gather_cleanup_done:
                    tally.failed += await self._mark_interrupted(pending, sink)
                    await self._persist_best_effort()
                raise

        return _complete(tally, dry_run)

    async def _dry_run_preview(
        self,
        base_where: ColumnElement[bool],
        on_progress: OnProgress | None,
        sink: EventSink,
    ) -> DownloadResult:
        """Log and emit what a real run would download, without any transfer or write.

        Args:
            base_where: Eligibility predicate shared with the real run.
            on_progress: Optional progress callback, called once per file.
            sink: Event sink for the per-file "would download" events.

        Returns:
            A dry-run ``DownloadResult`` counting every eligible file as downloaded.
        """
        tally = _Tally()
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
            await sink(
                "info",
                f"[Dry run] Would download {file.original_filename!r} → {local_path}",
                {"file_id": file.id, "dest": str(local_path)},
            )
            tally.downloaded += 1

        return _complete(tally, dry_run=True)

    async def _claim_batch(
        self,
        base_where: ColumnElement[bool],
        max_workers: int,
        sink: EventSink,
    ) -> _Pending:
        """Claim up to ``max_workers`` eligible rows, mark them DOWNLOADING and commit.

        Args:
            base_where: Eligibility predicate.
            max_workers: Maximum batch size.
            sink: Event sink for the stale-reclaim warning.

        Returns:
            The claimed ``(file, staging_path)`` pairs; empty when nothing is
            eligible (in which case nothing is flushed or committed).
        """
        # Claim up to max_workers eligible rows; other workers skip locked rows.
        stmt = (
            select(DownloadedFile)
            .where(base_where)
            .with_for_update(skip_locked=True, of=DownloadedFile)
            .limit(max_workers)
        )

        batch = list((await self.session.execute(stmt)).scalars().all())
        if not batch:
            return []

        # Mark all batch files DOWNLOADING before releases the locks.
        pending: _Pending = []
        for file in batch:
            if file.status == FileStatus.DOWNLOADING:
                logger.warning(
                    "Reclaiming stale DOWNLOADING file (stuck since %s): %s",
                    file.updated_at,
                    file.remote_path,
                )
                await sink(
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
        return pending

    async def _credit_finished_transfers(
        self,
        pending: _Pending,
        tasks: Sequence[asyncio.Future[SFTPDownloadResult]],
        tally: _Tally,
        sink: EventSink,
    ) -> None:
        """After an outer cancel, credit completed transfers and fail the rest.

        Args:
            pending: The batch, in task order.
            tasks: The transfer futures matching ``pending`` one-to-one.
            tally: Running totals, updated in place.
            sink: Event sink.
        """
        for (file, local_path), task in zip(pending, tasks, strict=True):
            if task.done() and not task.cancelled() and task.exception() is None:
                size = task.result().size
                # The cancel path historically does not write the mismatch log line.
                ok = await self._record_transfer(file, local_path, size, sink, log_mismatch=False)
                tally.record(ok, size)
            elif file.status == FileStatus.DOWNLOADING:
                await self._interrupt_file(file, sink)
                tally.failed += 1

    async def _apply_results(
        self,
        pending: _Pending,
        results: list[SFTPDownloadResult | BaseException],
        tally: _Tally,
        sink: EventSink,
    ) -> None:
        """Record each gathered transfer outcome sequentially.

        Args:
            pending: The batch, in task order.
            results: ``asyncio.gather(..., return_exceptions=True)`` output.
            tally: Running totals, updated in place.
            sink: Event sink.
        """
        for (file, local_path), result in zip(pending, results, strict=True):
            if isinstance(result, BaseException):
                await self._record_failure(file, result, sink)
                tally.failed += 1
            else:
                ok = await self._record_transfer(
                    file, local_path, result.size, sink, log_mismatch=True
                )
                tally.record(ok, result.size)

    async def _record_transfer(
        self,
        file: DownloadedFile,
        local_path: Path,
        size: int,
        sink: EventSink,
        *,
        log_mismatch: bool,
    ) -> bool:
        """Hash and verify a transferred file, then set its status and emit the event.

        Args:
            file: The row whose transfer completed.
            local_path: Where the transfer landed.
            size: Transferred size in bytes.
            sink: Event sink.
            log_mismatch: Whether to also ``logger.error`` a CRC32 mismatch. Only
                the normal (non-cancelled) path does this today.

        Returns:
            True if the file was recorded as downloaded/ignored, False on a
            CRC32 mismatch (the row is set to ERROR with ``local_path`` cleared).
        """
        sha256_hex, crc32_hex = await asyncio.to_thread(_hash_file, local_path)
        mismatch = _verify_integrity(file, sha256_hex, crc32_hex)
        if mismatch is not None:
            if log_mismatch:
                logger.error("%s: %s", mismatch, file.remote_path)
            file.status = FileStatus.ERROR
            file.error_message = mismatch
            file.local_path = None
            await sink(
                "error",
                f"{mismatch}: {file.original_filename!r}",
                {"file_id": file.id},
            )
            return False
        file.status = _post_download_status(file)
        file.local_path = str(local_path)
        file.file_size = size
        file.error_message = None
        suffix = " (noscan — excluded from matching)" if file.ignored_reason else ""
        await sink(
            "info",
            f"Downloaded {file.original_filename!r}{suffix}",
            {"file_id": file.id, "bytes": size},
        )
        return True

    async def _record_failure(
        self, file: DownloadedFile, error: BaseException, sink: EventSink
    ) -> None:
        """Mark a file ERROR after its SFTP transfer raised, and emit the event.

        Args:
            file: The row whose transfer failed.
            error: The exception gathered for it.
            sink: Event sink.
        """
        error_msg = (
            "Download interrupted" if isinstance(error, asyncio.CancelledError) else str(error)
        )
        logger.error("Failed to download %s: %s", file.remote_path, error)
        file.status = FileStatus.ERROR
        file.error_message = error_msg
        await sink(
            "error",
            f"Failed to download {file.original_filename!r}: {error_msg}",
            {"file_id": file.id, "error": error_msg},
        )

    async def _interrupt_file(self, file: DownloadedFile, sink: EventSink) -> None:
        """Mark one DOWNLOADING file ERROR ("Download interrupted") and emit the event.

        Args:
            file: The row to fail.
            sink: Event sink.
        """
        file.status = FileStatus.ERROR
        file.error_message = "Download interrupted"
        await sink(
            "error",
            f"Download interrupted: {file.original_filename!r}",
            {"file_id": file.id},
        )

    async def _mark_interrupted(self, pending: _Pending, sink: EventSink) -> int:
        """Fail every still-DOWNLOADING file of the batch as interrupted.

        Args:
            pending: The batch.
            sink: Event sink.

        Returns:
            The number of files newly failed.
        """
        interrupted = 0
        for file, _ in pending:
            if file.status == FileStatus.DOWNLOADING:
                await self._interrupt_file(file, sink)
                interrupted += 1
        return interrupted

    async def _persist_best_effort(self) -> None:
        """Flush and commit interrupted statuses, logging instead of raising on failure.

        Used on the abort paths, where the original exception must win.
        """
        try:
            await self.session.flush()
            await self.session.commit()
        except Exception:
            logger.warning(
                "Could not persist interrupted statuses; "
                "manual recovery via PATCH /files/<id> may be required"
            )

    @staticmethod
    async def _report_batch_progress(
        pending: _Pending,
        progress_idx: int,
        total: int,
        on_progress: OnProgress | None,
    ) -> int:
        """Emit one progress call per file of a committed batch.

        Args:
            pending: The batch.
            progress_idx: Progress counter before this batch.
            total: Total files expected this run.
            on_progress: Optional progress callback.

        Returns:
            The updated progress counter.
        """
        if not on_progress:
            return progress_idx
        for file, _ in pending:
            progress_idx += 1
            msg = (
                f"Downloaded {file.original_filename}"
                if file.status in (FileStatus.DOWNLOADED, FileStatus.IGNORED)
                else f"Failed {file.original_filename}"
            )
            await on_progress(progress_idx, total, msg)
        return progress_idx
