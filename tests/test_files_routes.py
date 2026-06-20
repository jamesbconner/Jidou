"""Tests for the /files API routes."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.downloaded_file import DownloadedFile, FileStatus


def _make_file(
    *,
    id: int = 1,
    status: str = FileStatus.PENDING,
    show_id: int | None = None,
) -> MagicMock:
    """Build a minimal DownloadedFile mock."""
    from datetime import UTC, datetime

    f = MagicMock(spec=DownloadedFile)
    f.id = id
    f.show_id = show_id
    f.episode_id = None
    f.original_filename = "show.s01e01.mkv"
    f.remote_path = "/shows/show.s01e01.mkv"
    f.local_path = None
    f.file_size = 1_000_000
    f.hash_sha256 = None
    f.status = status
    f.matched_by = None
    f.error_message = None
    f.created_at = datetime.now(UTC)
    f.updated_at = datetime.now(UTC)
    return f


def _session_override(
    single: MagicMock | None = None,
    many: list[MagicMock] | None = None,
) -> "type[AsyncMock]":
    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = single
        result.scalars.return_value.all.return_value = many or ([single] if single else [])
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        yield session

    return _mock_session  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /api/files
# ---------------------------------------------------------------------------


def test_list_files_returns_200() -> None:
    """GET /api/files returns a list of files."""
    from jidou.database import get_session

    f = _make_file()
    app.dependency_overrides[get_session] = _session_override(many=[f])
    try:
        response = TestClient(app).get("/api/files")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    finally:
        app.dependency_overrides.clear()


def test_list_files_with_valid_status_filter() -> None:
    """GET /api/files?status=pending returns 200."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(many=[])
    try:
        response = TestClient(app).get("/api/files?status=pending")
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_list_files_with_invalid_status_returns_400() -> None:
    """GET /api/files?status=<bad> returns 400."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(many=[])
    try:
        response = TestClient(app).get("/api/files?status=nonexistent")
        assert response.status_code == 400
        assert "Invalid status" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/files/{file_id}
# ---------------------------------------------------------------------------


def test_get_file_returns_200() -> None:
    """GET /api/files/{id} returns the file record."""
    from jidou.database import get_session

    f = _make_file(id=1)
    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).get("/api/files/1")
        assert response.status_code == 200
        assert response.json()["id"] == 1
    finally:
        app.dependency_overrides.clear()


def test_get_file_returns_404_when_not_found() -> None:
    """GET /api/files/{id} returns 404 for an unknown ID."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).get("/api/files/9999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/files/{file_id}/match
# ---------------------------------------------------------------------------


