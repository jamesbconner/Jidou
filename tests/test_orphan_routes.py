"""Tests for the /orphans API routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.show import Show

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orphan(
    *,
    id: int = 1,
    show_id: int = 1,
    tracked_filename: str | None = "/media/show.s01e05.mkv",
    tracked_source: str = "import",
    old_season_number: int = 1,
    old_episode_number: int = 5,
    downloaded_file_id: int | None = None,
) -> MagicMock:
    """Build a minimal OrphanedTrackingRecord mock."""
    o = MagicMock(spec=OrphanedTrackingRecord)
    o.id = id
    o.show_id = show_id
    o.tracked_filename = tracked_filename
    o.tracked_source = tracked_source
    o.old_season_number = old_season_number
    o.old_episode_number = old_episode_number
    o.downloaded_file_id = downloaded_file_id
    o.created_at = datetime.now(UTC)
    return o


def _make_show_mock(*, id: int = 1, title: str = "Test Show") -> MagicMock:
    s = MagicMock(spec=Show)
    s.id = id
    s.title = title
    return s


def _make_episode_mock(*, id: int = 10, show_id: int = 1) -> MagicMock:
    ep = MagicMock(spec=Episode)
    ep.id = id
    ep.show_id = show_id
    ep.file_tracked = False
    ep.tracked_filename = None
    ep.tracked_source = None
    ep.file_tracked_at = None
    return ep


def _make_file_mock(*, id: int = 50) -> MagicMock:
    f = MagicMock(spec=DownloadedFile)
    f.id = id
    f.episode_id = None
    return f


def _list_session(
    orphans: list[MagicMock],
    show_title_pairs: list[tuple[MagicMock, str]] | None = None,
) -> "type[AsyncMock]":
    """Session for list_orphans — returns (orphan, title) rows."""

    async def _mock() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        if show_title_pairs is not None:
            result.all.return_value = show_title_pairs
        else:
            result.all.return_value = [(o, "Test Show") for o in orphans]
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        yield session

    return _mock  # type: ignore[return-value]


def _show_orphan_session(
    show: MagicMock | None,
    orphans: list[MagicMock],
) -> "type[AsyncMock]":
    """Session for list_orphans_for_show — show lookup then orphan list."""

    async def _mock() -> AsyncMock:
        session = AsyncMock()
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        orphan_result = MagicMock()
        orphan_scalars = MagicMock()
        orphan_scalars.all.return_value = orphans
        orphan_result.scalars.return_value = orphan_scalars
        session.execute = AsyncMock(side_effect=[show_result, orphan_result])
        session.flush = AsyncMock()
        yield session

    return _mock  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /api/orphans
# ---------------------------------------------------------------------------


def test_list_orphans_returns_200() -> None:
    """GET /api/orphans returns a list of orphan records."""
    from jidou.database import get_session

    orphan = _make_orphan()
    app.dependency_overrides[get_session] = _list_session([orphan])
    try:
        response = TestClient(app).get("/api/orphans")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["id"] == 1
        assert body[0]["show_title"] == "Test Show"
        assert body[0]["tracked_source"] == "import"
        assert body[0]["old_season_number"] == 1
        assert body[0]["old_episode_number"] == 5
    finally:
        app.dependency_overrides.clear()


def test_list_orphans_empty_returns_empty_list() -> None:
    """GET /api/orphans with no records returns []."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _list_session([])
    try:
        response = TestClient(app).get("/api/orphans")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/orphans/show/{show_id}
# ---------------------------------------------------------------------------


def test_list_orphans_for_show_returns_200() -> None:
    """GET /api/orphans/show/{id} returns orphans for that show."""
    from jidou.database import get_session

    show = _make_show_mock()
    orphan = _make_orphan()
    app.dependency_overrides[get_session] = _show_orphan_session(show, [orphan])
    try:
        response = TestClient(app).get("/api/orphans/show/1")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["show_title"] == "Test Show"
    finally:
        app.dependency_overrides.clear()


