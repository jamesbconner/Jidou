"""Tests for the GET /shows/calendar API route."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from jidou.database import get_session
from jidou.main import app
from jidou.models.episode import Episode
from jidou.models.show import Show

_TODAY = date.today()


def _make_show(
    *, id: int = 1, title: str = "Test Show", poster_path: str | None = None
) -> MagicMock:
    s = MagicMock(spec=Show)
    s.id = id
    s.title = title
    s.poster_path = poster_path
    return s


def _make_episode(
    *,
    id: int = 1,
    show_id: int = 1,
    season_number: int = 1,
    episode_number: int = 1,
    name: str = "Episode Name",
    air_date: date,
    file_tracked: bool = False,
) -> MagicMock:
    e = MagicMock(spec=Episode)
    e.id = id
    e.show_id = show_id
    e.season_number = season_number
    e.episode_number = episode_number
    e.name = name
    e.air_date = air_date
    e.file_tracked = file_tracked
    return e


def _session_override(rows: list[tuple[MagicMock, MagicMock]]) -> object:
    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        yield session

    return _mock_session


def _get_calendar(rows: list[tuple[MagicMock, MagicMock]], start: str, end: str):
    app.dependency_overrides[get_session] = _session_override(rows)
    try:
        return TestClient(app).get(f"/api/shows/calendar?start={start}&end={end}")
    finally:
        app.dependency_overrides.clear()


class TestCalendarStatus:
    def test_tracked_status(self) -> None:
        """An aired episode with a tracked file gets status='tracked'."""
        show = _make_show()
        episode = _make_episode(air_date=_TODAY - timedelta(days=1), file_tracked=True)

        response = _get_calendar([(episode, show)], "2026-07-01", "2026-07-14")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "tracked"

    def test_missing_status(self) -> None:
        """An aired episode with no tracked file gets status='missing'."""
        show = _make_show()
        episode = _make_episode(air_date=_TODAY - timedelta(days=1), file_tracked=False)

        response = _get_calendar([(episode, show)], "2026-07-01", "2026-07-14")

        assert response.status_code == 200
        assert response.json()[0]["status"] == "missing"

    def test_upcoming_status(self) -> None:
        """A future air_date gets status='upcoming' regardless of file_tracked."""
        show = _make_show()
        episode = _make_episode(air_date=_TODAY + timedelta(days=3), file_tracked=False)

        response = _get_calendar([(episode, show)], "2026-07-01", "2026-07-14")

        assert response.status_code == 200
        assert response.json()[0]["status"] == "upcoming"

    def test_today_with_tracked_file_is_tracked_not_upcoming(self) -> None:
        """An episode airing exactly today is treated as already-aired, not upcoming."""
        show = _make_show()
        episode = _make_episode(air_date=_TODAY, file_tracked=True)

        response = _get_calendar([(episode, show)], "2026-07-01", "2026-07-14")

        assert response.status_code == 200
        assert response.json()[0]["status"] == "tracked"


class TestCalendarResponseShape:
    def test_response_includes_show_and_episode_fields(self) -> None:
        show = _make_show(id=7, title="Attack on Titan", poster_path="/poster.jpg")
        episode = _make_episode(
            id=42,
            show_id=7,
            season_number=2,
            episode_number=5,
            name="A New World",
            air_date=_TODAY - timedelta(days=1),
            file_tracked=True,
        )

        response = _get_calendar([(episode, show)], "2026-07-01", "2026-07-14")

        assert response.status_code == 200
        entry = response.json()[0]
        assert entry["episode_id"] == 42
        assert entry["show_id"] == 7
        assert entry["show_title"] == "Attack on Titan"
        assert entry["poster_path"] == "/poster.jpg"
        assert entry["season_number"] == 2
        assert entry["episode_number"] == 5
        assert entry["name"] == "A New World"
        assert entry["air_date"] == (_TODAY - timedelta(days=1)).isoformat()

    def test_multiple_shows_same_day_all_appear(self) -> None:
        show_a = _make_show(id=1, title="Show A")
        show_b = _make_show(id=2, title="Show B")
        ep_a = _make_episode(id=1, show_id=1, air_date=_TODAY, file_tracked=True)
        ep_b = _make_episode(id=2, show_id=2, air_date=_TODAY, file_tracked=False)

        response = _get_calendar([(ep_a, show_a), (ep_b, show_b)], "2026-07-01", "2026-07-14")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert {e["show_title"] for e in data} == {"Show A", "Show B"}

    def test_empty_range_returns_empty_list(self) -> None:
        response = _get_calendar([], "2026-07-01", "2026-07-14")

        assert response.status_code == 200
        assert response.json() == []


class TestCalendarValidation:
    def test_missing_start_returns_422(self) -> None:
        app.dependency_overrides[get_session] = _session_override([])
        try:
            response = TestClient(app).get("/api/shows/calendar?end=2026-07-14")
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 422

    def test_invalid_date_format_returns_422(self) -> None:
        app.dependency_overrides[get_session] = _session_override([])
        try:
            response = TestClient(app).get("/api/shows/calendar?start=not-a-date&end=2026-07-14")
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 422
