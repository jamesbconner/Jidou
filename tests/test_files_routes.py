"""Tests for the /files API routes."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.downloaded_file import DownloadedFile, FileStatus


def _make_file(
    *,
    id: int = 1,
    status: str = FileStatus.DISCOVERED,
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
    f.parsed_show_name = None
    f.parsed_season = None
    f.parsed_episode = None
    f.parsed_confidence = None
    f.parsed_content_type = None
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


def test_match_file_returns_404_when_file_missing() -> None:
    """POST /api/files/{id}/match returns 404 when the file doesn't exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).post("/api/files/9999/match", json={"show_id": 5})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_match_file_returns_404_when_show_missing() -> None:
    """POST /api/files/{id}/match returns 404 when the referenced show doesn't exist."""
    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.UNMATCHED)

    async def _two_query_session() -> AsyncMock:
        session = AsyncMock()
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = f
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[file_result, show_result])
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _two_query_session
    try:
        response = TestClient(app).post("/api/files/1/match", json={"show_id": 9999})
        assert response.status_code == 404
        assert "Show not found" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_match_file_returns_422_when_show_has_no_local_path() -> None:
    """POST /api/files/{id}/match returns 422 when show.local_path is None."""
    from jidou.database import get_session
    from jidou.models.show import Show

    f = _make_file(id=1, status=FileStatus.UNMATCHED)
    show = MagicMock(spec=Show)
    show.id = 5
    show.title = "Test Show"
    show.local_path = None

    async def _two_query_session() -> AsyncMock:
        session = AsyncMock()
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = f
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        session.execute = AsyncMock(side_effect=[file_result, show_result])
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _two_query_session
    try:
        response = TestClient(app).post("/api/files/1/match", json={"show_id": 5})
        assert response.status_code == 422
        assert "local_path" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_match_file_sets_matched_status() -> None:
    """POST /api/files/{id}/match transitions file status to MATCHED."""
    from jidou.database import get_session
    from jidou.models.downloaded_file import MatchedBy
    from jidou.models.show import Show

    f = _make_file(id=1, status=FileStatus.UNMATCHED)
    f.parsed_season = None  # triggers heuristic extraction + episode lookup
    f.parsed_episode = None
    show = MagicMock(spec=Show)
    show.id = 5
    show.title = "Test Show"
    show.local_path = "/media/test"

    async def _three_query_session() -> AsyncMock:
        session = AsyncMock()
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = f
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = None  # no episode in DB
        session.execute = AsyncMock(side_effect=[file_result, show_result, ep_result])
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _three_query_session
    try:
        response = TestClient(app).post("/api/files/1/match", json={"show_id": 5})
        assert response.status_code == 200
        assert f.status == FileStatus.MATCHED
        assert f.show_id == show.id
        assert f.matched_by == MatchedBy.MANUAL
        assert f.parsed_season == 1  # extracted from "show.s01e01.mkv"
        assert f.parsed_episode == 1
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


def test_patch_file_show_id_change_clears_stale_episode() -> None:
    """PATCH show_id to a different value clears episode_id and matched_by."""
    from jidou.database import get_session

    f = _make_file(id=1, show_id=5)
    f.episode_id = 99
    f.matched_by = "llm"

    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).patch("/api/files/1", json={"show_id": 10})
        assert response.status_code == 200
        assert f.show_id == 10
        assert f.episode_id is None
        assert f.matched_by is None
    finally:
        app.dependency_overrides.clear()


def test_patch_file_show_id_same_value_preserves_episode() -> None:
    """PATCH show_id with the same value does not clear episode_id."""
    from jidou.database import get_session

    f = _make_file(id=1, show_id=5)
    f.episode_id = 99
    f.matched_by = "heuristic"

    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).patch("/api/files/1", json={"show_id": 5})
        assert response.status_code == 200
        assert f.episode_id == 99
        assert f.matched_by == "heuristic"
    finally:
        app.dependency_overrides.clear()


def test_patch_file_explicit_episode_wins_over_show_clear() -> None:
    """PATCH show_id with explicit episode_id keeps the caller-provided episode."""
    from jidou.database import get_session

    f = _make_file(id=1, show_id=5)
    f.episode_id = 99
    f.matched_by = "llm"

    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).patch("/api/files/1", json={"show_id": 10, "episode_id": 42})
        assert response.status_code == 200
        assert f.show_id == 10
        assert f.episode_id == 42
        assert f.matched_by is None  # always cleared; not in FilePatch schema
    finally:
        app.dependency_overrides.clear()


