"""Tests for db_import_tasks — database backup restore Celery task."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from jidou.models.task import TaskStatus
from jidou.workers.db_import_tasks import (
    _build_episode,
    _build_show,
    _emit_progress,
    _update_episode,
    _update_show,
)

# ---------------------------------------------------------------------------
# _build_show
# ---------------------------------------------------------------------------


class TestBuildShow:
    def test_minimal_fields(self) -> None:
        """Minimal row produces Show with sane defaults."""
        show = _build_show({"tmdb_id": 123, "title": "Test Show"})
        assert show.tmdb_id == 123
        assert show.title == "Test Show"
        assert show.media_type == "tv"
        assert show.vote_count == 0
        assert show.cached is False
        assert show.local_path is None

    def test_all_optional_fields_set(self) -> None:
        """All optional fields are mapped from the row."""
        row = {
            "tmdb_id": 456,
            "title": "Full Show",
            "overview": "Great show",
            "media_type": "anime",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "vote_average": 8.5,
            "vote_count": 1000,
            "release_date": "2023-01-15",
            "original_language": "ja",
            "cached": True,
            "content_type": "anime",
            "sys_name": "full_show",
            "local_path": "/media/anime/Full Show",
            "number_of_seasons": 3,
            "in_production": True,
        }
        show = _build_show(row)
        assert show.overview == "Great show"
        assert show.vote_average == 8.5
        assert show.vote_count == 1000
        assert show.local_path == "/media/anime/Full Show"
        assert show.cached is True
        assert show.number_of_seasons == 3
        assert show.in_production is True

    def test_missing_vote_count_defaults_to_zero(self) -> None:
        """vote_count defaults to 0 when absent."""
        show = _build_show({"tmdb_id": 1, "title": "S"})
        assert show.vote_count == 0

    def test_adult_flag_mapped_from_row(self) -> None:
        """adult is mapped from the backup row when present."""
        show = _build_show({"tmdb_id": 1, "title": "S", "adult": True})
        assert show.adult is True

    def test_adult_flag_defaults_to_none(self) -> None:
        """adult defaults to None when absent from the backup row."""
        show = _build_show({"tmdb_id": 1, "title": "S"})
        assert show.adult is None


# ---------------------------------------------------------------------------
# _update_show
# ---------------------------------------------------------------------------


class TestUpdateShow:
    def test_updates_title_and_overview(self) -> None:
        """Title and overview are updated from the backup row."""
        show = MagicMock()
        show.local_path = "/keep/this"
        _update_show(show, {"title": "New Title", "overview": "New overview"})
        assert show.title == "New Title"
        assert show.overview == "New overview"

    def test_preserves_local_path_when_backup_absent(self) -> None:
        """local_path is preserved when the backup row has no local_path key."""
        show = MagicMock()
        show.local_path = "/media/tv/Show"
        _update_show(show, {"title": "Show"})
        assert show.local_path == "/media/tv/Show"

    def test_overwrites_local_path_when_backup_present(self) -> None:
        """local_path is updated when the backup provides a non-None value."""
        show = MagicMock()
        show.local_path = "/old/path"
        _update_show(show, {"title": "S", "local_path": "/new/path"})
        assert show.local_path == "/new/path"

    def test_updates_production_metadata(self) -> None:
        """Production metadata fields are updated."""
        show = MagicMock()
        show.local_path = None
        _update_show(show, {"in_production": True, "number_of_seasons": 4, "runtime": 45})
        assert show.in_production is True
        assert show.number_of_seasons == 4
        assert show.runtime == 45

    def test_updates_adult_flag_from_backup(self) -> None:
        """adult is updated when the backup row provides it."""
        show = MagicMock()
        show.local_path = None
        show.adult = None
        _update_show(show, {"adult": True})
        assert show.adult is True

    def test_preserves_adult_flag_when_backup_absent(self) -> None:
        """adult is preserved when the backup row has no adult key."""
        show = MagicMock()
        show.local_path = None
        show.adult = True
        _update_show(show, {"title": "Show"})
        assert show.adult is True


# ---------------------------------------------------------------------------
# _build_episode
# ---------------------------------------------------------------------------


class TestBuildEpisode:
    def test_minimal_fields(self) -> None:
        """Minimal row produces Episode with defaults."""
        ep = _build_episode(
            {"tmdb_id": 100, "show_id": 10, "season_number": 1, "episode_number": 1}
        )
        assert ep.tmdb_id == 100
        assert ep.show_id == 10
        assert ep.season_number == 1
        assert ep.episode_number == 1
        assert ep.name == ""
        assert ep.air_date is None
        assert ep.file_tracked is False

    def test_valid_air_date_parsed(self) -> None:
        """ISO-format air_date is parsed to a date object."""
        ep = _build_episode(
            {
                "tmdb_id": 200,
                "show_id": 10,
                "season_number": 1,
                "episode_number": 2,
                "air_date": "2023-03-15",
            }
        )
        assert ep.air_date == date(2023, 3, 15)

    def test_invalid_air_date_silently_skipped(self) -> None:
        """Malformed air_date is suppressed; air_date stays None."""
        ep = _build_episode(
            {
                "tmdb_id": 300,
                "show_id": 10,
                "season_number": 1,
                "episode_number": 3,
                "air_date": "not-a-date",
            }
        )
        assert ep.air_date is None

    def test_optional_fields_populated(self) -> None:
        """Optional episode fields are set from the row."""
        ep = _build_episode(
            {
                "tmdb_id": 400,
                "show_id": 10,
                "season_number": 2,
                "episode_number": 4,
                "name": "The Battle",
                "overview": "Epic",
                "runtime": 48,
                "file_tracked": True,
                "absolute_episode_number": 16,
            }
        )
        assert ep.name == "The Battle"
        assert ep.overview == "Epic"
        assert ep.runtime == 48
        assert ep.file_tracked is True
        assert ep.absolute_episode_number == 16


# ---------------------------------------------------------------------------
# _update_episode
# ---------------------------------------------------------------------------


class TestUpdateEpisode:
    def test_updates_basic_fields(self) -> None:
        """name, season_number, episode_number are updated."""
        ep = MagicMock()
        ep.air_date = None
        _update_episode(ep, {"name": "New", "season_number": 3, "episode_number": 5})
        assert ep.name == "New"
        assert ep.season_number == 3
        assert ep.episode_number == 5

    def test_updates_air_date(self) -> None:
        """Valid air_date string is parsed and applied."""
        ep = MagicMock()
        ep.air_date = None
        _update_episode(ep, {"air_date": "2024-06-01"})
        assert ep.air_date == date(2024, 6, 1)

    def test_invalid_air_date_suppressed(self) -> None:
        """Invalid air_date string is suppressed; existing value retained."""
        ep = MagicMock()
        ep.air_date = date(2023, 1, 1)
        _update_episode(ep, {"air_date": "invalid"})
        assert ep.air_date == date(2023, 1, 1)

    def test_updates_tracking_field(self) -> None:
        """file_tracked field is updated."""
        ep = MagicMock()
        ep.air_date = None
        _update_episode(ep, {"file_tracked": True})
        assert ep.file_tracked is True


# ---------------------------------------------------------------------------
# _emit_progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_progress_calls_update_and_broadcast() -> None:
    """_emit_progress calls update_task_status and emit_progress once each."""
    mock_session = AsyncMock()

    with (
        patch(
            "jidou.workers.db_import_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock) as mock_emit,
    ):
        await _emit_progress(mock_session, "task-1", current=5, total=10, message="Processing")

    mock_update.assert_called_once()
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args[0][0]
    assert call_args["type"] == "progress"
    assert call_args["data"]["current"] == 5
    assert call_args["data"]["total"] == 10


# ---------------------------------------------------------------------------
# _db_import — mock helpers
# ---------------------------------------------------------------------------


def _make_db_mocks() -> tuple:
    """Return (mock_engine, mock_session, mock_factory) for worker tests."""
    mock_engine = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)
    return mock_engine, mock_session, mock_factory


def _pending_task() -> MagicMock:
    t = MagicMock()
    t.status = TaskStatus.PENDING.value
    return t


def _completed_task() -> MagicMock:
    t = MagicMock()
    t.status = TaskStatus.COMPLETED.value
    return t


# ---------------------------------------------------------------------------
# _db_import — redelivery skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_redelivery_skip() -> None:
    """Task already in terminal state must return immediately without processing."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"tmdb_id": 1, "title": "S"}]})
    terminal = MagicMock(status=TaskStatus.COMPLETED.value)
    mock_engine, _mock_session, mock_factory = _make_db_mocks()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=terminal,
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
    ):
        result = await _db_import("task-001", content)

    assert result == "task-001"
    mock_update.assert_not_called()
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# _db_import — empty backup success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_empty_backup_succeeds() -> None:
    """Empty backup file completes with zero-count summary."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [], "episodes": [], "watchlist": []})
    mock_engine, _mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock) as mock_emit,
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-002", content)

    assert result == "task-002"
    # "complete" event must have been emitted
    complete_calls = [c for c in mock_emit.call_args_list if c[0][0].get("type") == "complete"]
    assert len(complete_calls) == 1
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# _db_import — show missing tmdb_id is skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_show_missing_tmdb_id_skipped() -> None:
    """Show row without tmdb_id is logged and skipped."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"title": "No ID Show"}]})
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-003", content)

    assert result == "task-003"
    # session.execute should not have been called (skipped before DB lookup)
    mock_session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# _db_import — show missing title is skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_show_missing_title_skipped() -> None:
    """Show row without title is logged and skipped."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"tmdb_id": 42, "title": ""}]})
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-004", content)

    assert result == "task-004"
    mock_session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# _db_import — new show created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_new_show_created() -> None:
    """Show not in DB is created; show_id_map is populated."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"id": 1, "tmdb_id": 999, "title": "New Show"}]})
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    # show not found → None
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=not_found)

    added_objects: list = []

    def on_add(obj: object) -> None:
        added_objects.append(obj)
        if hasattr(obj, "tmdb_id"):
            obj.id = 100  # type: ignore[attr-defined]

    # session.add() is synchronous — must not be AsyncMock or side_effect never fires
    mock_session.add = MagicMock(side_effect=on_add)

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-005", content)

    assert result == "task-005"
    # show.add was called once for the new show
    assert len(added_objects) == 1
    assert added_objects[0].tmdb_id == 999


