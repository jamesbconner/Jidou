"""Unit tests for jidou.api.lookups."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from jidou.api.lookups import get_or_404, get_show_or_404, one_or_404
from jidou.models.show import Show


def _session_returning(value: object) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _executed_sql(session: AsyncMock) -> str:
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_one_or_404_returns_row() -> None:
    row = MagicMock()
    session = _session_returning(row)
    assert asyncio.run(one_or_404(session, select(Show), detail="x")) is row


def test_one_or_404_raises_404_with_exact_detail() -> None:
    session = _session_returning(None)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(one_or_404(session, select(Show), detail="Thing not found"))
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Thing not found"


def test_get_or_404_filters_by_criteria() -> None:
    session = _session_returning(MagicMock())
    asyncio.run(get_or_404(session, Show, Show.id == 7, detail="Show not found"))
    sql = _executed_sql(session)
    assert "FROM shows" in sql
    assert "WHERE" in sql
    assert "FOR UPDATE" not in sql


def test_get_or_404_for_update_emits_for_update() -> None:
    session = _session_returning(MagicMock())
    asyncio.run(get_or_404(session, Show, Show.id == 7, detail="Show not found", for_update=True))
    assert "FOR UPDATE" in _executed_sql(session)


def test_get_show_or_404_uses_canonical_detail() -> None:
    session = _session_returning(None)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_show_or_404(session, 123))
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Show not found"


def test_get_show_or_404_returns_show() -> None:
    show = MagicMock(spec=Show)
    session = _session_returning(show)
    assert asyncio.run(get_show_or_404(session, 1)) is show