def test_patch_file_show_id_conflict_returns_409() -> None:
    """PATCH /api/files/{id} returns 409 when the new show_id violates the unique constraint."""
    from sqlalchemy.exc import IntegrityError

    from jidou.database import get_session

    f = _make_file(id=1, show_id=None)

    orig = Exception("unique constraint violated")
    orig.pgcode = "23505"  # type: ignore[attr-defined]

    async def _conflict_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = f
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock(side_effect=IntegrityError("stmt", {}, orig))
        session.rollback = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _conflict_session
    try:
        response = TestClient(app).patch("/api/files/1", json={"show_id": 42})
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_patch_file_fk_violation_returns_422() -> None:
    """PATCH /api/files/{id} returns 422 when episode_id references a non-existent row."""
    from sqlalchemy.exc import IntegrityError

    from jidou.database import get_session

    f = _make_file(id=1, show_id=5)

    orig = Exception("foreign key constraint violated")
    orig.pgcode = "23503"  # type: ignore[attr-defined]

    async def _fk_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = f
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock(side_effect=IntegrityError("stmt", {}, orig))
        session.rollback = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _fk_session
    try:
        response = TestClient(app).patch("/api/files/1", json={"episode_id": 9999})
        assert response.status_code == 422
        assert "does not exist" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_match_file_flushes_then_commits() -> None:
    """Match endpoint must flush before commit so the DB state is visible."""
    from jidou.database import get_session
    from jidou.models.show import Show

    f = _make_file(id=1, status=FileStatus.UNMATCHED)
    f.parsed_season = None  # triggers heuristic extraction + episode lookup
    f.parsed_episode = None
    show = MagicMock(spec=Show)
    show.id = 7
    show.title = "Test Show"
    show.local_path = "/media/test"

    call_order: list[str] = []

    async def _ordered_session() -> AsyncMock:
        session = AsyncMock()
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = f
        show_result = MagicMock()
        show_result.scalar_one_or_none.return_value = show
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[file_result, show_result, ep_result])
        session.flush = AsyncMock(side_effect=lambda: call_order.append("flush"))
        session.commit = AsyncMock(side_effect=lambda: call_order.append("commit"))
        yield session

    app.dependency_overrides[get_session] = _ordered_session
    try:
        TestClient(app).post("/api/files/1/match", json={"show_id": 7})
        assert call_order == ["flush", "commit"], "flush must precede commit"
    finally:
        app.dependency_overrides.clear()


def test_match_file_no_show_id_resets_to_downloaded() -> None:
    """POST /api/files/{id}/match without show_id resets file to DOWNLOADED."""
    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.UNMATCHED)

    async def _single_query_session() -> AsyncMock:
        session = AsyncMock()
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = f
        session.execute = AsyncMock(return_value=file_result)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _single_query_session
    try:
        response = TestClient(app).post("/api/files/1/match", json={})
        assert response.status_code == 200
        assert f.status == FileStatus.DOWNLOADED
        assert f.show_id is None
        assert f.matched_by is None
    finally:
        app.dependency_overrides.clear()