# ---------------------------------------------------------------------------
# _db_import — existing show updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_existing_show_updated() -> None:
    """Show already in DB is updated; show_id_map uses existing ID."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"id": 1, "tmdb_id": 888, "title": "Updated Title"}]})
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    # show already exists
    existing_show = MagicMock()
    existing_show.id = 50
    existing_show.local_path = "/media/tv/Show"
    found = MagicMock()
    found.scalar_one_or_none.return_value = existing_show
    mock_session.execute = AsyncMock(return_value=found)

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-006", content)

    assert result == "task-006"
    # existing show's title was updated
    assert existing_show.title == "Updated Title"
    # session.add was NOT called for an update
    mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# _db_import — cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_cancellation_handled_gracefully() -> None:
    """TaskCancelledError is caught and swallowed (no re-raise)."""
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"tmdb_id": 1, "title": "S"}]})
    mock_engine, mock_session, mock_factory = _make_db_mocks()

    # check_task_cancelled raises cancellation after the first show row
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=not_found)

    added: list = []

    def on_add(obj: object) -> None:
        added.append(obj)
        if hasattr(obj, "tmdb_id"):
            obj.id = 1  # type: ignore[attr-defined]

    mock_session.add = MagicMock(side_effect=on_add)

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch("jidou.workers.db_import_tasks.update_task_status", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch(
            "jidou.workers.db_import_tasks.check_task_cancelled",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
    ):
        # Should NOT raise — cancellation is caught
        result = await _db_import("task-007", content)

    assert result == "task-007"
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# _db_import — generic exception updates task status to FAILED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_exception_marks_failed_and_reraises() -> None:
    """Unexpected exception updates task to FAILED and re-raises."""
    import json as json_module

    from jidou.workers.db_import_tasks import _db_import

    content = "this is not valid json {{{"
    mock_engine, _mock_session, mock_factory = _make_db_mocks()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status", new_callable=AsyncMock
        ) as mock_update,
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock) as mock_emit,
        pytest.raises(json_module.JSONDecodeError),
    ):
        await _db_import("task-008", content)

    # FAILED status must have been requested
    failed_calls = [c for c in mock_update.call_args_list if c.args[2] == TaskStatus.FAILED]
    assert len(failed_calls) >= 1

    error_events = [c for c in mock_emit.call_args_list if c[0][0].get("type") == "error"]
    assert len(error_events) == 1

    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# _db_import — episode loop paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_episode_skipped_no_tmdb_id() -> None:
    """Episode row without tmdb_id is logged and skipped."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps(
        {"shows": [], "episodes": [{"season_number": 1, "episode_number": 1}], "watchlist": []}
    )
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-ep1", content)

    assert result == "task-ep1"
    # No DB lookup should have occurred for the episode
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_db_import_episode_skipped_show_not_in_map() -> None:
    """Episode with a show_id not in the restore map is skipped."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps(
        {
            "shows": [],
            "episodes": [{"tmdb_id": 500, "show_id": 99, "season_number": 1, "episode_number": 1}],
            "watchlist": [],
        }
    )
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-ep2", content)

    assert result == "task-ep2"
    # show_id=99 was never in show_id_map → episode execute not called
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_db_import_episode_created() -> None:
    """Episode not in DB is created when its show is in the restore map."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps(
        {
            "shows": [{"id": 10, "tmdb_id": 999, "title": "The Show"}],
            "episodes": [
                {
                    "tmdb_id": 500,
                    "show_id": 10,
                    "season_number": 1,
                    "episode_number": 1,
                    "title": "Pilot",
                }
            ],
            "watchlist": [],
        }
    )
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    show_not_found = MagicMock()
    show_not_found.scalar_one_or_none.return_value = None
    ep_not_found = MagicMock()
    ep_not_found.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(side_effect=[show_not_found, ep_not_found])

    added_objects: list = []

    def on_add(obj: object) -> None:
        added_objects.append(obj)
        obj.id = 100  # type: ignore[attr-defined]

    mock_session.add = MagicMock(side_effect=on_add)

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-ep3", content)

    assert result == "task-ep3"
    # Both the show and episode should have been added
    assert len(added_objects) == 2


