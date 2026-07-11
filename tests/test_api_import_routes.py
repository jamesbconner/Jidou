"""Tests for API import routes."""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.api.routes.import_routes import _decode_upload
from jidou.main import app
from jidou.models.task import BackgroundTask, TaskStatus
from jidou.services.progress import TaskDispatchError


def _fake_enqueue(task: MagicMock) -> AsyncMock:
    """Return a fake enqueue_task that calls dispatch() then returns *task*.

    Mirrors enqueue_task's real "create row, call dispatch, return the row"
    shape closely enough that call_args assertions against the mocked Celery
    task still work naturally, and re-raises a dispatch() failure as
    TaskDispatchError to match the real function's contract.
    """

    async def _run(session, task_id, task_type, dispatch, *, dry_run=False):  # type: ignore[no-untyped-def]
        try:
            dispatch()
        except Exception as exc:
            raise TaskDispatchError(str(exc)) from exc
        return task

    return AsyncMock(side_effect=_run)


class TestDecodeUpload:
    """Tests for the shared _decode_upload helper."""

    def test_decodes_plain_utf8(self) -> None:
        """Plain UTF-8 content (no BOM) decodes as-is."""
        assert _decode_upload(b"Z:\\anime\\Show\\ep.mkv") == "Z:\\anime\\Show\\ep.mkv"

    def test_decodes_utf8_with_bom(self) -> None:
        """UTF-8 BOM is stripped."""
        raw = b"\xef\xbb\xbf" + b"Z:\\anime\\Show\\ep.mkv"
        assert _decode_upload(raw) == "Z:\\anime\\Show\\ep.mkv"

    def test_decodes_utf16_le_with_bom(self) -> None:
        """UTF-16LE with BOM (PowerShell's `>` redirection default) decodes correctly.

        This is the exact failure mode that previously produced a silent
        zero-entries import: utf-8-sig can't decode a UTF-16 BOM, so it fell
        through to latin-1, which never raises but turns every character
        into itself-plus-a-NUL-byte, breaking every downstream regex.
        """
        text = "Z:\\anime tv\\Show\\Season 01\\Show.S01E01.mkv"
        raw = text.encode("utf-16")  # Python prepends the LE BOM by default
        assert _decode_upload(raw) == text

    def test_decodes_utf16_be_with_bom(self) -> None:
        """UTF-16BE with BOM also decodes correctly."""
        text = "Z:\\anime tv\\Show\\Season 01\\Show.S01E01.mkv"
        raw = text.encode("utf-16-be")
        raw_with_bom = b"\xfe\xff" + raw
        assert _decode_upload(raw_with_bom) == text

    def test_falls_back_to_latin1_for_non_utf8_non_utf16(self) -> None:
        """Bytes that are neither valid UTF-8 nor UTF-16-BOM-prefixed fall back to Latin-1."""
        raw = b"Caf\xe9.mkv"  # 'é' in Latin-1, invalid as UTF-8 continuation
        assert _decode_upload(raw) == "Café.mkv"


class TestImportText:
    """Tests for POST /api/import/text."""

    def test_import_text_invalid_content_type_returns_400(self) -> None:
        """Invalid content_type param returns 400 error."""
        client = TestClient(app)

        files = {"file": ("paths.txt", BytesIO(b"Z:\\anime tv\\Show\\ep.mkv"), "text/plain")}
        resp = client.post("/api/import/text", data={"content_type": "invalid_type"}, files=files)

        assert resp.status_code == 400
        assert "content_type must be one of" in resp.json()["detail"]

    def test_import_text_file_too_large_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """File exceeding the size limit returns 422 error.

        Patches the module's byte limit down to a few bytes so the test can
        exercise the real `len(raw) > _MAX_FILE_BYTES` check without
        allocating a multi-megabyte buffer.
        """
        monkeypatch.setattr("jidou.api.routes.import_routes._MAX_FILE_BYTES", 10)
        client = TestClient(app)

        content = b"Z:\\anime tv\\Show\\ep.mkv\n"  # > 10 bytes
        files = {"file": ("paths.txt", BytesIO(content), "text/plain")}
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
                    "jidou.api.routes.import_routes.enqueue_task",
                    _fake_enqueue(task),
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
                    "jidou.api.routes.import_routes.enqueue_task",
                    _fake_enqueue(task),
                ),
                patch("jidou.workers.import_tasks.path_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock()

                # UTF-8 content
                content = b"Z:\\anime tv\\Show\\Season 1\\Show.S01E01.mkv\n"
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

    def test_import_text_decodes_utf16_file_before_dispatch(self) -> None:
        """A UTF-16LE-encoded upload (e.g. from PowerShell `>` redirection) is
        decoded to real text before being handed to the Celery task — not the
        NUL-interleaved garbage latin-1 fallback would previously produce.
        """
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
                    "jidou.api.routes.import_routes.enqueue_task",
                    _fake_enqueue(task),
                ),
                patch("jidou.workers.import_tasks.path_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock()

                text = "Z:\\anime tv\\Show\\Season 01\\Show.S01E01.mkv\n"
                content = text.encode("utf-16")  # LE with BOM, PowerShell's default
                files = {"file": ("paths.txt", BytesIO(content), "text/plain")}
                resp = client.post(
                    "/api/import/text",
                    data={"content_type": "anime", "dry_run": False},
                    files=files,
                )

                assert resp.status_code == 200
                dispatched_content = mock_task.apply_async.call_args.kwargs["args"][0]
                assert dispatched_content == text
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
                    "jidou.api.routes.import_routes.enqueue_task",
                    _fake_enqueue(task),
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

    def test_import_database_file_too_large_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """File exceeding the size limit returns 422 error.

        Patches the module's byte limit down to a few bytes so the test can
        exercise the real `len(raw) > _MAX_DB_BYTES` check without
        allocating a 100 MB buffer.
        """
        monkeypatch.setattr("jidou.api.routes.import_routes._MAX_DB_BYTES", 10)
        client = TestClient(app)

        content = b'{"shows": []}'  # > 10 bytes
        files = {"file": ("backup.json", BytesIO(content), "application/json")}
        resp = client.post("/api/import/database", files=files)

        assert resp.status_code == 422
        assert "too large" in resp.json()["detail"]

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
                    "jidou.api.routes.import_routes.enqueue_task",
                    _fake_enqueue(task),
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
                    "jidou.api.routes.import_routes.enqueue_task",
                    _fake_enqueue(task),
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
