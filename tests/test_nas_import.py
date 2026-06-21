"""Tests for NAS batch import — parser, orchestrator, and API route."""

from io import BytesIO
from pathlib import PureWindowsPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.main import app
from jidou.services.nas_parser import (
    group_by_show,
    parse_file,
    parse_line,
)

# ---------------------------------------------------------------------------
# nas_parser — parse_line
# ---------------------------------------------------------------------------


class TestParseLine:
    def test_skips_blank_line(self) -> None:
        assert parse_line("") is None
        assert parse_line("   ") is None

    def test_skips_comment(self) -> None:
        assert parse_line("# this is a comment") is None

    def test_skips_non_media_extension(self) -> None:
        assert parse_line(r"Z:\anime tv\Show\Season 1\readme.txt") is None

    def test_skips_short_path(self) -> None:
        # Only 3 parts — not enough to extract a show dir
        assert parse_line(r"Z:\anime tv\episode.mkv") is None

    def test_with_season_dir(self) -> None:
        line = r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E03.v2.1080p.BluRay.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Dorohedoro"
        assert entry.season == 1
        assert entry.episode == 3
        assert not entry.is_absolute
        assert entry.show_root == str(PureWindowsPath(r"Z:\anime tv\Dorohedoro"))

    def test_without_season_dir_dash_episode(self) -> None:
        line = r"Z:\anime tv\Hunter x Hunter\[HorribleSubs] Hunter x Hunter - 146 [1080p].mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Hunter x Hunter"
        assert entry.season is None
        assert entry.episode == 146
        assert entry.is_absolute

    def test_subsplease_style(self) -> None:
        line = (
            r"Z:\anime tv\As A Reincarnated Aristocrat\Season 2"
            r"\[SubsPlease] Tensei Kizoku - 06 (1080p) [F5E0AC82].mkv"
        )
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "As A Reincarnated Aristocrat"
        assert entry.season == 2
        assert entry.episode == 6

    def test_ep_word_style(self) -> None:
        line = r"Z:\anime tv\Yawara\Yawara - Ep 64.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Yawara"
        assert entry.episode == 64
        assert entry.is_absolute

    def test_trailing_dash_number(self) -> None:
        line = r"Z:\anime tv\Seirei no Moribito\Seirei no Moribito - 06.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.show_dir == "Seirei no Moribito"
        assert entry.episode == 6

    def test_case_insensitive_season_dir(self) -> None:
        line = r"Z:\anime tv\Show\season 2\Show.S02E01.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.season == 2
        assert entry.episode == 1

    def test_mp4_extension_accepted(self) -> None:
        line = r"Z:\tv\Breaking Bad\Season 1\episode.mp4"
        entry = parse_line(line)
        assert entry is not None

    def test_raw_path_preserved(self) -> None:
        line = r"Z:\anime tv\Show\ep01.mkv"
        entry = parse_line(line)
        assert entry is not None
        assert entry.raw_path == line


# ---------------------------------------------------------------------------
# nas_parser — parse_file and group_by_show
# ---------------------------------------------------------------------------


class TestParseFile:
    def test_parse_multiple_shows(self) -> None:
        content = "\n".join(
            [
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E01.mkv",
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E02.mkv",
                r"Z:\anime tv\Hunter x Hunter\[HorribleSubs] Hunter x Hunter - 01 [1080p].mkv",
                "# a comment line",
                "",
                r"Z:\anime tv\Hunter x Hunter\[HorribleSubs] Hunter x Hunter - 02 [1080p].mkv",
            ]
        )
        entries = parse_file(content)
        assert len(entries) == 4

    def test_group_by_show(self) -> None:
        content = "\n".join(
            [
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E01.mkv",
                r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E02.mkv",
                r"Z:\anime tv\Hunter x Hunter\ep01.mkv",
            ]
        )
        entries = parse_file(content)
        groups = group_by_show(entries)
        assert set(groups.keys()) == {"Dorohedoro", "Hunter x Hunter"}
        assert len(groups["Dorohedoro"]) == 2
        assert len(groups["Hunter x Hunter"]) == 1

    def test_windows_crlf_line_endings(self) -> None:
        content = (
            "Z:\\anime tv\\Show\\Season 1\\Show.S01E01.mkv\r\n"
            "Z:\\anime tv\\Show\\Season 1\\Show.S01E02.mkv\r\n"
        )
        entries = parse_file(content)
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# NASImportOrchestrator (unit — DB and TMDB fully mocked)
# ---------------------------------------------------------------------------