def test_match_file_routed_returns_409() -> None:
    """POST /api/files/{id}/match on a ROUTED file must return 409."""
    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.ROUTED)

    async def _single_query_session() -> AsyncMock:
        session = AsyncMock()
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = f
        session.execute = AsyncMock(return_value=file_result)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _single_query_session
    try:
        response = TestClient(app).post("/api/files/1/match", json={"show_id": 5})
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_match_file_both_show_id_and_tmdb_id_returns_422() -> None:
    """POST /api/files/{id}/match with both show_id and tmdb_id returns 422."""
    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.UNMATCHED)
    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).post("/api/files/1/match", json={"show_id": 1, "tmdb_id": 99})
        assert response.status_code == 422
        assert "both" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_match_file_tmdb_id_creates_show_and_matches() -> None:
    """POST /api/files/{id}/match with tmdb_id creates a show and marks file MATCHED."""
    from unittest.mock import patch

    from jidou.database import get_session
    from jidou.models.downloaded_file import MatchedBy
    from jidou.models.show import Show

    f = _make_file(id=1, status=FileStatus.UNMATCHED)
    f.parsed_season = None
    f.parsed_episode = None

    tmdb_data = {
        "id": 1396,
        "name": "Breaking Bad",
        "overview": "A chemistry teacher turns to crime.",
        "poster_path": "/poster.jpg",
        "backdrop_path": None,
        "vote_average": 9.5,
        "vote_count": 12000,
        "first_air_date": "2008-01-20",
        "original_language": "en",
    }

    created_show = MagicMock(spec=Show)
    created_show.id = 42
    created_show.title = "Breaking Bad"
    created_show.local_path = "/media/tv/Breaking Bad"

    async def _tmdb_match_session() -> AsyncMock:
        session = AsyncMock()
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = f
        # show lookup by tmdb_id → not found (triggers creation)
        no_show_result = MagicMock()
        no_show_result.scalar_one_or_none.return_value = None
        # episode lookup → not found
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[file_result, no_show_result, ep_result])
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        # Capture the Show added to the session and make it usable
        def _add(obj: object) -> None:
            if isinstance(obj, Show):
                obj.id = created_show.id  # type: ignore[attr-defined]
                obj.local_path = "/media/tv/Breaking Bad"  # type: ignore[attr-defined]

        session.add = MagicMock(side_effect=_add)
        yield session

    app.dependency_overrides[get_session] = _tmdb_match_session
    try:
        with patch(
            "jidou.api.routes.files.TMDBService",
            autospec=True,
        ) as mock_tmdb:
            mock_tmdb.return_value.get_details = AsyncMock(return_value=tmdb_data)
            response = TestClient(app).post(
                "/api/files/1/match",
                json={
                    "tmdb_id": 1396,
                    "local_path": "/media/tv/Breaking Bad",
                    "content_type": "tv",
                },
            )
        assert response.status_code == 200
        assert f.status == FileStatus.MATCHED
        assert f.matched_by == MatchedBy.MANUAL
        assert f.parsed_season == 1
        assert f.parsed_episode == 1
    finally:
        app.dependency_overrides.clear()


def test_match_file_tmdb_id_without_local_path_returns_422() -> None:
    """POST /api/files/{id}/match with tmdb_id but no local_path returns 422."""
    from unittest.mock import patch

    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.UNMATCHED)

    async def _tmdb_missing_path_session() -> AsyncMock:
        session = AsyncMock()
        file_result = MagicMock()
        file_result.scalar_one_or_none.return_value = f
        no_show_result = MagicMock()
        no_show_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[file_result, no_show_result])
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _tmdb_missing_path_session
    try:
        with patch("jidou.api.routes.files.TMDBService"):
            response = TestClient(app).post(
                "/api/files/1/match",
                json={"tmdb_id": 1396},
            )
        assert response.status_code == 422
        assert "local_path" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/files/{file_id}/tmdb-suggestions
# ---------------------------------------------------------------------------


def test_tmdb_suggestions_returns_results() -> None:
    """GET /api/files/{id}/tmdb-suggestions returns TMDB search results."""
    from unittest.mock import patch

    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.UNMATCHED)
    f.parsed_show_name = "Breaking Bad"

    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        with patch(
            "jidou.api.routes.files.TMDBService",
            autospec=True,
        ) as mock_tmdb:
            mock_tmdb.return_value.search = AsyncMock(
                return_value={
                    "results": [
                        {
                            "id": 1396,
                            "name": "Breaking Bad",
                            "media_type": "tv",
                            "overview": "A chemistry teacher turns to crime.",
                            "poster_path": "/poster.jpg",
                            "first_air_date": "2008-01-20",
                            "vote_average": 9.5,
                        },
                        {
                            "id": 999,
                            "title": "Breaking Film",
                            "media_type": "movie",
                            "overview": "Some movie.",
                            "poster_path": None,
                            "release_date": "2020-01-01",
                            "vote_average": 6.0,
                        },
                    ]
                }
            )
            response = TestClient(app).get("/api/files/1/tmdb-suggestions")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "Breaking Bad"
        assert len(data["results"]) == 2
        assert data["results"][0]["tmdb_id"] == 1396
        assert data["results"][0]["title"] == "Breaking Bad"
    finally:
        app.dependency_overrides.clear()


def test_tmdb_suggestions_no_parsed_name_returns_422() -> None:
    """GET /api/files/{id}/tmdb-suggestions with no parsed_show_name returns 422."""
    from jidou.database import get_session

    f = _make_file(id=1, status=FileStatus.UNMATCHED)
    f.parsed_show_name = None

    app.dependency_overrides[get_session] = _session_override(single=f)
    try:
        response = TestClient(app).get("/api/files/1/tmdb-suggestions")
        assert response.status_code == 422
        assert "parsed_show_name" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_tmdb_suggestions_file_not_found_returns_404() -> None:
    """GET /api/files/{id}/tmdb-suggestions returns 404 for unknown file."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).get("/api/files/9999/tmdb-suggestions")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