@pytest.mark.asyncio
async def test_db_import_episode_updated() -> None:
    """Existing episode row is updated when show is in restore map."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps(
        {
            "shows": [{"id": 10, "tmdb_id": 999, "title": "The Show"}],
            "episodes": [
                {
                    "tmdb_id": 500,
                    "show_id": 10,
                    "season_number": 2,
                    "episode_number": 3,
                    "name": "Updated Pilot",
                }
            ],
            "watchlist": [],
        }
    )
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    existing_show = MagicMock()
    existing_show.id = 50
    existing_show.local_path = None
    show_found = MagicMock()
    show_found.scalar_one_or_none.return_value = existing_show

    existing_ep = MagicMock()
    existing_ep.air_date = None
    existing_ep.name = "Old Pilot"
    ep_found = MagicMock()
    ep_found.scalar_one_or_none.return_value = existing_ep
    mock_session.execute = AsyncMock(side_effect=[show_found, ep_found])

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-ep4", content)

    assert result == "task-ep4"
    # No new objects added — update path
    mock_session.add.assert_not_called()
    assert existing_ep.name == "Updated Pilot"
    assert existing_ep.season_number == 2


# ---------------------------------------------------------------------------
# _db_import — watchlist loop paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_watchlist_skipped_show_not_in_map() -> None:
    """Watchlist entry with show_id not in map is logged and skipped."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps(
        {"shows": [], "episodes": [], "watchlist": [{"show_id": 99, "status": "watching"}]}
    )
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-wl1", content)

    assert result == "task-wl1"
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_db_import_watchlist_entry_created() -> None:
    """New watchlist entry is created when show is in restore map."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps(
        {
            "shows": [{"id": 10, "tmdb_id": 999, "title": "The Show"}],
            "episodes": [],
            "watchlist": [{"show_id": 10, "status": "watching", "notes": "love it", "position": 3}],
        }
    )
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    show_not_found = MagicMock()
    show_not_found.scalar_one_or_none.return_value = None
    wl_not_found = MagicMock()
    wl_not_found.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(side_effect=[show_not_found, wl_not_found])

    added_objects: list = []

    def on_add(obj: object) -> None:
        added_objects.append(obj)
        obj.id = 200  # type: ignore[attr-defined]

    mock_session.add = MagicMock(side_effect=on_add)

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-wl2", content)

    assert result == "task-wl2"
    # show + watchlist entry both added
    assert len(added_objects) == 2


@pytest.mark.asyncio
async def test_db_import_watchlist_entry_updated() -> None:
    """Existing watchlist entry is updated when show is in restore map."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps(
        {
            "shows": [{"id": 10, "tmdb_id": 999, "title": "The Show"}],
            "episodes": [],
            "watchlist": [{"show_id": 10, "status": "completed", "notes": "done", "position": 7}],
        }
    )
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    existing_show = MagicMock()
    existing_show.id = 50
    existing_show.local_path = None
    show_found = MagicMock()
    show_found.scalar_one_or_none.return_value = existing_show

    existing_wl = MagicMock()
    existing_wl.status = "watching"
    existing_wl.notes = "old note"
    existing_wl.position = 1
    wl_found = MagicMock()
    wl_found.scalar_one_or_none.return_value = existing_wl
    mock_session.execute = AsyncMock(side_effect=[show_found, wl_found])

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-wl3", content)

    assert result == "task-wl3"
    mock_session.add.assert_not_called()
    assert existing_wl.notes == "done"
    assert existing_wl.position == 7


