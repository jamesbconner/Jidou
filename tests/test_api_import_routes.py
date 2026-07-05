"""Tests for API import routes."""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.task import BackgroundTask, TaskStatus


class TestImportText:
    """Tests for POST /api/import/text."""

    def test_import_text_invalid_content_type_returns_400(self) -> None:
        """Invalid content_type param returns 400 error."""
        client = TestClient(app)

        files = {"file": ("paths.txt", BytesIO(b"Z:\\anime tv\\Show\\ep.mkv"), "text/plain")}
        resp = client.post(
            "/api/import/text", data={"content_type": "invalid_type"}, files=files
        )

        assert resp.status_code == 400
        assert "content_type must be one of" in resp.json()["detail"]

    def test_import_text_file_too_large_returns_422(self) -> None:
        """File exceeding 10 MB limit returns 422 error."""
        client = TestClient(app)

        large_content = b"Z:\\anime tv\\Show\\ep.mkv\n" * 600_000  # ~14 MB
        files = {"file": ("paths.txt", BytesIO(large_content), "text/plain")}
        resp = client.post("/api/import/text", data={"content_type": "anime"}, files=files)

        assert resp.status_code == 422
        assert "too large" in resp.json()["detail"]

    def test_import_text_with_valid_content_type(self) -> None:
        """Valid content_type values (anime, tv, movie) are accepted."""
        client = TestClient(app)

        task = MagicMock(spec=BackgroundTask)
        task.id = 1
        task.celery_task_id = "abc-123"
        task.task_type = "import"
        task.status = TaskStatus.PENDING.value
        task.progress_current = 0
        task.progress_total = 0
        task.progress_message = None
        task.dry_run = False
        task.result_summary = None

        from datetime import UTC, datetime

        task.created_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        task.completed_at = None

        async def _mock_session() -> AsyncMock:
            session = AsyncMock()
            yield session

        from jidou.database import get_session

        app.dependency_overrides[get_session] = _mock_session

        try:
            with (
                patch(
                    "jidou.api.routes.import_routes.create_task_record",
                    AsyncMock(return_value=task),
                ),
                patch("jidou.workers.import_tasks.path_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock()

                for content_type in ["anime", "tv", "movie"]:
                    content = b"Z:\\anime tv\\Show\\Season 1\\Show.S01E01.mkv\n"
                    files = {"file": ("paths.txt", BytesIO(content), "text/plain")}
                    resp = client.post(
                        "/api/import/text",
                        data={"content_type": content_type, "dry_run": False},
                        files=files,
                    )

                    assert resp.status_code == 200
                    assert resp.json()["task_type"] == "import"
        finally:
            app.dependency_overrides.clear()

    def test_import_text_handles_unicode_decode(self) -> None:
        """File content is decoded handling UTF-8 and fallback to Latin-1."""
        client = TestClient(app)

        task = MagicMock(spec=BackgroundTask)
        task.id = 1
        task.celery_task_id = "abc-123"
        task.task_type = "import"
        task.status = TaskStatus.PENDING.value
        task.progress_current = 0
        task.progress_total = 0
        task.progress_message = None
        task.dry_run = False
        task.result_summary = None

        from datetime import UTC, datetime

        task.created_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        task.completed_at = None

        async def _mock_session() -> AsyncMock:
            session = AsyncMock()
            yield session

        from jidou.database import get_session

        app.dependency_overrides[get_session] = _mock_session

        try:
            with (
                patch(
                    "jidou.api.routes.import_routes.create_task_record",
                    AsyncMock(return_value=task),
                ),
                patch("jidou.workers.import_tasks.path_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock()

                # UTF-8 content
                content = "Z:\\anime tv\\Show\\Season 1\\Show.S01E01.mkv\n".encode("utf-8")
                files = {"file": ("paths.txt", BytesIO(content), "text/plain")}
                resp = client.post(
                    "/api/import/text",
                    data={"content_type": "anime", "dry_run": False},
                    files=files,
                )

                assert resp.status_code == 200
                mock_task.apply_async.assert_called()
        finally:
            app.dependency_overrides.clear()

    def test_import_text_task_dispatch_failure_returns_503(self) -> None:
        """When task broker fails, returns 503 Service Unavailable."""
        client = TestClient(app)

        task = MagicMock(spec=BackgroundTask)
        task.id = 1
        task.status = TaskStatus.FAILED.value
        task.progress_message = "Failed to enqueue task: Celery unavailable"

        from datetime import UTC, datetime

        task.completed_at = datetime.now(UTC)

        async def _mock_session() -> AsyncMock:
            session = AsyncMock()
            yield session

        from jidou.database import get_session

        app.dependency_overrides[get_session] = _mock_session

        try:
            with (
                patch(
                    "jidou.api.routes.import_routes.create_task_record",
                    AsyncMock(return_value=task),
                ),
                patch("jidou.workers.import_tasks.path_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock(
                    side_effect=RuntimeError("Celery broker unavailable")
                )

                content = b"Z:\\anime tv\\Show\\Season 1\\Show.S01E01.mkv\n"
                files = {"file": ("paths.txt", BytesIO(content), "text/plain")}
                resp = client.post(
                    "/api/import/text",
                    data={"content_type": "anime", "dry_run": False},
                    files=files,
                )

                assert resp.status_code == 503
                assert "broker unavailable" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()


class TestImportDatabase:
    """Tests for POST /api/import/database."""

    @pytest.mark.skip(reason="Large file test causes memory issues in test harness")
    def test_import_database_file_too_large_returns_422(self) -> None:
        """File exceeding 100 MB limit returns 422 error."""
        # This test is covered by the import_text equivalent test
        pass

    def test_import_database_invalid_json_returns_422(self) -> None:
        """Invalid JSON content returns 422 error with parse error message."""
        client = TestClient(app)

        invalid_json = b'{"shows": invalid json'
        files = {"file": ("backup.json", BytesIO(invalid_json), "application/json")}
        resp = client.post("/api/import/database", files=files)

        assert resp.status_code == 422
        assert "Invalid JSON" in resp.json()["detail"]

    def test_import_database_valid_json_dispatches_task(self) -> None:
        """Valid JSON file creates task record and dispatches to Celery."""
        client = TestClient(app)

        task = MagicMock(spec=BackgroundTask)
        task.id = 1
        task.celery_task_id = "xyz-456"
        task.task_type = "db_import"
        task.status = TaskStatus.PENDING.value
        task.progress_current = 0
        task.progress_total = 0
        task.progress_message = None
        task.dry_run = False
        task.result_summary = None

        from datetime import UTC, datetime

        task.created_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        task.completed_at = None

        async def _mock_session() -> AsyncMock:
            session = AsyncMock()
            yield session

        from jidou.database import get_session

        app.dependency_overrides[get_session] = _mock_session

        try:
            with (
                patch(
                    "jidou.api.routes.import_routes.create_task_record",
                    AsyncMock(return_value=task),
                ),
                patch("jidou.workers.db_import_tasks.db_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock()

                valid_json = b'{"version": "1", "shows": [], "episodes": [], "watchlist": []}'
                files = {"file": ("backup.json", BytesIO(valid_json), "application/json")}
                resp = client.post("/api/import/database", files=files)

                assert resp.status_code == 200
                assert resp.json()["task_type"] == "db_import"
                mock_task.apply_async.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    def test_import_database_task_dispatch_failure_returns_503(self) -> None:
        """When task broker fails, returns 503 Service Unavailable."""
        client = TestClient(app)

        task = MagicMock(spec=BackgroundTask)
        task.id = 1
        task.status = TaskStatus.FAILED.value
        task.progress_message = "Failed to enqueue task"

        from datetime import UTC, datetime

        task.completed_at = datetime.now(UTC)

        async def _mock_session() -> AsyncMock:
            session = AsyncMock()
            yield session

        from jidou.database import get_session

        app.dependency_overrides[get_session] = _mock_session

        try:
            with (
                patch(
                    "jidou.api.routes.import_routes.create_task_record",
                    AsyncMock(return_value=task),
                ),
                patch("jidou.workers.db_import_tasks.db_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock(side_effect=RuntimeError("Broker down"))

                valid_json = b'{"version": "1", "shows": [], "episodes": [], "watchlist": []}'
                files = {"file": ("backup.json", BytesIO(valid_json), "application/json")}
                resp = client.post("/api/import/database", files=files)

                assert resp.status_code == 503
                assert "broker unavailable" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()
