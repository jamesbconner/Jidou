"""Reconcile ``downloaded_files`` rows against what actually exists on disk."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus

logger = logging.getLogger(__name__)

# Statuses reflecting a file mid-pipeline, where local_path may be unset or
# still a transient staging path — never worth an existence check.
_IN_FLIGHT_STATUSES = frozenset(
    {
        FileStatus.DISCOVERED,
        FileStatus.DOWNLOADING,
        FileStatus.PENDING,
        FileStatus.ROUTING,
    }
)


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of a single :func:`reconcile_local_file_existence` pass."""

    marked_missing: int
    restored: int


def _paths_present(paths: list[str]) -> list[bool]:
    """Synchronously check which of *paths* are real files. Run off the event loop."""
    return [Path(p).is_file() for p in paths]


async def reconcile_local_file_existence(
    db_session: AsyncSession, show_id: int
) -> ReconciliationResult:
    """Sync ``downloaded_files.status`` for a show against on-disk reality.

    Flags rows whose ``local_path`` no longer exists as ``FileStatus.MISSING``,
    and restores previously-flagged rows to ``unmatched``/``matched`` if their
    file has reappeared at the same path. Skips rows in an in-flight pipeline
    status, where ``local_path`` may be unset or only a transient staging path.

    Args:
        db_session: DB session (injected).
        show_id: Show whose files should be reconciled.

    Returns:
        Counts of rows newly marked missing and rows restored.
    """
    stmt = select(DownloadedFile).where(
        DownloadedFile.show_id == show_id,
        DownloadedFile.local_path.is_not(None),
        DownloadedFile.status.not_in(_IN_FLIGHT_STATUSES),
    )
    rows = list((await db_session.execute(stmt)).scalars().all())
    if not rows:
        return ReconciliationResult(marked_missing=0, restored=0)

    paths = [row.local_path for row in rows if row.local_path is not None]
    present = await asyncio.to_thread(_paths_present, paths)

    marked_missing = 0
    restored = 0
    for row, exists in zip(rows, present, strict=True):
        if not exists and row.status != FileStatus.MISSING:
            row.status = FileStatus.MISSING
            marked_missing += 1
        elif exists and row.status == FileStatus.MISSING:
            row.status = FileStatus.MATCHED if row.episode_id is not None else FileStatus.UNMATCHED
            restored += 1

    if marked_missing or restored:
        await db_session.commit()
        logger.info(
            "file_reconciliation.completed",
            extra={"show_id": show_id, "marked_missing": marked_missing, "restored": restored},
        )

    return ReconciliationResult(marked_missing=marked_missing, restored=restored)
