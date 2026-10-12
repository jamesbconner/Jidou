"""Shared SFTP discovery steps for the scan and seed orchestrators.

Both orchestrators start the same way: shallow-list every configured remote
path, split the children into files and directories, then deep-walk the
directories in one concurrent batch. They differ only in what they do with
the results (scan emits events and records ``DISCOVERED`` rows; seed logs and
records ``SEEDED`` rows), so the discovery half lives here and each caller
keeps its own reporting.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from jidou.services.sftp_service import RecursiveListResult, RemoteFile, SFTPService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RootListing:
    """Result of shallow-listing every configured remote path.

    Attributes:
        files: Files found directly under the roots, in listing order.
        dirs: Directories found directly under the roots, in listing order.
        failed_roots: Number of roots whose listing raised and was skipped.
    """

    files: list[RemoteFile]
    dirs: list[RemoteFile]
    failed_roots: int


@dataclass(frozen=True)
class WalkOutcome:
    """Result of deep-walking a batch of directories.

    Attributes:
        walked: ``(directory, result)`` for each walk that returned, in batch order.
        failures: ``(directory, exception)`` for each walk that raised, in batch order.
    """

    walked: list[tuple[str, RecursiveListResult]]
    failures: list[tuple[str, BaseException]]


async def list_roots(
    sftp: SFTPService,
    remote_paths: Sequence[str],
    *,
    before_each: Callable[[int, int, str], Awaitable[None]] | None = None,
    on_error: Callable[[str, Exception], Awaitable[None]] | None = None,
) -> RootListing:
    """Shallow-list each remote path, tolerating a failure on any one of them.

    Args:
        sftp: Connected SFTP service.
        remote_paths: Root directories to list, in order.
        before_each: Awaited as ``(index, total, root)`` (1-based index) before each
            listing, e.g. to report progress. Its errors propagate.
        on_error: Awaited as ``(root, exception)`` after a listing fails and has been
            logged. Its errors propagate.

    Returns:
        The files and directories found, plus how many roots failed.
    """
    files: list[RemoteFile] = []
    dirs: list[RemoteFile] = []
    failed_roots = 0
    total = len(remote_paths)
    for idx, root in enumerate(remote_paths, 1):
        if before_each is not None:
            await before_each(idx, total, root)
        try:
            children = await sftp.list_remote_children(root)
        except Exception as exc:
            # One unreachable root must not stop the others from being inventoried.
            logger.exception("Failed to list remote path %s; skipping", root)
            failed_roots += 1
            if on_error is not None:
                await on_error(root, exc)
            continue
        files.extend(c for c in children if not c.is_dir)
        dirs.extend(c for c in children if c.is_dir)
    return RootListing(files=files, dirs=dirs, failed_roots=failed_roots)


async def walk_directories(sftp: SFTPService, dir_paths: list[str]) -> WalkOutcome:
    """Deep-walk *dir_paths* concurrently in one batch, splitting successes from failures.

    Args:
        sftp: Connected SFTP service.
        dir_paths: Directories to walk. An empty list makes no SFTP call.

    Returns:
        Walk results and failures, each in batch order.
    """
    walked: list[tuple[str, RecursiveListResult]] = []
    failures: list[tuple[str, BaseException]] = []
    if not dir_paths:
        return WalkOutcome(walked=walked, failures=failures)
    for dir_path, outcome in await sftp.list_remote_files_recursive_batch(dir_paths):
        if isinstance(outcome, BaseException):
            failures.append((dir_path, outcome))
        else:
            walked.append((dir_path, outcome))
    return WalkOutcome(walked=walked, failures=failures)
