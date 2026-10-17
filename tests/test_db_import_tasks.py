"""Tests for db_import_tasks — database backup restore Celery task."""

import json
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import inspect

from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.workers.db_import_tasks import (
    _build_episode,
    _build_show,
    _update_episode,
    _update_show,
    check_restore_field_coverage,
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

    def test_aliases_sources_mapped_from_row(self) -> None:
        """aliases_sources is mapped from the backup row when present."""
        show = _build_show({"tmdb_id": 1, "title": "S", "aliases_sources": {"tmdb": ["Alt Title"]}})
        assert show.aliases_sources == {"tmdb": ["Alt Title"]}

    def test_aliases_sources_defaults_to_none(self) -> None:
        """aliases_sources defaults to None when absent from the backup row."""
        show = _build_show({"tmdb_id": 1, "title": "S"})
        assert show.aliases_sources is None


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

    def test_updates_aliases_sources_from_backup(self) -> None:
        """aliases_sources is updated when the backup row provides it."""
        show = MagicMock()
        show.local_path = None
        show.aliases_sources = None
        _update_show(show, {"aliases_sources": {"user": ["Nickname"]}})
        assert show.aliases_sources == {"user": ["Nickname"]}

    def test_preserves_aliases_sources_when_backup_absent(self) -> None:
        """aliases_sources is preserved when the backup row has no aliases_sources key."""
        show = MagicMock()
        show.local_path = None
        show.aliases_sources = {"tmdb": ["Original"]}
        _update_show(show, {"title": "Show"})
        assert show.aliases_sources == {"tmdb": ["Original"]}


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

    def test_tracking_fields_populated(self) -> None:
        """tracked_filename, tracked_source, and file_tracked_at are set from the row."""
        ep = _build_episode(
            {
                "tmdb_id": 500,
                "show_id": 10,
                "season_number": 1,
                "episode_number": 1,
                "tracked_filename": "Show.S01E01.mkv",
                "tracked_source": "sftp",
                "file_tracked_at": "2024-06-01T12:30:00+00:00",
            }
        )
        assert ep.tracked_filename == "Show.S01E01.mkv"
        assert ep.tracked_source == "sftp"
        assert ep.file_tracked_at == datetime.fromisoformat("2024-06-01T12:30:00+00:00")

    def test_tracking_fields_default_to_none(self) -> None:
        """tracked_filename, tracked_source, and file_tracked_at default to None when absent."""
        ep = _build_episode(
            {"tmdb_id": 500, "show_id": 10, "season_number": 1, "episode_number": 1}
        )
        assert ep.tracked_filename is None
        assert ep.tracked_source is None
        assert ep.file_tracked_at is None

    def test_invalid_file_tracked_at_silently_skipped(self) -> None:
        """Malformed file_tracked_at is suppressed; the field stays None."""
        ep = _build_episode(
            {
                "tmdb_id": 500,
                "show_id": 10,
                "season_number": 1,
                "episode_number": 1,
                "file_tracked_at": "not-a-datetime",
            }
        )
        assert ep.file_tracked_at is None


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

    def test_updates_tracking_metadata_fields(self) -> None:
        """tracked_filename, tracked_source, and file_tracked_at are updated from the row."""
        ep = MagicMock()
        ep.air_date = None
        _update_episode(
            ep,
            {
                "tracked_filename": "Show.S02E03.mkv",
                "tracked_source": "path_import",
                "file_tracked_at": "2024-07-04T08:00:00+00:00",
            },
        )
        assert ep.tracked_filename == "Show.S02E03.mkv"
        assert ep.tracked_source == "path_import"
        assert ep.file_tracked_at == datetime.fromisoformat("2024-07-04T08:00:00+00:00")

    def test_preserves_tracking_metadata_when_backup_absent(self) -> None:
        """tracked_filename/tracked_source/file_tracked_at survive an absent-from-row update."""
        ep = MagicMock()
        ep.air_date = None
        ep.tracked_filename = "Existing.mkv"
        ep.tracked_source = "sftp"
        ep.file_tracked_at = datetime(2023, 1, 1)
        _update_episode(ep, {"name": "New"})
        assert ep.tracked_filename == "Existing.mkv"
        assert ep.tracked_source == "sftp"
        assert ep.file_tracked_at == datetime(2023, 1, 1)

    def test_invalid_file_tracked_at_does_not_clear_existing_timestamp(self) -> None:
        """A malformed (non-null) file_tracked_at must not wipe a valid existing value.

        Regression test for a Cursor Bugbot finding on PR-02: the key being
        present with an unparseable value previously overwrote a good
        timestamp with None instead of leaving it untouched.
        """
        ep = MagicMock()
        ep.air_date = None
        ep.file_tracked_at = datetime(2023, 1, 1)
        _update_episode(ep, {"file_tracked_at": "not-a-datetime"})
        assert ep.file_tracked_at == datetime(2023, 1, 1)

    def test_explicit_null_file_tracked_at_clears_existing_timestamp(self) -> None:
        """An explicit null file_tracked_at legitimately clears tracking state."""
        ep = MagicMock()
        ep.air_date = None
        ep.file_tracked_at = datetime(2023, 1, 1)
        _update_episode(ep, {"file_tracked_at": None})
        assert ep.file_tracked_at is None


# ---------------------------------------------------------------------------
# Field coverage — restore must handle every Show/Episode column
# ---------------------------------------------------------------------------


def test_restore_field_coverage_has_no_gaps() -> None:
    """Every Show/Episode column is either restored or explicitly excluded.

    Regression test: aliases_sources (Show) and tracked_filename /
    tracked_source / file_tracked_at (Episode) were added to the models but
    never wired into _build_show/_update_show/_build_episode/_update_episode,
    so a backup restore silently dropped them. A future column added to
    either model without a matching restore-side change now fails here
    instead of shipping silently.
    """
    assert check_restore_field_coverage() == {"Show": set(), "Episode": set()}


# ---------------------------------------------------------------------------
# Export/restore round trip
# ---------------------------------------------------------------------------


class TestRestoreRoundTrip:
    def test_show_round_trip_preserves_all_fields(self) -> None:
        """A fully-populated Show survives an export/restore round trip."""
        from jidou.api.routes.export_routes import _row_to_dict

        show = Show(
            tmdb_id=42,
            title="Round Trip Show",
            overview="An overview",
            media_type="tv",
            poster_path="/poster.jpg",
            backdrop_path="/backdrop.jpg",
            vote_average=7.5,
            vote_count=100,
            release_date="2020-01-01",
            original_language="en",
            cached=True,
            content_type="tv",
            sys_name="Round Trip Show",
            aliases=["Alt Name"],
            aliases_sources={"tmdb": ["Alt Name"]},
            genres=[{"id": 1, "name": "Drama"}],
            adult=False,
            origin_country=["US"],
            last_air_date="2023-01-01",
            last_episode_to_air={"id": 1},
            next_episode_to_air=None,
            homepage="https://example.com",
            external_ids={"imdb_id": "tt123"},
            episode_groups=[{"id": "g1"}],
            status="Ended",
            in_production=False,
            number_of_seasons=2,
            number_of_episodes=20,
            networks=[{"id": 5, "name": "HBO"}],
            show_type="Scripted",
            runtime=45,
            tagline="A tagline",
            local_path="/media/tv/Round Trip Show",
        )
        row = _row_to_dict(show)
        restored = _build_show(row)

        for attr in inspect(Show).column_attrs:
            key = attr.key
            if key in {"id", "created_at", "updated_at"}:
                continue
            assert getattr(restored, key) == getattr(show, key), f"{key} was not preserved"

    def test_episode_round_trip_preserves_all_fields(self) -> None:
        """A fully-populated Episode survives an export/restore round trip."""
        from jidou.api.routes.export_routes import _row_to_dict

        ep = Episode(
            show_id=10,
            tmdb_id=500,
            season_number=1,
            episode_number=1,
            name="Pilot",
            overview="The first episode",
            air_date=date(2020, 1, 1),
            runtime=24,
            absolute_episode_number=1,
            episode_type="standard",
            still_path="/still.jpg",
            file_tracked=True,
            file_tracked_at=datetime(2024, 6, 1, 12, 30, 0),
            tracked_filename="Show.S01E01.mkv",
            tracked_source="sftp",
        )
        row = _row_to_dict(ep)
        restored = _build_episode(row)

        for attr in inspect(Episode).column_attrs:
            key = attr.key
            if key in {"id", "created_at", "updated_at"}:
                continue
            assert getattr(restored, key) == getattr(ep, key), f"{key} was not preserved"


# ---------------------------------------------------------------------------
# _db_import — shared helpers
#
# Lifecycle machinery (redelivery skip, RUNNING/COMPLETED/CANCELLED/FAILED
# transitions, on_progress/on_event plumbing, engine/session lifecycle) is
# covered once, generically, in tests/test_worker_harness.py. These tests
# patch run_task_workflow to capture _db_import's `work` closure, then call
# it directly with a plain session mock -- covering what's actually
# db_import-specific: the show/episode/watchlist upsert loops. `_work` still
# calls update_task_status (the "found N shows" RUNNING update) and
# check_task_cancelled (per-row) directly, so those two stay patched at
# jidou.workers.db_import_tasks -- everything else moved into the harness.
# ---------------------------------------------------------------------------


def _capture_run_task_workflow(module_path: str) -> tuple:
    """Patch <module_path>.run_task_workflow, capturing its call kwargs and `work` callback."""
    captured: dict[str, object] = {}

    async def fake_run_task_workflow(
        celery_task_id: str,
        task_type: str,
        work: object,
        *,
        progress_total: int = 0,
        dry_run: bool = False,
        running_message: str = "",
    ) -> str:
        captured["celery_task_id"] = celery_task_id
        captured["task_type"] = task_type
        captured["work"] = work
        captured["progress_total"] = progress_total
        captured["dry_run"] = dry_run
        captured["running_message"] = running_message
        return celery_task_id

    return patch(f"{module_path}.run_task_workflow", side_effect=fake_run_task_workflow), captured


async def _invoke_work(captured: dict[str, object], session: AsyncMock) -> object:
    """Call the captured `_work` closure with a no-op check_task_cancelled/update_task_status."""
    with (
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        return await captured["work"](session, AsyncMock(), AsyncMock(), AsyncMock())  # type: ignore[operator]


# ---------------------------------------------------------------------------
# _db_import — wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_wires_run_task_workflow() -> None:
    """_db_import wires run_task_workflow with the right task_type/progress_total/dry_run."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [], "episodes": [], "watchlist": []})
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        result = await _db_import("task-001", content)

    assert result == "task-001"
    assert captured["task_type"] == "db_import"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is False
    assert captured["running_message"] == "Parsing backup file…"


# ---------------------------------------------------------------------------
# _db_import — empty backup success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_empty_backup_succeeds() -> None:
    """Empty backup file completes with zero-count summary."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [], "episodes": [], "watchlist": []})
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-002", content)

    wf_result = await _invoke_work(captured, AsyncMock())

    assert wf_result.progress_current == 0  # type: ignore[attr-defined]
    assert wf_result.progress_total == 0  # type: ignore[attr-defined]
    assert wf_result.result_summary == {  # type: ignore[attr-defined]
        "shows_created": 0,
        "shows_updated": 0,
        "episodes_created": 0,
        "episodes_updated": 0,
        "watchlist_created": 0,
        "watchlist_updated": 0,
    }


# ---------------------------------------------------------------------------
# _db_import — show missing tmdb_id is skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_show_missing_tmdb_id_skipped() -> None:
    """Show row without tmdb_id is logged and skipped."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"title": "No ID Show"}]})
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-003", content)

    session = AsyncMock()
    await _invoke_work(captured, session)

    # session.execute should not have been called (skipped before DB lookup)
    session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# _db_import — show missing title is skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_show_missing_title_skipped() -> None:
    """Show row without title is logged and skipped."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"tmdb_id": 42, "title": ""}]})
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-004", content)

    session = AsyncMock()
    await _invoke_work(captured, session)

    session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# _db_import — new show created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_new_show_created() -> None:
    """Show not in DB is created; show_id_map is populated."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"id": 1, "tmdb_id": 999, "title": "New Show"}]})
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-005", content)

    session = AsyncMock()
    # show not found → None
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=not_found)

    added_objects: list = []

    def on_add(obj: object) -> None:
        added_objects.append(obj)
        if hasattr(obj, "tmdb_id"):
            obj.id = 100  # type: ignore[attr-defined]

    # session.add() is synchronous — must not be AsyncMock or side_effect never fires
    session.add = MagicMock(side_effect=on_add)

    await _invoke_work(captured, session)

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
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-006", content)

    session = AsyncMock()
    # show already exists
    existing_show = MagicMock()
    existing_show.id = 50
    existing_show.local_path = "/media/tv/Show"
    found = MagicMock()
    found.scalar_one_or_none.return_value = existing_show
    session.execute = AsyncMock(return_value=found)

    await _invoke_work(captured, session)

    # existing show's title was updated
    assert existing_show.title == "Updated Title"
    # session.add was NOT called for an update
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# _db_import — cancellation propagates out of `work`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_cancellation_propagates_from_work() -> None:
    """TaskCancelledError raised by check_task_cancelled propagates out of `_work`.

    The harness's own catch-and-return-cleanly behavior for TaskCancelledError
    is covered generically in tests/test_worker_harness.py; this only checks
    that _db_import's `work` closure doesn't swallow it itself.
    """
    from jidou.services.progress import TaskCancelledError
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"tmdb_id": 1, "title": "S"}]})
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-007", content)

    session = AsyncMock()
    with (
        patch(
            "jidou.workers.db_import_tasks.check_task_cancelled",
            new_callable=AsyncMock,
            side_effect=TaskCancelledError("cancelled"),
        ),
        pytest.raises(TaskCancelledError),
    ):
        await captured["work"](session, AsyncMock(), AsyncMock(), AsyncMock())  # type: ignore[operator]


# ---------------------------------------------------------------------------
# _db_import — malformed file content propagates from `work`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_malformed_json_propagates_from_work() -> None:
    """A malformed backup file raises JSONDecodeError out of `_work` (harness marks it FAILED)."""
    import json as json_module

    from jidou.workers.db_import_tasks import _db_import

    content = "this is not valid json {{{"
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-008", content)

    with pytest.raises(json_module.JSONDecodeError):
        await captured["work"](AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())  # type: ignore[operator]


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
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-ep1", content)

    session = AsyncMock()
    await _invoke_work(captured, session)

    # No DB lookup should have occurred for the episode
    session.execute.assert_not_called()


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
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-ep2", content)

    session = AsyncMock()
    await _invoke_work(captured, session)

    # show_id=99 was never in show_id_map → episode execute not called
    session.execute.assert_not_called()


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
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-ep3", content)

    session = AsyncMock()
    show_not_found = MagicMock()
    show_not_found.scalar_one_or_none.return_value = None
    ep_not_found = MagicMock()
    ep_not_found.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[show_not_found, ep_not_found])

    added_objects: list = []

    def on_add(obj: object) -> None:
        added_objects.append(obj)
        obj.id = 100  # type: ignore[attr-defined]

    session.add = MagicMock(side_effect=on_add)

    await _invoke_work(captured, session)

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
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-ep4", content)

    session = AsyncMock()
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
    session.execute = AsyncMock(side_effect=[show_found, ep_found])

    await _invoke_work(captured, session)

    # No new objects added — update path
    session.add.assert_not_called()
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
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-wl1", content)

    session = AsyncMock()
    await _invoke_work(captured, session)

    session.execute.assert_not_called()


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
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-wl2", content)

    session = AsyncMock()
    show_not_found = MagicMock()
    show_not_found.scalar_one_or_none.return_value = None
    wl_not_found = MagicMock()
    wl_not_found.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[show_not_found, wl_not_found])

    added_objects: list = []

    def on_add(obj: object) -> None:
        added_objects.append(obj)
        obj.id = 200  # type: ignore[attr-defined]

    session.add = MagicMock(side_effect=on_add)

    await _invoke_work(captured, session)

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
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-wl3", content)

    session = AsyncMock()
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
    session.execute = AsyncMock(side_effect=[show_found, wl_found])

    await _invoke_work(captured, session)

    session.add.assert_not_called()
    assert existing_wl.notes == "done"
    assert existing_wl.position == 7


# ---------------------------------------------------------------------------
# _db_import — branches: backup_show_id is None (no "id" field in row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_import_show_created_without_backup_id() -> None:
    """When show row has no 'id', show_id_map is not populated."""
    from jidou.workers.db_import_tasks import _db_import

    # Row lacks "id" → backup_show_id is None
    content = json.dumps({"shows": [{"tmdb_id": 5001, "title": "No ID Show"}]})
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-show-noid", content)

    session = AsyncMock()
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=not_found)

    added: list = []

    def on_add(obj: object) -> None:
        added.append(obj)
        if hasattr(obj, "tmdb_id"):
            obj.id = 200  # type: ignore[attr-defined]

    session.add = MagicMock(side_effect=on_add)

    await _invoke_work(captured, session)

    assert len(added) == 1


@pytest.mark.asyncio
async def test_db_import_show_updated_without_backup_id() -> None:
    """When existing show row has no 'id', show_id_map is not populated."""
    from jidou.workers.db_import_tasks import _db_import

    content = json.dumps({"shows": [{"tmdb_id": 5002, "title": "No ID Update"}]})
    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-show-upd-noid", content)

    session = AsyncMock()
    existing = MagicMock()
    existing.id = 77
    existing.local_path = "/media/tv/Show"
    found = MagicMock()
    found.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=found)

    await _invoke_work(captured, session)

    assert existing.title == "No ID Update"


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
        patch("jidou.workers._harness.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        db_import_task(file_content="{}")

    assert len(mark_calls) == 1


# ---------------------------------------------------------------------------
# Characterization tests (pin pre-decomposition behaviour of the restore paths)
# ---------------------------------------------------------------------------


def _full_episode() -> Episode:
    """Return an Episode with every restorable field populated."""
    return Episode(
        show_id=1,
        tmdb_id=500,
        season_number=1,
        episode_number=2,
        name="Original",
        overview="Original overview",
        air_date=date(2020, 1, 1),
        runtime=30,
        absolute_episode_number=2,
        episode_type="standard",
        still_path="/s.jpg",
        file_tracked=True,
        file_tracked_at=datetime(2024, 1, 1, 12, 0, 0),
        tracked_filename="a.mkv",
        tracked_source="match",
        watched=True,
        watched_at=datetime(2024, 2, 2, 8, 0, 0),
    )


def test_update_episode_null_and_malformed_rules() -> None:
    """Null clears file_tracked_at; malformed watched_at and null air_date change nothing."""
    ep = _full_episode()
    _update_episode(ep, {"file_tracked_at": None, "watched_at": "garbage", "air_date": None})
    assert ep.file_tracked_at is None
    assert ep.watched_at == datetime(2024, 2, 2, 8, 0, 0)
    assert ep.air_date == date(2020, 1, 1)


def test_update_episode_null_watched_at_clears_and_malformed_tracked_at_keeps() -> None:
    """The two timestamp rules are symmetric: null clears, malformed is ignored."""
    ep = _full_episode()
    _update_episode(ep, {"watched_at": None, "file_tracked_at": "garbage"})
    assert ep.watched_at is None
    assert ep.file_tracked_at == datetime(2024, 1, 1, 12, 0, 0)


def test_update_episode_empty_row_changes_nothing_and_never_rewrites_identity() -> None:
    """An empty backup row changes nothing; show_id/tmdb_id in a row are never applied."""
    ep = _full_episode()
    before = {a.key: getattr(ep, a.key) for a in inspect(Episode).column_attrs}
    _update_episode(ep, {})
    _update_episode(ep, {"show_id": 999, "tmdb_id": 12345})
    after = {a.key: getattr(ep, a.key) for a in inspect(Episode).column_attrs}
    assert after == before


def test_update_show_preserves_local_path_and_cached() -> None:
    """A backup row with local_path=None / cached=False cannot clobber live values."""
    show = Show(tmdb_id=1, title="T", local_path="/live/path", cached=True)
    _update_show(show, {"local_path": None, "cached": False, "tmdb_id": 777})
    assert show.local_path == "/live/path"
    assert show.cached is True
    assert show.tmdb_id == 1


def test_update_show_empty_row_changes_no_column() -> None:
    """An empty backup row changes no Show column."""
    show = Show(
        tmdb_id=1,
        title="T",
        overview="o",
        media_type="movie",
        vote_count=5,
        content_type="anime",
        aliases=["a"],
        track_missing_episodes=False,
        local_path="/p",
    )
    before = {a.key: getattr(show, a.key) for a in inspect(Show).column_attrs}
    _update_show(show, {})
    after = {a.key: getattr(show, a.key) for a in inspect(Show).column_attrs}
    assert after == before


def test_build_show_defaults() -> None:
    """A row with only tmdb_id and title gets the documented defaults, None elsewhere."""
    show = _build_show({"tmdb_id": 1, "title": "T"})
    assert show.media_type == "tv"
    assert show.vote_count == 0
    assert show.cached is False
    assert show.track_missing_episodes is True
    defaulted = {"media_type", "vote_count", "cached", "track_missing_episodes", "tmdb_id", "title"}
    checked = 0
    for attr in inspect(Show).column_attrs:
        if attr.key in {"id", "created_at", "updated_at"} | defaulted:
            continue
        assert getattr(show, attr.key) is None, attr.key
        checked += 1
    assert checked > 20


@pytest.mark.parametrize("missing", ["tmdb_id", "title"])
def test_build_show_requires_tmdb_id_and_title(missing: str) -> None:
    """tmdb_id and title are mandatory when building a Show."""
    row = {"tmdb_id": 1, "title": "T"}
    del row[missing]
    with pytest.raises(KeyError):
        _build_show(row)


@pytest.mark.parametrize("missing", ["show_id", "tmdb_id", "season_number", "episode_number"])
def test_build_episode_requires_identity_fields(missing: str) -> None:
    """show_id, tmdb_id, season_number and episode_number are mandatory for an Episode."""
    row = {"show_id": 1, "tmdb_id": 2, "season_number": 1, "episode_number": 1}
    del row[missing]
    with pytest.raises(KeyError):
        _build_episode(row)


def test_build_episode_defaults() -> None:
    """Absent optional keys give name '', flags False, everything else None."""
    ep = _build_episode({"show_id": 1, "tmdb_id": 2, "season_number": 1, "episode_number": 1})
    assert ep.name == ""
    assert ep.file_tracked is False
    assert ep.watched is False
    assert ep.air_date is None
    assert ep.file_tracked_at is None
    assert ep.watched_at is None


def test_enum_columns_pass_unrecognised_values_through_unchanged() -> None:
    """Restore does no enum coercion: out-of-enum strings are kept verbatim.

    ``str_enum(..., native_enum=False)`` has ``validate_strings=False``, so the bind
    processor lets an unrecognised string through too; both must stay true so a
    restore of such a backup behaves exactly as it always has.
    """
    from sqlalchemy.dialects import postgresql

    show = _build_show({"tmdb_id": 1, "title": "T", "content_type": "bogus"})
    assert show.content_type == "bogus"
    ep = _build_episode(
        {
            "show_id": 1,
            "tmdb_id": 2,
            "season_number": 1,
            "episode_number": 1,
            "tracked_source": "bogus",
        }
    )
    assert ep.tracked_source == "bogus"

    dialect = postgresql.dialect()
    for column in (Show.__table__.c.content_type, Episode.__table__.c.tracked_source):
        processor = column.type.dialect_impl(dialect).bind_processor(dialect)
        assert processor is not None
        assert processor("bogus") == "bogus"


async def _run_work(
    content: dict[str, object], session: AsyncMock, on_progress: AsyncMock
) -> object:
    """Run ``_db_import``'s work closure with a caller-supplied ``on_progress``."""
    from jidou.workers.db_import_tasks import _db_import

    patcher, captured = _capture_run_task_workflow("jidou.workers.db_import_tasks")
    with patcher:
        await _db_import("task-char", json.dumps(content))
    with (
        patch("jidou.workers.db_import_tasks.check_task_cancelled", new_callable=AsyncMock),
    ):
        return await captured["work"](session, on_progress, AsyncMock(), AsyncMock())  # type: ignore[operator]


def _session_finding(existing: object | None = None) -> AsyncMock:
    """Build a mock session whose every lookup returns ``existing`` (or nothing)."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", 7))
    return session


@pytest.mark.asyncio
async def test_episode_progress_cadence() -> None:
    """Episode-phase progress fires only when the running total is a multiple of 100."""
    shows = [{"id": 1, "tmdb_id": 10, "title": "S"}]
    episodes = [
        {"tmdb_id": 1000 + i, "show_id": 1, "season_number": 1, "episode_number": i}
        for i in range(250)
    ]
    on_progress = AsyncMock()

    await _run_work({"shows": shows, "episodes": episodes}, _session_finding(), on_progress)

    calls = [c.args for c in on_progress.await_args_list]
    assert calls[0] == (1, 251, "Shows: 10")
    episode_calls = [c for c in calls if c[2].startswith("Episodes:")]
    assert episode_calls == [(100, 251, "Episodes: 100"), (200, 251, "Episodes: 200")]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_progress_counts_skipped_rows_without_reporting_them() -> None:
    """Skipped show/episode/watchlist rows advance the counter but never report."""
    content = {
        "shows": [
            {"id": 1, "tmdb_id": None, "title": "skip"},
            {"id": 2, "tmdb_id": 20, "title": ""},
            {"id": 3, "tmdb_id": 30, "title": "ok"},
        ],
        "episodes": [{"show_id": 3, "season_number": 1, "episode_number": 1}],
        "watchlist": [{"show_id": 99, "status": "planned"}],
    }
    on_progress = AsyncMock()

    result = await _run_work(content, _session_finding(), on_progress)

    # Only the one successful show reports; its counter value includes the two skips.
    assert [c.args for c in on_progress.await_args_list] == [(3, 5, "Shows: 30")]
    assert result.progress_current == 5  # type: ignore[attr-defined]
    assert result.result_summary["shows_created"] == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_commit_once_per_section_and_result_message() -> None:
    """Three commits (shows, episodes, watchlist) and the exact completion message."""
    session = _session_finding()
    content = {
        "shows": [{"id": 1, "tmdb_id": 10, "title": "S"}],
        "episodes": [
            {"tmdb_id": 11, "show_id": 1, "season_number": 1, "episode_number": 1},
        ],
        "watchlist": [{"show_id": 1, "status": "watching", "notes": "n", "position": 3}],
    }
    result = await _run_work(content, session, AsyncMock())
    assert session.commit.await_count == 3
    assert result.message == (  # type: ignore[attr-defined]
        "Done — 1 shows created, 0 updated; 1 episodes created, 0 updated"
    )
    assert result.result_summary == {  # type: ignore[attr-defined]
        "shows_created": 1,
        "shows_updated": 0,
        "episodes_created": 1,
        "episodes_updated": 0,
        "watchlist_created": 1,
        "watchlist_updated": 0,
    }
    added = [c.args[0] for c in session.add.call_args_list]
    assert [type(o).__name__ for o in added] == ["Show", "Episode", "WatchlistEntry"]
    assert added[1].show_id == 7
    assert added[2].show_id == 7
    assert added[2].position == 3
    assert added[2].notes == "n"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_watchlist_update_keeps_existing_values_for_absent_keys() -> None:
    """An existing watchlist entry keeps status/notes/position absent from the row."""
    from jidou.models.watchlist import WatchlistEntry, WatchlistStatus

    entry = WatchlistEntry(show_id=7, status=WatchlistStatus("watching"), notes="keep", position=4)
    existing_show = MagicMock()
    existing_show.id = 7
    existing_show.local_path = None
    lookups = [existing_show, entry]

    def _next(*_a: object, **_k: object) -> MagicMock:
        found = MagicMock()
        found.scalar_one_or_none.return_value = lookups.pop(0)
        return found

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=_next)
    session.add = MagicMock()
    content = {
        "shows": [{"id": 1, "tmdb_id": 10, "title": "S"}],
        "watchlist": [{"show_id": 1}],
    }
    result = await _run_work(content, session, AsyncMock())
    assert entry.status == WatchlistStatus("watching")
    assert entry.notes == "keep"
    assert entry.position == 4
    assert result.result_summary["watchlist_updated"] == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_invalid_watchlist_status_raises_value_error() -> None:
    """A watchlist status outside the enum propagates ValueError (unchanged behaviour)."""
    content = {
        "shows": [{"id": 1, "tmdb_id": 10, "title": "S"}],
        "watchlist": [{"show_id": 1, "status": "bogus"}],
    }
    with pytest.raises(ValueError, match="bogus"):
        await _run_work(content, _session_finding(), AsyncMock())


# The hand-written column list restore used before ``_SHOW_COLUMNS`` was derived from
# ``show_columns(...)``; kept verbatim so the derivation can never silently drift.
_LEGACY_SHOW_HANDLED_COLUMNS = frozenset(
    [
        "tmdb_id",
        "title",
        "overview",
        "media_type",
        "poster_path",
        "backdrop_path",
        "vote_average",
        "vote_count",
        "release_date",
        "original_language",
        "cached",
        "content_type",
        "sys_name",
        "aliases",
        "aliases_sources",
        "genres",
        "origin_country",
        "last_air_date",
        "last_episode_to_air",
        "next_episode_to_air",
        "homepage",
        "external_ids",
        "episode_groups",
        "episode_group_map",
        "active_episode_group_id",
        "active_episode_group_name",
        "status",
        "in_production",
        "number_of_seasons",
        "number_of_episodes",
        "networks",
        "show_type",
        "runtime",
        "tagline",
        "local_path",
        "adult",
        "list_poster_path",
        "detail_poster_path",
        "banner_path",
        "track_missing_episodes",
    ]
)

_LEGACY_EPISODE_HANDLED_COLUMNS = frozenset(
    [
        "show_id",
        "tmdb_id",
        "season_number",
        "episode_number",
        "name",
        "overview",
        "air_date",
        "runtime",
        "absolute_episode_number",
        "episode_type",
        "still_path",
        "file_tracked",
        "file_tracked_at",
        "tracked_filename",
        "tracked_source",
        "watched",
        "watched_at",
    ]
)


def test_column_tables_equal_legacy_handled_sets() -> None:
    """The derived column tables restore exactly the columns the old literals listed."""
    from jidou.workers.db_import_tasks import _EPISODE_COLUMNS, _SHOW_COLUMNS

    assert len(_LEGACY_SHOW_HANDLED_COLUMNS) == 40
    assert {c.name for c in _SHOW_COLUMNS} == _LEGACY_SHOW_HANDLED_COLUMNS
    assert len(_SHOW_COLUMNS) == len(_LEGACY_SHOW_HANDLED_COLUMNS)
    assert {c.name for c in _EPISODE_COLUMNS} == _LEGACY_EPISODE_HANDLED_COLUMNS
    assert len(_EPISODE_COLUMNS) == len(_LEGACY_EPISODE_HANDLED_COLUMNS)


def test_restore_leaves_metadata_refreshed_at_null_so_restored_shows_refresh_first() -> None:
    from jidou.workers.db_import_tasks import (
        _SHOW_COLUMNS,
        _build_show,
        check_restore_field_coverage,
    )

    assert "metadata_refreshed_at" not in {c.name for c in _SHOW_COLUMNS}
    assert check_restore_field_coverage()["Show"] == set()
    row = {"tmdb_id": 1, "title": "T", "metadata_refreshed_at": "2026-01-01T00:00:00+00:00"}
    assert _build_show(row).metadata_refreshed_at is None


def test_column_defaults_and_update_exclusions() -> None:
    """Build defaults and the insert-only / special-update sets match the documented rules."""
    from jidou.workers.db_import_tasks import (
        _EPISODE_COLUMNS,
        _EPISODE_UPDATE_SPECIAL,
        _SHOW_COLUMNS,
        _SHOW_INSERT_ONLY,
    )

    show_defaults = {c.name: c.default for c in _SHOW_COLUMNS if c.default is not None}
    assert show_defaults == {
        "media_type": "tv",
        "vote_count": 0,
        "cached": False,
        "track_missing_episodes": True,
    }
    assert {c.name for c in _SHOW_COLUMNS if c.required} == {"tmdb_id", "title"}
    episode_defaults = {c.name: c.default for c in _EPISODE_COLUMNS if c.default is not None}
    assert episode_defaults == {"name": "", "file_tracked": False, "watched": False}
    assert {c.name for c in _EPISODE_COLUMNS if c.required} == {
        "show_id",
        "tmdb_id",
        "season_number",
        "episode_number",
    }
    assert {"tmdb_id", "cached"} == _SHOW_INSERT_ONLY
    assert {
        "show_id",
        "tmdb_id",
        "air_date",
        "file_tracked_at",
        "watched_at",
    } == _EPISODE_UPDATE_SPECIAL
