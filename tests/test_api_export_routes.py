"""Tests for API export routes."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.models.watchlist import WatchlistEntry


class TestExportDatabase:
    """Tests for GET /api/export/database."""

    def test_export_database_returns_streaming_response(self) -> None:
        """Export returns a StreamingResponse with proper headers."""
        client = TestClient(app)

        show = MagicMock(spec=Show)
        show.id = 1
        show.title = "Test Show"
        show.tmdb_id = 123

        ep = MagicMock(spec=Episode)
        ep.id = 1
        ep.show_id = 1
        ep.season_number = 1
        ep.episode_number = 1

        wl = MagicMock(spec=WatchlistEntry)
        wl.id = 1
        wl.show_id = 1
        wl.added_date = date(2024, 1, 1)

        async def mock_session():
            session = AsyncMock()
            # Mock for shows query
            shows_result = MagicMock()
            shows_result.scalars.return_value.all.return_value = [show]
            # Mock for episodes query
            eps_result = MagicMock()
            eps_result.scalars.return_value.all.return_value = [ep]
            # Mock for watchlist query
            wl_result = MagicMock()
            wl_result.scalars.return_value.all.return_value = [wl]
            # Set side effects for sequential execute calls
            session.execute = AsyncMock(side_effect=[shows_result, eps_result, wl_result])
            yield session

        from jidou.database import get_session

        app.dependency_overrides[get_session] = mock_session

        try:
            # Mock the inspect function to avoid introspection on mock objects
            with patch("jidou.api.routes.export_routes.inspect") as mock_inspect:
                mock_mapper = MagicMock()
                mock_mapper.column_attrs = []
                mock_inspect.return_value.mapper = mock_mapper

                resp = client.get("/api/export/database")

                assert resp.status_code == 200
                assert "application/json" in resp.headers.get("content-type", "")
                assert "attachment" in resp.headers.get("content-disposition", "")
                assert "jidou-backup-" in resp.headers.get("content-disposition", "")
        finally:
            app.dependency_overrides.clear()

    def test_export_database_serializes_dates_to_iso(self) -> None:
        """Date and datetime fields are serialized to ISO format strings."""
        from jidou.api.routes.export_routes import _row_to_dict

        created_date = date(2024, 1, 15)
        created_dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC)

        row = MagicMock()
        attr1 = MagicMock()
        attr1.key = "created"
        attr2 = MagicMock()
        attr2.key = "updated"

        mock_mapper = MagicMock()
        mock_mapper.column_attrs = [attr1, attr2]

        with patch("jidou.api.routes.export_routes.inspect") as mock_inspect:
            mock_inspect.return_value.mapper = mock_mapper
            row.created = created_date
            row.updated = created_dt

            result = _row_to_dict(row)

            assert result["created"] == "2024-01-15"
            assert result["updated"] == "2024-01-15T10:30:45+00:00"

    def test_export_database_includes_all_three_tables(self) -> None:
        """Export payload includes shows, episodes, and watchlist."""
        import json

        client = TestClient(app)

        show = MagicMock(spec=Show)
        ep = MagicMock(spec=Episode)
        wl = MagicMock(spec=WatchlistEntry)

        async def mock_session():
            session = AsyncMock()
            shows_result = MagicMock()
            shows_result.scalars.return_value.all.return_value = [show]
            eps_result = MagicMock()
            eps_result.scalars.return_value.all.return_value = [ep]
            wl_result = MagicMock()
            wl_result.scalars.return_value.all.return_value = [wl]
            session.execute = AsyncMock(side_effect=[shows_result, eps_result, wl_result])
            yield session

        from jidou.database import get_session

        app.dependency_overrides[get_session] = mock_session

        try:
            with patch("jidou.api.routes.export_routes.inspect") as mock_inspect:
                mock_mapper = MagicMock()
                mock_mapper.column_attrs = []
                mock_inspect.return_value.mapper = mock_mapper

                resp = client.get("/api/export/database")
                content = resp.text

                payload = json.loads(content)
                assert "version" in payload
                assert "exported_at" in payload
                assert "shows" in payload
                assert "episodes" in payload
                assert "watchlist" in payload
                assert isinstance(payload["shows"], list)
                assert isinstance(payload["episodes"], list)
                assert isinstance(payload["watchlist"], list)
        finally:
            app.dependency_overrides.clear()

    def test_row_to_dict_handles_non_date_fields(self) -> None:
        """_row_to_dict preserves non-date fields as-is."""
        from jidou.api.routes.export_routes import _row_to_dict

        row = MagicMock()
        attr1 = MagicMock()
        attr1.key = "id"
        attr2 = MagicMock()
        attr2.key = "title"

        mock_mapper = MagicMock()
        mock_mapper.column_attrs = [attr1, attr2]

        with patch("jidou.api.routes.export_routes.inspect") as mock_inspect:
            mock_inspect.return_value.mapper = mock_mapper
            row.id = 42
            row.title = "Test Show"

            result = _row_to_dict(row)

            assert result["id"] == 42
            assert result["title"] == "Test Show"
