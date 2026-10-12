"""Duplicate-file flagging against a real PostgreSQL (DF-13, decision D33).

Skipped unless ``JIDOU_TEST_PG_URL`` names an asyncpg URL of a throwaway
database already migrated to ``alembic upgrade head``. Running against the
migrated schema (not ``create_all``) also proves the migration's foreign key
really is ``ON DELETE SET NULL``.

Every test runs inside one outer transaction that is rolled back afterwards;
the orchestrator's own ``commit()`` only releases a savepoint, so nothing is
left behind in the database.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator
from jidou.services.synthetic_file import synthetic_remote_path

_PG_URL = os.environ.get("JIDOU_TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not _PG_URL,
    reason="JIDOU_TEST_PG_URL is not set (needs a throwaway PostgreSQL migrated to head)",
)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a session whose work is rolled back when the test ends."""
    assert _PG_URL is not None
    engine = create_async_engine(_PG_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        db = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield db
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


async def _show_with_episode(db: AsyncSession) -> tuple[Show, Episode]:
    """Insert ``Example Show`` with its S01E05 episode.

    Args:
        db: The test session.

    Returns:
        The show and the episode, flushed so both have ids.
    """
    show = Show(
        tmdb_id=990001,
        title="Example Show",
        media_type="tv",
        aliases=["example show"],
        local_path="/library/Example Show",
    )
    db.add(show)
    await db.flush()
    ep = Episode(show_id=show.id, tmdb_id=990101, season_number=1, episode_number=5, name="Five")
    db.add(ep)
    await db.flush()
    return show, ep


def _file(name: str, remote_path: str, status: FileStatus, **kw: object) -> DownloadedFile:
    """Build a DownloadedFile row.

    Args:
        name: ``original_filename``.
        remote_path: Unique remote path.
        status: Lifecycle status.
        **kw: Extra column values.

    Returns:
        A new, not yet added, DownloadedFile.
    """
    return DownloadedFile(
        original_filename=name, remote_path=remote_path, status=status, file_size=0, **kw
    )


async def test_pg_parse_flags_second_file_for_same_episode(session: AsyncSession) -> None:
    """The newer file is flagged against the lowest-id settled file; both are kept."""
    show, ep = await _show_with_episode(session)
    first = _file("A.mkv", "/r/a.mkv", FileStatus.ROUTED, show_id=show.id, episode_id=ep.id)
    second = _file("B.mkv", "/r/b.mkv", FileStatus.MATCHED, show_id=show.id, episode_id=ep.id)
    session.add_all([first, second])
    await session.flush()
    new = _file("Example.Show.S01E05.v2.mkv", "/r/c.mkv", FileStatus.DOWNLOADED)
    session.add(new)
    await session.flush()

    result = await ParseOrchestrator(session, llm=None).run()

    assert result.files_matched == 1
    assert new.status == FileStatus.MATCHED
    assert new.episode_id == ep.id
    assert new.duplicate_of_file_id == first.id  # lowest id wins
    assert first.duplicate_of_file_id is None
    assert first.status == FileStatus.ROUTED


async def test_pg_parse_does_not_flag_synthetic_import_rows(session: AsyncSession) -> None:
    """A synthetic-import row on the episode is not an original."""
    show, ep = await _show_with_episode(session)
    synthetic = _file(
        "A.mkv",
        synthetic_remote_path("/library/Example Show/A.mkv"),
        FileStatus.ROUTED,
        show_id=show.id,
        episode_id=ep.id,
    )
    unsettled = _file("U.mkv", "/r/u.mkv", FileStatus.ERROR, show_id=show.id, episode_id=ep.id)
    session.add_all([synthetic, unsettled])
    new = _file("Example.Show.S01E05.mkv", "/r/c.mkv", FileStatus.DOWNLOADED)
    session.add(new)
    await session.flush()

    await ParseOrchestrator(session, llm=None).run()

    assert new.status == FileStatus.MATCHED
    assert new.episode_id == ep.id
    assert new.duplicate_of_file_id is None


async def test_pg_reparse_does_not_self_flag(session: AsyncSession) -> None:
    """Re-parsing a file already linked to the episode does not flag it against itself."""
    show, ep = await _show_with_episode(session)
    new = _file(
        "Example.Show.S01E05.mkv",
        "/r/c.mkv",
        FileStatus.UNMATCHED,
        show_id=show.id,
        episode_id=ep.id,
    )
    session.add(new)
    await session.flush()

    await ParseOrchestrator(session, llm=None).run()

    assert new.status == FileStatus.MATCHED
    assert new.episode_id == ep.id
    assert new.duplicate_of_file_id is None


async def test_pg_deleting_original_clears_flag(session: AsyncSession) -> None:
    """ON DELETE SET NULL: deleting the original clears the duplicate's flag."""
    original = _file("A.mkv", "/r/a.mkv", FileStatus.ROUTED)
    session.add(original)
    await session.flush()
    dup = _file("B.mkv", "/r/b.mkv", FileStatus.MATCHED, duplicate_of_file_id=original.id)
    session.add(dup)
    await session.flush()
    dup_id = dup.id

    await session.execute(delete(DownloadedFile).where(DownloadedFile.id == original.id))
    session.expunge_all()

    flag = await session.scalar(
        select(DownloadedFile.duplicate_of_file_id).where(DownloadedFile.id == dup_id)
    )
    assert flag is None
