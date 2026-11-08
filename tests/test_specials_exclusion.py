"""Specials (season 0) must stay out of missing / wanted / calendar / next-up queries.

The route tests elsewhere mock the session, so they never run SQL. These tests
record the statements each route executes and assert on the compiled text, which
is the only thing that distinguishes "excludes season 0" from "doesn't".
"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from jidou.api.dependencies import get_tmdb
from jidou.database import get_session
from jidou.main import app

# Season 0 is excluded with this exact predicate everywhere a query counts or
# lists episodes as wanted.
_EXCLUDES_SPECIALS = "episodes.season_number != 0"


def _recording_session(executed: list[str]) -> Any:
    """Return a session dependency whose ``execute`` records compiled SQL.

    Args:
        executed: List that receives one compiled statement per ``execute`` call.

    Returns:
        An async-generator dependency override yielding the recording session.
    """

    async def _override() -> AsyncIterator[MagicMock]:
        result = MagicMock()
        result.all.return_value = []
        result.first.return_value = None
        result.scalars.return_value.all.return_value = []
        result.scalar_one_or_none.return_value = None

        async def _execute(stmt: Any, *_args: Any, **_kwargs: Any) -> MagicMock:
            compiled = stmt.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
            executed.append(" ".join(str(compiled).split()))
            return result

        session = MagicMock()
        session.execute = AsyncMock(side_effect=_execute)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        yield session

    return _override


@pytest.fixture
def executed() -> Any:
    """Yield the list of statements a request executed; clean up overrides after."""
    statements: list[str] = []
    app.dependency_overrides[get_session] = _recording_session(statements)
    app.dependency_overrides[get_tmdb] = lambda: MagicMock()
    try:
        yield statements
    finally:
        app.dependency_overrides.clear()


def test_calendar_excludes_specials(executed: list[str]) -> None:
    """The calendar never lists season 0 episodes."""
    response = TestClient(app).get("/api/shows/calendar?start=2026-07-01&end=2026-07-14")

    assert response.status_code == 200
    assert any(_EXCLUDES_SPECIALS in sql for sql in executed)


def test_sync_missing_ignores_season_zero_gaps(executed: list[str]) -> None:
    """A show whose only unmet episode is a special is not re-synced as "missing"."""
    response = TestClient(app).post(
        "/api/shows/calendar/sync-missing?start=2026-07-01&end=2026-07-14"
    )

    assert response.status_code == 200
    assert _EXCLUDES_SPECIALS in executed[0]


def test_watchlist_next_up_skips_specials(executed: list[str]) -> None:
    """ "Next up" is the first unwatched regular episode, never a season 0 one."""
    response = TestClient(app).get("/api/watchlist")

    assert response.status_code == 200
    assert any(_EXCLUDES_SPECIALS in sql for sql in executed)


def test_show_list_episode_and_progress_counts_exclude_specials(
    executed: list[str],
) -> None:
    """Every flat episode count -- total, watched, missing, aired, matched -- leaves season 0 out.

    The query already carries the filter three times (the per-season subquery
    and what hangs off it); each of the five flat counts adds one more. The
    total/watched pair drives the show card's progress bar, which must not drop
    below complete because of specials.
    """
    response = TestClient(app).get("/api/shows")

    assert response.status_code == 200
    assert executed[0].count(_EXCLUDES_SPECIALS) == 8