def test_list_orphans_for_show_returns_404_when_show_missing() -> None:
    """GET /api/orphans/show/{id} returns 404 when show not found."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _show_orphan_session(None, [])
    try:
        response = TestClient(app).get("/api/orphans/show/999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /api/orphans/{orphan_id}
# ---------------------------------------------------------------------------


def _single_orphan_session(orphan: MagicMock | None) -> "type[AsyncMock]":
    """Session returning a single orphan (or None) for dismiss/resolve."""

    async def _mock() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = orphan
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        yield session

    return _mock  # type: ignore[return-value]


def test_dismiss_orphan_returns_204() -> None:
    """DELETE /api/orphans/{id} deletes the record and returns 204."""
    from jidou.database import get_session

    orphan = _make_orphan()
    app.dependency_overrides[get_session] = _single_orphan_session(orphan)
    try:
        response = TestClient(app).delete("/api/orphans/1")
        assert response.status_code == 204
    finally:
        app.dependency_overrides.clear()


def test_dismiss_orphan_returns_404_when_not_found() -> None:
    """DELETE /api/orphans/{id} returns 404 when record does not exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _single_orphan_session(None)
    try:
        response = TestClient(app).delete("/api/orphans/999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/orphans/{orphan_id}/resolve
# ---------------------------------------------------------------------------


def _resolve_session(
    orphan: MagicMock | None,
    episode: MagicMock | None = None,
    file: MagicMock | None = None,
) -> "type[AsyncMock]":
    """Session for resolve endpoint — orphan, episode, optional file lookups."""

    async def _mock() -> AsyncMock:
        session = AsyncMock()
        orphan_result = MagicMock()
        orphan_result.scalar_one_or_none.return_value = orphan
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = episode
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = file
        session.execute = AsyncMock(side_effect=[orphan_result, ep_result, file_result])
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        yield session

    return _mock  # type: ignore[return-value]


def test_resolve_import_orphan_sets_episode_tracking() -> None:
    """POST /api/orphans/{id}/resolve writes tracking to the Episode for imported orphans."""
    from jidou.database import get_session

    orphan = _make_orphan(tracked_source="import", downloaded_file_id=None)
    ep = _make_episode_mock()
    app.dependency_overrides[get_session] = _resolve_session(orphan, ep)
    try:
        response = TestClient(app).post("/api/orphans/1/resolve", json={"episode_id": 10})
        assert response.status_code == 204
        assert ep.file_tracked is True
        assert ep.tracked_filename == "/media/show.s01e05.mkv"
        assert ep.tracked_source == "import"
        assert ep.file_tracked_at is not None
    finally:
        app.dependency_overrides.clear()


def test_resolve_match_orphan_without_file_sets_match_source() -> None:
    """POST /api/orphans/{id}/resolve uses record.tracked_source, not hardcoded 'import'.

    A match-sourced orphan with downloaded_file_id=None (file deleted or lacked
    parsed S/E) should resolve with tracked_source='match', not 'import'.
    """
    from jidou.database import get_session

    orphan = _make_orphan(tracked_source="match", downloaded_file_id=None)
    ep = _make_episode_mock()
    app.dependency_overrides[get_session] = _resolve_session(orphan, ep)
    try:
        response = TestClient(app).post("/api/orphans/1/resolve", json={"episode_id": 10})
        assert response.status_code == 204
        assert ep.file_tracked is True
        assert ep.tracked_source == "match"
        assert ep.tracked_filename == "/media/show.s01e05.mkv"
    finally:
        app.dependency_overrides.clear()


def test_resolve_download_orphan_links_file_to_episode() -> None:
    """POST /api/orphans/{id}/resolve links the DownloadedFile and marks Episode tracked."""
    from jidou.database import get_session

    orphan = _make_orphan(tracked_source="match", downloaded_file_id=50)
    ep = _make_episode_mock()
    file = _make_file_mock()
    app.dependency_overrides[get_session] = _resolve_session(orphan, ep, file)
    try:
        response = TestClient(app).post("/api/orphans/1/resolve", json={"episode_id": 10})
        assert response.status_code == 204
        assert file.episode_id == 10
        assert ep.file_tracked is True
        assert ep.tracked_source == "match"
        assert ep.tracked_filename == "/media/show.s01e05.mkv"
        assert ep.file_tracked_at is not None
    finally:
        app.dependency_overrides.clear()


def test_resolve_orphan_returns_422_when_episode_belongs_to_wrong_show() -> None:
    """POST /api/orphans/{id}/resolve returns 422 when the episode is from a different show."""
    from jidou.database import get_session

    orphan = _make_orphan(show_id=1)
    ep = _make_episode_mock(show_id=99)  # wrong show
    app.dependency_overrides[get_session] = _resolve_session(orphan, ep)
    try:
        response = TestClient(app).post("/api/orphans/1/resolve", json={"episode_id": 10})
        assert response.status_code == 422
        assert "does not belong" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_resolve_orphan_returns_404_when_orphan_missing() -> None:
    """POST /api/orphans/{id}/resolve returns 404 when orphan not found."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _resolve_session(None)
    try:
        response = TestClient(app).post("/api/orphans/999/resolve", json={"episode_id": 10})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_resolve_orphan_returns_404_when_episode_missing() -> None:
    """POST /api/orphans/{id}/resolve returns 404 when target episode not found."""
    from jidou.database import get_session

    orphan = _make_orphan(tracked_source="import")
    app.dependency_overrides[get_session] = _resolve_session(orphan, None)
    try:
        response = TestClient(app).post("/api/orphans/1/resolve", json={"episode_id": 999})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_resolve_download_orphan_returns_404_when_file_missing() -> None:
    """POST /api/orphans/{id}/resolve returns 404 when DownloadedFile no longer exists."""
    from jidou.database import get_session

    orphan = _make_orphan(tracked_source="match", downloaded_file_id=50)
    ep = _make_episode_mock()
    app.dependency_overrides[get_session] = _resolve_session(orphan, ep, None)
    try:
        response = TestClient(app).post("/api/orphans/1/resolve", json={"episode_id": 10})
        assert response.status_code == 404
        assert "no longer exists" in response.json()["detail"]
        assert ep.file_tracked is False
    finally:
        app.dependency_overrides.clear()


def test_resolve_orphan_returns_409_when_episode_already_tracked() -> None:
    """POST /api/orphans/{id}/resolve returns 409 when target episode is already tracked."""
    from jidou.database import get_session

    orphan = _make_orphan(tracked_source="import")
    ep = _make_episode_mock()
    ep.file_tracked = True
    app.dependency_overrides[get_session] = _resolve_session(orphan, ep)
    try:
        response = TestClient(app).post("/api/orphans/1/resolve", json={"episode_id": 10})
        assert response.status_code == 409
        assert "already tracked" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
