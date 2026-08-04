"""Tests for the shared chunked bulk-existence-check and duplicate-safe-insert helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from jidou.models.downloaded_file import DownloadedFile
from jidou.orchestrators._bulk_existence import chunked_existing_paths, insert_or_skip_duplicate


def _make_session(existing_by_chunk: list[list[str]]) -> AsyncMock:
    """Return a mock session whose execute() yields one chunk's existing paths per call."""
    session = AsyncMock()
    results = []
    for chunk in existing_by_chunk:
        result = MagicMock()
        result.scalars.return_value.all.return_value = chunk
        results.append(result)
    session.execute = AsyncMock(side_effect=results)
    return session


@pytest.mark.asyncio
async def test_empty_input_returns_empty_set_without_querying() -> None:
    """No paths means no query at all."""
    session = AsyncMock()
    session.execute = AsyncMock()

    result = await chunked_existing_paths(session, DownloadedFile.remote_path, [])

    assert result == set()
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_returns_only_paths_that_exist() -> None:
    """Paths not found in the table are excluded from the result."""
    session = _make_session([["/a/1.mkv", "/a/3.mkv"]])

    result = await chunked_existing_paths(
        session, DownloadedFile.remote_path, ["/a/1.mkv", "/a/2.mkv", "/a/3.mkv"]
    )

    assert result == {"/a/1.mkv", "/a/3.mkv"}


@pytest.mark.asyncio
async def test_chunks_at_boundary_size() -> None:
    """Exactly chunk_size paths fit in a single query."""
    paths = [f"/a/{i}.mkv" for i in range(5)]
    session = _make_session([paths])

    result = await chunked_existing_paths(session, DownloadedFile.remote_path, paths, chunk_size=5)

    assert session.execute.call_count == 1
    assert result == set(paths)


@pytest.mark.asyncio
async def test_chunks_above_boundary_size_issues_multiple_queries() -> None:
    """One more path than chunk_size requires a second query."""
    paths = [f"/a/{i}.mkv" for i in range(6)]
    session = _make_session([paths[:5], paths[5:]])

    result = await chunked_existing_paths(session, DownloadedFile.remote_path, paths, chunk_size=5)

    assert session.execute.call_count == 2
    assert result == set(paths)


@pytest.mark.asyncio
async def test_chunks_below_boundary_size_issues_one_query() -> None:
    """Fewer paths than chunk_size still issues exactly one query."""
    paths = [f"/a/{i}.mkv" for i in range(3)]
    session = _make_session([paths])

    result = await chunked_existing_paths(session, DownloadedFile.remote_path, paths, chunk_size=5)

    assert session.execute.call_count == 1
    assert result == set(paths)


class _FakeNestedTransaction:
    """Mimics AsyncSession.begin_nested()'s async context manager.

    Never swallows the exception raised inside the ``with`` block -- like the
    real SAVEPOINT context manager, it just lets it propagate to the caller.
    """

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc

    async def __aenter__(self) -> "_FakeNestedTransaction":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _make_insert_session(exc: Exception | None) -> AsyncMock:
    """Return a mock session whose begin_nested() raises *exc* on exit, if given."""
    session = AsyncMock()
    session.add = MagicMock()
    if exc is None:
        session.begin_nested = MagicMock(return_value=_FakeNestedTransaction())
    else:
        err: Exception = exc

        class _RaisingNested(_FakeNestedTransaction):
            async def __aexit__(self, exc_type: object, exc_val: object, tb: object) -> bool:
                raise err

        session.begin_nested = MagicMock(return_value=_RaisingNested())
    return session


def _make_integrity_error(pgcode: str | None) -> IntegrityError:
    """Build an IntegrityError whose ``.orig`` carries *pgcode* (or lacks it, if None)."""
    orig = MagicMock(spec=[] if pgcode is None else ["pgcode"])
    if pgcode is not None:
        orig.pgcode = pgcode
    return IntegrityError("INSERT", {}, orig)


@pytest.mark.asyncio
async def test_insert_or_skip_duplicate_returns_true_on_success() -> None:
    """A clean insert reports success and adds the object to the session."""
    session = _make_insert_session(None)
    obj = object()

    result = await insert_or_skip_duplicate(session, obj)

    assert result is True
    session.add.assert_called_once_with(obj)


@pytest.mark.asyncio
async def test_insert_or_skip_duplicate_swallows_unique_violation() -> None:
    """pgcode 23505 (unique violation) is a benign concurrent-writer race and is skipped."""
    session = _make_insert_session(_make_integrity_error("23505"))

    result = await insert_or_skip_duplicate(session, object())

    assert result is False


@pytest.mark.asyncio
async def test_insert_or_skip_duplicate_reraises_other_pgcode() -> None:
    """A different pgcode (e.g. foreign-key violation) is a real bug and must propagate."""
    session = _make_insert_session(_make_integrity_error("23503"))

    with pytest.raises(IntegrityError):
        await insert_or_skip_duplicate(session, object())


@pytest.mark.asyncio
async def test_insert_or_skip_duplicate_reraises_when_pgcode_missing() -> None:
    """Regression test for #433: an unknown/absent pgcode must not be treated as benign.

    ``getattr(orig, "pgcode", None)`` returns None both when the driver never
    set a pgcode and when ``orig`` itself is missing -- either way that's an
    unconfirmed cause, not a confirmed unique-violation race, so it must
    re-raise rather than being silently skipped.
    """
    session = _make_insert_session(_make_integrity_error(None))

    with pytest.raises(IntegrityError):
        await insert_or_skip_duplicate(session, object())
