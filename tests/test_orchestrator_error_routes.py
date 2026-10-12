"""Route-level characterization of every error an orchestrator turns into an HTTP response.

These pin the status code and the *full* JSON body for each moved error path, so the move
from ``HTTPException`` / ``FeedOnboardingError`` to domain errors plus one handler is provably
byte-identical. They drive the real orchestrators through the real routes; only the session,
TMDB and ``fetch_show_metadata`` boundaries are faked.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.api.dependencies import get_llm_service, get_tmdb
from jidou.database import get_session
from jidou.main import app
from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.rss import RssFeed
from jidou.models.show import Show
from tests.test_shows_routes import _make_show, _make_tmdb_mock, _rematch_session

_NO_LOCAL_PATH = (
    "Show has no local_path configured; provide local_path or set it via PATCH /shows/{id}/paths"
)


@pytest.fixture(autouse=True)
def _clean_overrides() -> Iterator[None]:
    """Install inert TMDB/LLM dependencies and reset overrides around every test."""
    app.dependency_overrides[get_tmdb] = lambda: MagicMock()
    app.dependency_overrides[get_llm_service] = lambda: MagicMock()
    yield
    app.dependency_overrides.clear()


def _result(scalar: object = None) -> MagicMock:
    """Build an ``execute()`` result whose ``scalar_one_or_none`` is *scalar*."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    return r


def _session_returning(*results: MagicMock) -> Callable[[], AsyncIterator[AsyncMock]]:
    """Return a ``get_session`` override yielding a session with queued query results."""

    async def _mock() -> AsyncIterator[AsyncMock]:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=list(results))
        session.add = MagicMock()
        yield session

    return _mock


def _file() -> MagicMock:
    f = MagicMock(spec=DownloadedFile)
    f.id = 1
    f.status = FileStatus.UNMATCHED
    f.parsed_show_name = None
    return f


# --- POST /api/files/{id}/match ------------------------------------------------------------


def test_match_unknown_show_id_is_404_show_not_found() -> None:
    app.dependency_overrides[get_session] = _session_returning(_result(_file()), _result(None))
    r = TestClient(app).post("/api/files/1/match", json={"show_id": 5})
    assert (r.status_code, r.json()) == (404, {"detail": "Show not found"})


def test_match_show_without_local_path_is_422() -> None:
    show = MagicMock(spec=Show)
    show.local_path = None
    app.dependency_overrides[get_session] = _session_returning(_result(_file()), _result(show))
    r = TestClient(app).post("/api/files/1/match", json={"show_id": 5})
    assert (r.status_code, r.json()) == (422, {"detail": _NO_LOCAL_PATH})


def test_match_new_tmdb_show_without_local_path_is_422() -> None:
    app.dependency_overrides[get_session] = _session_returning(_result(_file()), _result(None))
    r = TestClient(app).post("/api/files/1/match", json={"tmdb_id": 1396})
    assert (r.status_code, r.json()) == (
        422,
        {"detail": "local_path is required when creating a new show via tmdb_id"},
    )


def test_match_tmdb_lookup_failure_is_404_with_cause() -> None:
    app.dependency_overrides[get_session] = _session_returning(_result(_file()), _result(None))
    with patch(
        "jidou.orchestrators.manual_match_orchestrator.fetch_show_metadata",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        r = TestClient(app).post(
            "/api/files/1/match", json={"tmdb_id": 1396, "local_path": "/media/x"}
        )
    assert (r.status_code, r.json()) == (404, {"detail": "TMDB lookup failed: boom"})


# --- POST /api/shows/{id}/rematch ----------------------------------------------------------


def test_rematch_tmdb_fetch_failure_is_502() -> None:
    tmdb = _make_tmdb_mock()
    tmdb.get_details = AsyncMock(side_effect=Exception("TMDB unavailable"))
    app.dependency_overrides[get_session] = _rematch_session(_make_show(id=1, tmdb_id=100))
    app.dependency_overrides[get_tmdb] = lambda: tmdb
    r = TestClient(app).post("/api/shows/1/rematch", json={"tmdb_id": 200})
    assert (r.status_code, r.json()) == (502, {"detail": "Failed to fetch TMDB details"})


def test_rematch_episode_sync_failure_is_502() -> None:
    tmdb = _make_tmdb_mock()
    tmdb.get_details = AsyncMock(
        return_value={"name": "Correct Show", "first_air_date": "2020-01-01"}
    )
    app.dependency_overrides[get_session] = _rematch_session(_make_show(id=1, tmdb_id=100))
    app.dependency_overrides[get_tmdb] = lambda: tmdb
    with patch("jidou.orchestrators.show_rematch_orchestrator.TMDBOrchestrator") as orch:
        orch.return_value.sync_show_episodes = AsyncMock(side_effect=Exception("Sync failed"))
        r = TestClient(app).post("/api/shows/1/rematch", json={"tmdb_id": 200})
    assert (r.status_code, r.json()) == (
        502,
        {"detail": "TMDB episode sync failed; rematch aborted"},
    )


# --- POST /api/rss/feeds/{id}/add-show -----------------------------------------------------


def test_add_show_unknown_library_show_is_404() -> None:
    feed = MagicMock(spec=RssFeed)
    feed.id = 7
    app.dependency_overrides[get_session] = _session_returning(_result(feed), _result(None))
    r = TestClient(app).post("/api/rss/feeds/7/add-show", json={"parsed_name": "x", "show_id": 999})
    assert (r.status_code, r.json()) == (404, {"detail": "Show not found"})
