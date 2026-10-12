"""Queries for downloaded files that a route serializes as ``FileRead``.

``FileRead`` embeds the file's ``show`` and ``episode``. Those relationships
are never loaded implicitly, so every query whose result becomes a
``FileRead`` must load them explicitly; these helpers are the one place that
says how.
"""

from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.models.downloaded_file import DownloadedFile


def select_file_read() -> Select[tuple[DownloadedFile]]:
    """Return a ``select(DownloadedFile)`` that also loads ``show`` and ``episode``.

    Callers add their own ``where`` / ordering / paging clauses.

    Returns:
        The base statement for any query serialized as ``FileRead``.
    """
    return select(DownloadedFile).options(
        selectinload(DownloadedFile.show), selectinload(DownloadedFile.episode)
    )


async def reload_file_read(session: AsyncSession, *criteria: ColumnElement[bool]) -> DownloadedFile:
    """Re-select a file already held by *session*, with ``show`` and ``episode`` loaded.

    Used after a flush or commit, when the route returns an object it loaded
    (or created) earlier without those relationships. ``populate_existing``
    is required: without it SQLAlchemy keeps the instance already in the
    identity map as it is and the eager loaders never fill in the
    relationships. Run it after the flush/commit, so there are no pending
    changes for the refresh to overwrite.

    Args:
        session: The request's async DB session (the same one that changed the file).
        *criteria: ``WHERE`` clauses identifying exactly one file.

    Returns:
        The file, with ``show`` and ``episode`` loaded from the database.

    Raises:
        sqlalchemy.exc.NoResultFound: If no file matches.
        sqlalchemy.exc.MultipleResultsFound: If more than one file matches.
    """
    stmt = select_file_read().where(*criteria).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one()
