"""Shared bulk-existence-check and duplicate-safe-insert helpers for orchestrators.

Checking whether a large batch of remote paths is already tracked one row at
a time (a SELECT per path) is an N+1 query pattern; checking them all in a
single unbounded IN() clause risks an oversized query for a very large batch.
``chunked_existing_paths`` chunks the check into bounded IN() queries instead.

``insert_or_skip_duplicate`` centralises the "insert a row, but tolerate a
concurrent writer winning a unique-constraint race" pattern used whenever two
orchestrator runs (or a scan and a seed) could try to create the same
DownloadedFile/ScannedDirectory row at the same time.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

logger = logging.getLogger(__name__)

# Number of paths to batch into a single existence-check query.
EXISTENCE_CHUNK = 1_000


async def chunked_existing_paths(
    session: AsyncSession,
    column: InstrumentedAttribute[str],
    paths: list[str],
    chunk_size: int = EXISTENCE_CHUNK,
) -> set[str]:
    """Return the subset of *paths* already present in *column*'s table.

    Args:
        session: Active async SQLAlchemy session.
        column: The mapped column to check membership against (e.g.
            ``DownloadedFile.remote_path``, ``ScannedDirectory.remote_path``).
        paths: Candidate paths to check. May be empty.
        chunk_size: Maximum paths per IN() query.

    Returns:
        Set of paths from *paths* that already exist in the table.
    """
    existing: set[str] = set()
    for i in range(0, len(paths), chunk_size):
        chunk = paths[i : i + chunk_size]
        stmt = select(column).where(column.in_(chunk))
        rows = (await session.execute(stmt)).scalars().all()
        existing.update(rows)
    return existing


async def insert_or_skip_duplicate(session: AsyncSession, obj: object) -> bool:
    """Insert *obj* via a savepoint, tolerating a concurrent duplicate-row race.

    Wraps the add in ``session.begin_nested()`` so a unique-constraint
    violation (pgcode 23505 — a concurrent scan/seed run already created the
    same row) only rolls back this one insert, not the whole transaction.
    Any other integrity error (e.g. a foreign-key violation) is a real bug
    and is re-raised.

    Args:
        session: Active async SQLAlchemy session.
        obj: The ORM instance to insert (not yet added to the session).

    Returns:
        True if inserted; False if skipped because a concurrent writer
        already won the race to create this row.

    Raises:
        IntegrityError: If the failure is not a unique-constraint race.
    """
    try:
        async with session.begin_nested():
            session.add(obj)
        return True
    except IntegrityError as exc:
        orig = getattr(exc, "orig", None)
        pgcode = getattr(orig, "pgcode", None)
        if pgcode is not None and pgcode != "23505":
            raise
        logger.debug("Insert skipped due to unique-constraint race: %r", obj)
        return False