def test_rematch_file_returns_404_when_file_missing() -> None:
    """POST /api/files/{id}/match returns 404 when the file doesn't exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).post("/api/files/9999/match", json={"method": "auto"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_rematch_file_returns_422_when_no_show_assigned() -> None:
    """POST /api/files/{id}/match returns 422 when the file has no show."""
    from jidou.database import get_session

    f = _make_file(id=1, show_id=None)
    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).post("/api/files/1/match", json={"method": "auto"})
        assert response.status_code == 422
        assert "no associated show" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_rematch_file_returns_503_when_broker_unavailable() -> None:
    """POST /api/files/{id}/match returns 503 when Celery broker is down."""
    import sys
    from unittest.mock import patch

    from jidou.database import get_session

    # show_id must be set so the 422 guard does not trigger
    f = _make_file(id=1, show_id=5)
    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        # Setting the module to None in sys.modules makes `from module import X`
        # raise ImportError, simulating a missing/broken Celery broker.
        with patch.dict(sys.modules, {"jidou.workers.match_tasks": None}):  # type: ignore[dict-item]
            response = TestClient(app).post("/api/files/1/match", json={"method": "auto"})
        assert response.status_code == 503
        # Bug 4 regression: file must be ERROR, not stuck as PENDING
        assert f.status == FileStatus.ERROR
    finally:
        app.dependency_overrides.clear()


def test_rematch_file_resets_status_to_pending() -> None:
    """POST /api/files/{id}/match resets the file status to PENDING before dispatch."""
    from unittest.mock import patch

    from jidou.database import get_session

    # show_id must be set so the 422 guard does not trigger
    f = _make_file(id=1, status=FileStatus.ERROR, show_id=5)

    async def _session_with_capture() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = f
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _session_with_capture
    try:
        mock_task = MagicMock()
        mock_task.apply_async = MagicMock()
        with patch.dict(
            "sys.modules",
            {"jidou.workers.match_tasks": MagicMock(match_files_task=mock_task)},
        ):
            TestClient(app).post("/api/files/1/match", json={"method": "heuristic"})
        assert f.status == FileStatus.PENDING
        # Bug: episode_id must be cleared so the worker assigns a fresh match
        assert f.episode_id is None
        # Verify dispatch used the correct show-level args (Bug 1 regression)
        mock_task.apply_async.assert_called_once_with(args=[5, False])
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PATCH /api/files/{file_id}
# ---------------------------------------------------------------------------


def test_patch_file_show_id() -> None:
    """PATCH /api/files/{id} with show_id updates the show assignment."""
    from jidou.database import get_session

    f = _make_file(id=1, show_id=None)
    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).patch("/api/files/1", json={"show_id": 42})
        assert response.status_code == 200
        assert f.show_id == 42
    finally:
        app.dependency_overrides.clear()


def test_patch_file_status() -> None:
    """PATCH /api/files/{id} with status updates the file status."""
    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.ERROR)
    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).patch("/api/files/1", json={"status": "downloaded"})
        assert response.status_code == 200
        assert f.status == FileStatus.DOWNLOADED
    finally:
        app.dependency_overrides.clear()


def test_patch_file_invalid_status_returns_422() -> None:
    """PATCH /api/files/{id} with a bad status string returns 422 (Pydantic pattern validation)."""
    from jidou.database import get_session

    f = _make_file(id=1)
    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).patch("/api/files/1", json={"status": "not_a_status"})
        # Pydantic's pattern constraint on FilePatch.status rejects bad values
        # before the route handler runs, returning 422 Unprocessable Entity.
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_patch_file_not_found_returns_404() -> None:
    """PATCH /api/files/{id} returns 404 for an unknown file ID."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).patch("/api/files/9999", json={"status": "pending"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_patch_file_partial_only_updates_provided_fields() -> None:
    """PATCH /api/files/{id} with only status leaves show_id unchanged."""
    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.ERROR, show_id=7)
    original_show_id = f.show_id
    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).patch("/api/files/1", json={"status": "pending"})
        assert response.status_code == 200
        assert f.show_id == original_show_id
        assert f.status == FileStatus.PENDING
    finally:
        app.dependency_overrides.clear()


def test_rematch_file_commits_before_dispatch() -> None:
    """Commit must happen before Celery dispatch so the worker reads updated state."""
    from unittest.mock import patch

    from jidou.database import get_session

    f = _make_file(id=1, show_id=7)
    call_order: list[str] = []

    async def _ordered_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = f
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock(side_effect=lambda: call_order.append("flush"))
        session.commit = AsyncMock(side_effect=lambda: call_order.append("commit"))
        yield session

    def _recording_apply_async(**_kwargs: object) -> None:
        call_order.append("dispatch")

    app.dependency_overrides[get_session] = _ordered_session
    try:
        mock_task = MagicMock()
        mock_task.apply_async = MagicMock(side_effect=_recording_apply_async)
        with patch.dict(
            "sys.modules",
            {"jidou.workers.match_tasks": MagicMock(match_files_task=mock_task)},
        ):
            TestClient(app).post("/api/files/1/match", json={"method": "auto"})
        assert call_order == ["flush", "commit", "dispatch"], "commit must precede Celery dispatch"
    finally:
        app.dependency_overrides.clear()