# ---------------------------------------------------------------------------
# db_import_task (sync Celery wrapper) — soft timeout
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _db_import — branches: backup_show_id is None (no "id" field in row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_show_created_without_backup_id() -> None:
    """When show row has no 'id', show_id_map is not populated (branch 141->143 False)."""
    from jidou.workers.db_import_tasks import _db_import

    # Row lacks "id" → backup_show_id is None
    content = json.dumps({"shows": [{"tmdb_id": 5001, "title": "No ID Show"}]})
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=not_found)

    added: list = []

    def on_add(obj: object) -> None:
        added.append(obj)
        if hasattr(obj, "tmdb_id"):
            obj.id = 200  # type: ignore[attr-defined]

    mock_session.add = MagicMock(side_effect=on_add)

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-show-noid", content)

    assert result == "task-show-noid"
    assert len(added) == 1


@pytest.mark.asyncio
async def test_db_import_show_updated_without_backup_id() -> None:
    """When existing show row has no 'id', show_id_map is not populated (branch 146->148 False)."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"tmdb_id": 5002, "title": "No ID Update"}]})
    mock_engine, mock_session, mock_factory = _make_db_mocks()
    completed = _completed_task()

    existing = MagicMock()
    existing.id = 77
    existing.local_path = "/media/tv/Show"
    found = MagicMock()
    found.scalar_one_or_none.return_value = existing
    mock_session.execute = AsyncMock(return_value=found)

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock),
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-show-upd-noid", content)

    assert result == "task-show-upd-noid"
    assert existing.title == "No ID Update"


# ---------------------------------------------------------------------------
# _db_import — branch 261->290: final_task is None (no complete emit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_skips_complete_emit_when_final_task_is_none() -> None:
    """No 'complete' emit_progress when update_task_status returns None."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [], "episodes": [], "watchlist": []})
    mock_engine, _mock_session, mock_factory = _make_db_mocks()

    with (
        patch("jidou.workers.db_import_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.db_import_tasks.async_sessionmaker", return_value=mock_factory),
        patch(
            "jidou.workers.db_import_tasks.create_task_record",
            new_callable=AsyncMock,
            return_value=_pending_task(),
        ),
        patch(
            "jidou.workers.db_import_tasks.update_task_status",
            new_callable=AsyncMock,
            return_value=None,  # triggers False branch at line 261
        ),
        patch("jidou.workers.db_import_tasks.emit_progress", new_callable=AsyncMock) as mock_emit,
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        result = await _db_import("task-no-emit", content)

    assert result == "task-no-emit"
    complete_calls = [c for c in mock_emit.call_args_list if c[0][0].get("type") == "complete"]
    assert len(complete_calls) == 0


def test_db_import_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded triggers mark_task_timed_out and re-raises."""
    from jidou.workers.db_import_tasks import db_import_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.db_import_tasks._db_import",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.db_import_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        db_import_task(file_content="{}")

    assert len(mark_calls) == 1
