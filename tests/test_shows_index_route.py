"""Tests for ``GET /api/shows/index`` (DF-18): the lightweight library index.

The index feeds pickers and ``tmdb_id:media_type`` lookups in the frontend,
so it must stay a single column-only query that scales to several thousand
shows: no ORM entity loads, no relationship loads, no per-row queries.
"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select

from jidou.database import get_session
from jidou.main import app
from jidou.models.show import Show
from tests.test_api_contract import _served_routes

# Exact field set of ShowIndexEntry, in schema order.
_INDEX_FIELDS = [
    "id",
    "tmdb_id",
    "title",
    "sys_name",
    "aliases",
    "media_type",
    "content_type",
    "local_path",
]


def _row(**overrides: Any) -> dict[str, Any]:
    """Build one column-only index row as the DB would return it."""
    row: dict[str, Any] = {
        "id": 1,
        "tmdb_id": 100,
        "title": "Example Show",
        "sys_name": "Example Show",
        "aliases": ["Example"],
        "media_type": "tv",
        "content_type": "anime",
        "local_path": "/media/anime/Example Show",
    }
    row.update(overrides)
    return row


def _mock_session(rows: list[dict[str, Any]]) -> tuple[AsyncMock, Any]:
    """Return a mock session whose single execute() yields *rows* as mappings.

    Returns:
        The session mock (to inspect ``execute`` calls) and the dependency
        override that yields it.
    """
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)

    async def _override() -> AsyncIterator[AsyncMock]:
        yield session

    return session, _override


@pytest.fixture
def index_session() -> Any:
    """Install a mock DB session for the duration of one test."""
    rows = [
        _row(),
        _row(
            id=2,
            tmdb_id=200,
            title="Other Film",
            sys_name=None,
            aliases=None,
            media_type="movie",
            content_type=None,
            local_path=None,
        ),
    ]
    session, override = _mock_session(rows)
    app.dependency_overrides[get_session] = override
    try:
        yield session
    finally:
        app.dependency_overrides.clear()


def _executed_stmt(session: AsyncMock) -> Select[Any]:
    stmt = session.execute.await_args.args[0]
    assert isinstance(stmt, Select)
    return stmt


def test_index_returns_exact_lightweight_fields(index_session: AsyncMock) -> None:
    """Each entry carries exactly the index fields, nothing from ShowList/ShowRead."""
    response = TestClient(app).get("/api/shows/index")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert all(list(entry) == _INDEX_FIELDS for entry in body)
    assert body[0] == _row()
    assert body[1]["aliases"] is None
    assert body[1]["content_type"] is None
    assert body[1]["media_type"] == "movie"


def test_index_is_one_column_only_query(index_session: AsyncMock) -> None:
    """One execute, selecting only the index columns from ``shows`` (no N+1, no joins)."""
    TestClient(app).get("/api/shows/index")

    # A single round trip regardless of library size: no per-show queries.
    assert index_session.execute.await_count == 1
    stmt = _executed_stmt(index_session)
    # Column-only select: no ORM entity is loaded, so no lazy/eager
    # relationship loading can be triggered by serialization.
    assert [c.key for c in stmt.selected_columns] == _INDEX_FIELDS
    assert all(d["expr"] is not Show for d in stmt.column_descriptions)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "JOIN" not in sql.upper()
    assert sql.count("FROM") == 1
    assert "FROM shows" in sql
    # The index is the whole library: no LIMIT/OFFSET truncation.
    assert "LIMIT" not in sql.upper()
    assert "OFFSET" not in sql.upper()


def test_index_orders_by_title_then_id(index_session: AsyncMock) -> None:
    """Ordering is deterministic: title ascending, then id as the tie-breaker."""
    TestClient(app).get("/api/shows/index")

    sql = str(_executed_stmt(index_session).compile(dialect=postgresql.dialect()))
    assert sql.endswith("ORDER BY shows.title ASC, shows.id ASC")


def test_index_returns_rows_in_query_order() -> None:
    """The route does not re-sort; it returns rows in the DB's (title, id) order."""
    rows = [
        _row(id=5, tmdb_id=500, title="Alpha"),
        _row(id=2, tmdb_id=200, title="Beta"),
        _row(id=9, tmdb_id=900, title="Beta"),
    ]
    _, override = _mock_session(rows)
    app.dependency_overrides[get_session] = override
    try:
        response = TestClient(app).get("/api/shows/index")
    finally:
        app.dependency_overrides.clear()

    assert [e["id"] for e in response.json()] == [5, 2, 9]


def test_index_empty_library_returns_empty_list() -> None:
    """An empty library yields ``[]``, not an error."""
    _, override = _mock_session([])
    app.dependency_overrides[get_session] = override
    try:
        response = TestClient(app).get("/api/shows/index")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []


def test_index_route_registered_before_show_id_route() -> None:
    """``/shows/index`` must precede ``/shows/{show_id}`` or it is shadowed (422)."""
    get_paths = [
        r.path
        for r in _served_routes(app)
        if "GET" in r.methods and r.path.startswith("/api/shows")
    ]
    assert len(get_paths) >= 5
    assert "/api/shows/index" in get_paths
    assert "/api/shows/{show_id}" in get_paths
    assert get_paths.index("/api/shows/index") < get_paths.index("/api/shows/{show_id}")


def test_index_is_not_captured_by_show_id_route(index_session: AsyncMock) -> None:
    """A request to /shows/index hits the index handler, not get_show (no 422)."""
    response = TestClient(app).get("/api/shows/index")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
