"""Tests for the shared chunked bulk-existence-check helper."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.downloaded_file import DownloadedFile
from jidou.orchestrators._bulk_existence import chunked_existing_paths


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
