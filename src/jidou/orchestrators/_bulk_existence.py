"""Shared chunked bulk-existence-check helper for orchestrators.

Checking whether a large batch of remote paths is already tracked one row at
a time (a SELECT per path) is an N+1 query pattern; checking them all in a
single unbounded IN() clause risks an oversized query for a very large batch.
This chunks the check into bounded IN() queries instead.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

# Number of paths to batch into a single existence-check query.
_EXISTENCE_CHUNK = 1_000


async def chunked_existing_paths(
    session: AsyncSession,
    column: InstrumentedAttribute[str],
    paths: list[str],
    chunk_size: int = _EXISTENCE_CHUNK,
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