def _make_episode(*, id: int, show_id: int, season: int, episode: int) -> MagicMock:
    ep = MagicMock()
    ep.id = id
    ep.show_id = show_id
    ep.season_number = season
    ep.episode_number = episode
    ep.absolute_episode_number = None
    ep.file_tracked = False
    return ep


def _make_show(*, id: int = 1, tmdb_id: int = 999, title: str = "Dorohedoro") -> MagicMock:
    s = MagicMock()
    s.id = id
    s.tmdb_id = tmdb_id
    s.title = title
    s.aliases = []
    return s


@pytest.mark.asyncio
async def test_orchestrator_creates_show_and_tracks_episode() -> None:
    """Happy path: show not in DB → TMDB create → mark episode tracked."""
    from jidou.orchestrators.nas_import_orchestrator import NASImportOrchestrator
    from jidou.services.nas_parser import ParsedNASEntry

    entries = [
        ParsedNASEntry(
            raw_path=r"Z:\anime tv\Dorohedoro\Season 01\Dorohedoro.S01E01.mkv",
            show_dir="Dorohedoro",
            show_root=r"Z:\anime tv\Dorohedoro",
            season=1,
            episode=1,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=10, show_id=1, season=1, episode=1)

    session = AsyncMock()
    found_ep = MagicMock()
    found_ep.scalar_one_or_none.return_value = episode
    session.execute.return_value = found_ep
    session.commit = AsyncMock()

    tmdb = AsyncMock()

    orch = NASImportOrchestrator(session, tmdb, content_type="anime")

    # Patch the private methods so the test focuses on the coordination logic.
    with (
        patch.object(orch, "_db_find_show", AsyncMock(return_value=None)),
        patch.object(orch, "_tmdb_create_show", AsyncMock(return_value=(show, "created"))),
    ):
        result = await orch.run(entries)

    assert result.shows_processed == 1
    assert result.shows_created == 1
    assert result.shows_found == 0
    assert result.episodes_tracked == 1
    assert result.episodes_unmatched == 0
    assert episode.file_tracked is True


@pytest.mark.asyncio
async def test_orchestrator_finds_existing_show() -> None:
    """Show already in DB → skip TMDB → match episode."""
    from jidou.orchestrators.nas_import_orchestrator import NASImportOrchestrator
    from jidou.services.nas_parser import ParsedNASEntry

    entries = [
        ParsedNASEntry(
            raw_path=r"Z:\anime tv\Dorohedoro\Season 01\ep.mkv",
            show_dir="Dorohedoro",
            show_root=r"Z:\anime tv\Dorohedoro",
            season=1,
            episode=2,
            is_absolute=False,
        )
    ]

    show = _make_show()
    episode = _make_episode(id=20, show_id=1, season=1, episode=2)

    session = AsyncMock()
    show_result = MagicMock()
    show_result.scalars.return_value.first.return_value = show

    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode

    session.execute.side_effect = [show_result, ep_result]
    session.commit = AsyncMock()

    tmdb = AsyncMock()

    orch = NASImportOrchestrator(session, tmdb)
    result = await orch.run(entries)

    assert result.shows_found == 1
    assert result.shows_created == 0
    assert result.episodes_tracked == 1
    tmdb.search.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_handles_tmdb_miss() -> None:
    """TMDB returns no results → show_not_found, all episodes unmatched."""
    from jidou.orchestrators.nas_import_orchestrator import NASImportOrchestrator
    from jidou.services.nas_parser import ParsedNASEntry

    entries = [
        ParsedNASEntry(
            raw_path=r"Z:\anime tv\UnknownShow\ep01.mkv",
            show_dir="UnknownShow",
            show_root=r"Z:\anime tv\UnknownShow",
            season=None,
            episode=1,
            is_absolute=True,
        )
    ]

    session = AsyncMock()
    not_found = MagicMock()
    not_found.scalars.return_value.first.return_value = None
    session.execute.return_value = not_found

    tmdb = AsyncMock()
    tmdb.search.return_value = {"results": []}

    orch = NASImportOrchestrator(session, tmdb)
    result = await orch.run(entries)

    assert result.shows_not_found == 1
    assert result.episodes_unmatched == 1
    assert result.episodes_tracked == 0


@pytest.mark.asyncio
async def test_orchestrator_absolute_episode_fallback() -> None:
    """No season dir → absolute lookup by absolute_episode_number first, then s1/eN."""
    from jidou.orchestrators.nas_import_orchestrator import NASImportOrchestrator
    from jidou.services.nas_parser import ParsedNASEntry

    entries = [
        ParsedNASEntry(
            raw_path=r"Z:\anime tv\Hunter x Hunter\HxH - 146 [1080p].mkv",
            show_dir="Hunter x Hunter",
            show_root=r"Z:\anime tv\Hunter x Hunter",
            season=None,
            episode=146,
            is_absolute=True,
        )
    ]

    show = _make_show(id=2, tmdb_id=11, title="Hunter x Hunter")
    episode = _make_episode(id=30, show_id=2, season=1, episode=146)

    session = AsyncMock()
    show_result = MagicMock()
    show_result.scalars.return_value.first.return_value = show

    # absolute_episode_number lookup → None (not set), then s1/e146 → found
    abs_miss = MagicMock()
    abs_miss.scalar_one_or_none.return_value = None

    s1_hit = MagicMock()
    s1_hit.scalar_one_or_none.return_value = episode

    session.execute.side_effect = [show_result, abs_miss, s1_hit]
    session.commit = AsyncMock()

    tmdb = AsyncMock()

    orch = NASImportOrchestrator(session, tmdb)
    result = await orch.run(entries)

    assert result.episodes_tracked == 1
    assert episode.file_tracked is True


# ---------------------------------------------------------------------------
# POST /api/import/nas — API route
# ---------------------------------------------------------------------------


def _import_route_session_override(task: MagicMock) -> "type[AsyncMock]":
    """Session that returns the given task on flush then yields it."""

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        # create_task_record returns task
        # Patch the whole function instead of the session for simplicity.
        yield session

    return _mock_session  # type: ignore[return-value]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestImportNASRoute:
    def test_invalid_content_type_returns_400(self, client: TestClient) -> None:
        data = {"content_type": "invalid", "dry_run": False}
        files = {"file": ("paths.txt", BytesIO(b"Z:\\anime tv\\Show\\ep.mkv"), "text/plain")}
        resp = client.post("/api/import/nas", data=data, files=files)
        assert resp.status_code == 400
        assert "content_type" in resp.json()["detail"]

    def test_file_too_large_returns_422(self, client: TestClient) -> None:
        large_content = b"Z:\\anime tv\\Show\\ep.mkv\n" * 600_000  # ~14 MB
        files = {"file": ("paths.txt", BytesIO(large_content), "text/plain")}
        resp = client.post("/api/import/nas", data={"content_type": "anime"}, files=files)
        assert resp.status_code == 422
        assert "too large" in resp.json()["detail"]

    def test_valid_upload_dispatches_task(self, client: TestClient) -> None:
        from jidou.database import get_session
        from jidou.models.task import BackgroundTask, TaskStatus

        task = MagicMock(spec=BackgroundTask)
        task.id = 1
        task.celery_task_id = "abc-123"
        task.task_type = "import"
        task.status = TaskStatus.PENDING.value
        task.progress_current = 0
        task.progress_total = 0
        task.progress_message = None
        task.dry_run = False
        from datetime import UTC, datetime

        task.result_summary = None
        task.created_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        task.completed_at = None

        async def _mock_session() -> AsyncMock:
            session = AsyncMock()
            yield session

        app.dependency_overrides[get_session] = _mock_session
        try:
            with (
                patch(
                    "jidou.api.routes.import_routes.create_task_record",
                    AsyncMock(return_value=task),
                ),
                patch("jidou.workers.import_tasks.nas_import_task") as mock_task,
            ):
                mock_task.apply_async = MagicMock()
                content = b"Z:\\anime tv\\Show\\Season 1\\Show.S01E01.mkv\n"
                files = {"file": ("paths.txt", BytesIO(content), "text/plain")}
                resp = client.post(
                    "/api/import/nas",
                    data={"content_type": "anime", "dry_run": False},
                    files=files,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["task_type"] == "import"
