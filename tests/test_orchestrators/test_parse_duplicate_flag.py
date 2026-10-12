"""Duplicate-file flagging in ParseOrchestrator (DF-13, decision D33).

When parse links a file to an episode that already has another
non-synthetic file in MATCHED, ROUTING or ROUTED, the new file is flagged
with ``duplicate_of_file_id`` and a warning is emitted. Both files are kept.

These tests drive ``ParseOrchestrator.run`` with a mock session: the show and
episode lookups are patched, and the duplicate lookup is the only query after
the initial file listing, so its statement can be inspected. The same
behaviour is exercised against a real PostgreSQL in
``tests/test_duplicate_file_flag_pg.py``.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator
from jidou.services.filename_parser import FilenameParseResult

_MOD = "jidou.orchestrators.parse_orchestrator"


def _file(file_id: int, filename: str, status: FileStatus, remote_path: str) -> DownloadedFile:
    """Build a transient DownloadedFile row.

    Args:
        file_id: Primary key to assign.
        filename: ``original_filename``.
        status: Lifecycle status.
        remote_path: Unique remote path (synthetic rows use the import scheme).

    Returns:
        A DownloadedFile not attached to any session.
    """
    return DownloadedFile(
        id=file_id,
        original_filename=filename,
        remote_path=remote_path,
        status=status,
        file_size=0,
    )


def _show() -> MagicMock:
    """Return a matched show that needs no alias, content-type or path backfill."""
    show = MagicMock()
    show.id = 10
    show.title = "Example Show"
    show.aliases = ["example show"]
    show.local_path = "/library/Example Show"
    show.content_type = "tv"
    return show


def _episode() -> MagicMock:
    """Return the resolved episode S01E05 (id 50)."""
    ep = MagicMock()
    ep.id = 50
    ep.season_number = 1
    ep.episode_number = 5
    return ep


def _session(files: list[DownloadedFile], existing: DownloadedFile | None) -> MagicMock:
    """Mock session: the first query lists *files*; later ones find *existing*.

    Args:
        files: Rows returned by the DOWNLOADED/UNMATCHED listing.
        existing: The row the duplicate lookup returns (None for no duplicate).

    Returns:
        A mock AsyncSession.
    """
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    listing = MagicMock()
    listing.scalars.return_value.all.return_value = files
    lookup = MagicMock()
    lookup.scalars.return_value.first.return_value = existing
    lookup.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(side_effect=[listing, lookup, lookup])
    return session


def _parsed() -> FilenameParseResult:
    """Return the parser result for an ``Example Show S01E05`` filename."""
    return FilenameParseResult(
        show_name="Example Show",
        season=1,
        episode=5,
        crc32=None,
        content_type="tv",
        confidence=0.9,
        llm_ok=False,
    )


async def _run(session: MagicMock, events: list[tuple[str, str, dict[str, Any]]]) -> None:
    """Run ParseOrchestrator with lookups patched, recording emitted events.

    Args:
        session: The mock session.
        events: Receives ``(level, message, ctx)`` for every event.
    """

    async def _on_event(level: str, message: str, ctx: dict[str, Any]) -> None:
        events.append((level, message, ctx))

    with (
        patch(f"{_MOD}.parse_filename", AsyncMock(return_value=_parsed())),
        patch(f"{_MOD}.find_show_by_name", AsyncMock(return_value=_show())),
        patch(f"{_MOD}.resolve_episode", AsyncMock(return_value=_episode())),
        patch(f"{_MOD}.dismiss_orphans_for_file", AsyncMock()),
    ):
        await ParseOrchestrator(session, llm=None).run(on_event=_on_event)


def _lookup_sql(session: MagicMock) -> str:
    """Compile the duplicate-lookup statement (the second query) with literal binds.

    Args:
        session: The mock session after a run.

    Returns:
        The statement's PostgreSQL SQL text.
    """
    assert session.execute.await_count >= 2, "the duplicate lookup never ran"
    stmt = session.execute.await_args_list[1].args[0]
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_parse_flags_second_file_for_same_episode() -> None:
    """A second file for an already-matched episode is flagged and a warning is emitted."""
    original = _file(1, "Example.Show.S01E05.mkv", FileStatus.ROUTED, "/remote/a.mkv")
    new = _file(2, "Example.Show.S01E05.v2.mkv", FileStatus.DOWNLOADED, "/remote/b.mkv")
    session = _session([new], original)
    events: list[tuple[str, str, dict[str, Any]]] = []

    await _run(session, events)

    # Both files are kept: the new one is still MATCHED to the same episode.
    assert new.status == FileStatus.MATCHED
    assert new.episode_id == 50
    assert getattr(new, "duplicate_of_file_id", None) == 1
    assert original.status == FileStatus.ROUTED
    warnings = [(msg, ctx) for level, msg, ctx in events if level == "warn"]
    assert warnings == [
        (
            "Episode S01E05 of 'Example Show' already has 'Example.Show.S01E05.mkv'; "
            "'Example.Show.S01E05.v2.mkv' flagged as a duplicate (both kept)",
            {"file_id": 2, "duplicate_of_file_id": 1, "episode_id": 50},
        )
    ]


@pytest.mark.asyncio
async def test_parse_does_not_flag_synthetic_import_rows() -> None:
    """The lookup skips synthetic-import rows, so a file next to one is not flagged."""
    new = _file(2, "Example.Show.S01E05.mkv", FileStatus.DOWNLOADED, "/remote/b.mkv")
    session = _session([new], None)
    events: list[tuple[str, str, dict[str, Any]]] = []

    await _run(session, events)

    sql = _lookup_sql(session)
    assert "downloaded_files.remote_path NOT LIKE 'synthetic-import://%%'" in sql
    assert new.status == FileStatus.MATCHED
    assert new.duplicate_of_file_id is None
    assert not [e for e in events if e[0] == "warn"]


@pytest.mark.asyncio
async def test_parse_duplicate_lookup_shape() -> None:
    """The lookup targets the same episode, settled statuses, other rows, lowest id first."""
    new = _file(7, "Example.Show.S01E05.mkv", FileStatus.UNMATCHED, "/remote/b.mkv")
    session = _session([new], None)

    await _run(session, [])

    sql = _lookup_sql(session)
    assert "downloaded_files.episode_id = 50" in sql
    assert "downloaded_files.id != 7" in sql
    assert "downloaded_files.status IN ('matched', 'routing', 'routed')" in sql
    assert "ORDER BY downloaded_files.id" in sql
    assert "LIMIT 1" in sql


@pytest.mark.asyncio
async def test_reparse_does_not_self_flag_and_clears_stale_flag() -> None:
    """Re-parsing a file against its own earlier link never points it at itself.

    The lookup excludes the file's own id (checked above); with no other file
    on the episode the flag is cleared rather than left over from an earlier
    parse.
    """
    new = _file(7, "Example.Show.S01E05.mkv", FileStatus.UNMATCHED, "/remote/b.mkv")
    new.episode_id = 50
    new.duplicate_of_file_id = 3  # stale flag from an earlier parse
    session = _session([new], None)
    events: list[tuple[str, str, dict[str, Any]]] = []

    await _run(session, events)

    assert new.status == FileStatus.MATCHED
    assert new.episode_id == 50
    assert new.duplicate_of_file_id is None
    assert not [e for e in events if e[0] == "warn"]
