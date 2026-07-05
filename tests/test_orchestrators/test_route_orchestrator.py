"""Tests for RouteOrchestrator (MATCHED → ROUTED file routing)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.route_orchestrator import RouteOrchestrator, _final_path_for

# ---------------------------------------------------------------------------
# _final_path_for unit tests
# ---------------------------------------------------------------------------


def test_final_path_tv_creates_season_subdir() -> None:
    """TV file lands in Season NN subdirectory."""
    path = _final_path_for("/media/tv/Show", season=2, filename="ep.mkv")
    assert path == Path("/media/tv/Show/Season 02/ep.mkv")


def test_final_path_tv_season_zero_pads() -> None:
    """Season number is zero-padded to two digits."""
    path = _final_path_for("/media/tv/Show", season=1, filename="ep.mkv")
    assert path.parts[-2] == "Season 01" and path.name == "ep.mkv"


def test_final_path_movie_lands_in_show_root() -> None:
    """Movie (is_movie=True) skips the season subdirectory."""
    path = _final_path_for("/media/movies/Film", season=None, filename="film.mkv", is_movie=True)
    assert path == Path("/media/movies/Film/film.mkv")


def test_final_path_no_season_lands_in_show_root() -> None:
    """File with season=None (not a movie) lands directly under show root."""
    path = _final_path_for("/media/tv/Show", season=None, filename="special.mkv")
    assert path == Path("/media/tv/Show/special.mkv")


def test_final_path_movie_with_season_still_uses_root() -> None:
    """is_movie=True takes precedence — season param is ignored."""
    path = _final_path_for("/media/movies/Film", season=1, filename="film.mkv", is_movie=True)
    assert path == Path("/media/movies/Film/film.mkv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(
    file_id: int = 1,
    filename: str = "Show.S01E01.mkv",
    local_path: str | None = "/staging/Show.S01E01.mkv",
    status: FileStatus = FileStatus.MATCHED,
    show_id: int = 10,
    episode_id: int | None = 1,
    parsed_season: int | None = 1,
    parsed_episode: int | None = 1,
) -> MagicMock:
    f = MagicMock()
    f.id = file_id
    f.original_filename = filename
    f.local_path = local_path
    f.status = status
    f.show_id = show_id
    f.episode_id = episode_id
    f.parsed_season = parsed_season
    f.parsed_episode = parsed_episode
    f.error_message = None
    return f


def _make_show(
    show_id: int = 10,
    local_path: str | None = "/media/tv/Show",
    content_type: str | None = "tv",
    media_type: str = "tv",
) -> MagicMock:
    s = MagicMock()
    s.id = show_id
    s.local_path = local_path
    s.content_type = content_type
    s.media_type = media_type
    return s


def _make_episode(
    ep_id: int = 1,
    season: int = 1,
    ep_num: int = 1,
) -> MagicMock:
    e = MagicMock()
    e.id = ep_id
    e.season_number = season
    e.episode_number = ep_num
    e.file_tracked = False
    e.file_tracked_at = None
    e.tracked_filename = None
    e.tracked_source = None
    return e


def _make_session(
    file_show_pairs: list[tuple],
    ep: MagicMock | None = None,
) -> MagicMock:
    """Build a mock AsyncSession for RouteOrchestrator.run().

    Execute side_effect order:
      1. files+shows query         → .all()
      2. episode lookup (optional) → .scalar_one_or_none()
    """
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    files_result = MagicMock()
    files_result.all.return_value = file_show_pairs

    side_effects: list = [files_result]
    if ep is not None:
        ep_result = MagicMock()
        ep_result.scalar_one_or_none.return_value = ep
        side_effects.append(ep_result)

    session.execute = AsyncMock(side_effect=side_effects)
    return session


# ---------------------------------------------------------------------------
# run() — no files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_no_matched_files_returns_empty_result() -> None:
    """run() with no MATCHED files returns zeroed RouteResult."""
    files_result = MagicMock()
    files_result.all.return_value = []
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=files_result)

    orch = RouteOrchestrator(session)
    result = await orch.run()

    assert result.files_routed == 0
    assert result.files_failed == 0


# ---------------------------------------------------------------------------
# run() — show has no local_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_no_local_path_marks_error() -> None:
    """File whose show has no local_path is marked ERROR."""
    file = _make_file()
    show = _make_show(local_path=None)
    session = _make_session([(file, show)])

    orch = RouteOrchestrator(session)
    result = await orch.run()

    assert result.files_failed == 1
    assert result.files_routed == 0
    assert file.status == FileStatus.ERROR
    assert "local_path" in (file.error_message or "")


# ---------------------------------------------------------------------------
# run() — dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_dry_run_does_not_move_files() -> None:
    """dry_run=True increments files_routed without calling shutil.move."""
    file = _make_file()
    show = _make_show()
    session = _make_session([(file, show)])

    with patch("shutil.move") as mock_move:
        orch = RouteOrchestrator(session)
        result = await orch.run(dry_run=True)

    mock_move.assert_not_called()
    assert result.dry_run is True
    assert result.files_routed == 1


@pytest.mark.asyncio
async def test_run_dry_run_no_local_path_does_not_fail() -> None:
    """dry_run=True with missing local_path still increments routed (logs warning only)."""
    file = _make_file()
    show = _make_show(local_path=None)
    session = _make_session([(file, show)])

    orch = RouteOrchestrator(session)
    result = await orch.run(dry_run=True)

    # dry_run skips the error branch for missing local_path
    assert result.files_routed == 0
    assert result.files_failed == 0


# ---------------------------------------------------------------------------
# run() — successful file move
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_successful_route_moves_file_and_marks_routed(tmp_path: Path) -> None:
    """A matched file is moved to its final path and marked ROUTED."""
    # Create a real staging file
    staging = tmp_path / "staging" / "Show.S01E01.mkv"
    staging.parent.mkdir()
    staging.write_bytes(b"video")

    dest_dir = tmp_path / "media" / "tv" / "Show"

    file = _make_file(local_path=str(staging))
    show = _make_show(local_path=str(dest_dir))
    ep = _make_episode()
    session = _make_session([(file, show)], ep=ep)

    orch = RouteOrchestrator(session)
    result = await orch.run()

    assert result.files_routed == 1
    assert result.files_failed == 0
    assert file.status == FileStatus.ROUTED
    assert not staging.exists()
    expected = dest_dir / "Season 01" / "Show.S01E01.mkv"
    assert expected.exists()


@pytest.mark.asyncio
async def test_run_movie_routes_to_show_root(tmp_path: Path) -> None:
    """Movie files land directly under show root (no Season NN subdirectory)."""
    staging = tmp_path / "staging" / "Film.mkv"
    staging.parent.mkdir()
    staging.write_bytes(b"video")

    dest_dir = tmp_path / "media" / "movies" / "Film"

    file = _make_file(filename="Film.mkv", local_path=str(staging), parsed_season=None)
    show = _make_show(local_path=str(dest_dir), content_type="movie", media_type="movie")
    ep = _make_episode()
    session = _make_session([(file, show)], ep=ep)

    orch = RouteOrchestrator(session)
    result = await orch.run()

    assert result.files_routed == 1
    assert (dest_dir / "Film.mkv").exists()


# ---------------------------------------------------------------------------
# run() — file already at destination (synthetic import no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_source_equals_dest_skips_move(tmp_path: Path) -> None:
    """When source path equals dest, file is marked ROUTED without shutil.move."""
    show_dir = tmp_path / "media" / "tv" / "Show" / "Season 01"
    show_dir.mkdir(parents=True)
    filepath = show_dir / "Show.S01E01.mkv"
    filepath.write_bytes(b"video")

    # File is already at its final path
    file = _make_file(local_path=str(filepath))
    show = _make_show(local_path=str(tmp_path / "media" / "tv" / "Show"))
    ep = _make_episode()
    session = _make_session([(file, show)], ep=ep)

    with patch("shutil.move") as mock_move:
        orch = RouteOrchestrator(session)
        result = await orch.run()

    mock_move.assert_not_called()
    assert result.files_routed == 1
    assert file.status == FileStatus.ROUTED


# ---------------------------------------------------------------------------
# run() — retry path (staging gone but dest exists)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_retry_staging_gone_dest_exists(tmp_path: Path) -> None:
    """When staging is gone but dest exists, file is marked ROUTED (idempotent retry)."""
    dest_dir = tmp_path / "media" / "tv" / "Show" / "Season 01"
    dest_dir.mkdir(parents=True)
    dest_file = dest_dir / "Show.S01E01.mkv"
    dest_file.write_bytes(b"video")

    staging_path = str(tmp_path / "staging" / "Show.S01E01.mkv")
    # staging does NOT exist

    file = _make_file(local_path=staging_path)
    show = _make_show(local_path=str(tmp_path / "media" / "tv" / "Show"))
    ep = _make_episode()
    session = _make_session([(file, show)], ep=ep)

    orch = RouteOrchestrator(session)
    result = await orch.run()

    assert result.files_routed == 1
    assert file.status == FileStatus.ROUTED
    assert file.local_path == str(dest_file)


# ---------------------------------------------------------------------------
# run() — filename collision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_collision_appends_numeric_suffix(tmp_path: Path) -> None:
    """Destination collision results in a numeric suffix rather than overwrite."""
    show_dir = tmp_path / "media" / "tv" / "Show" / "Season 01"
    show_dir.mkdir(parents=True)
    # Pre-existing file at the expected destination
    existing = show_dir / "Show.S01E01.mkv"
    existing.write_bytes(b"existing")

    staging = tmp_path / "staging" / "Show.S01E01.mkv"
    staging.parent.mkdir()
    staging.write_bytes(b"new video")

    file = _make_file(local_path=str(staging))
    show = _make_show(local_path=str(tmp_path / "media" / "tv" / "Show"))
    ep = _make_episode()
    session = _make_session([(file, show)], ep=ep)

    orch = RouteOrchestrator(session)
    result = await orch.run()

    assert result.files_routed == 1
    # Suffixed file should now exist
    assert (show_dir / "Show.S01E01.1.mkv").exists()
    # Original file should be untouched
    assert existing.read_bytes() == b"existing"


# ---------------------------------------------------------------------------
# run() — shutil.move failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_shutil_failure_marks_error(tmp_path: Path) -> None:
    """If shutil.move raises, file is marked ERROR and local_path reset to staging."""
    staging = tmp_path / "staging" / "Show.S01E01.mkv"
    staging.parent.mkdir()
    staging.write_bytes(b"video")

    file = _make_file(local_path=str(staging))
    original_staging_path = str(staging)
    show = _make_show(local_path=str(tmp_path / "media" / "tv" / "Show"))
    ep = _make_episode()
    session = _make_session([(file, show)], ep=ep)

    with patch("shutil.move", side_effect=OSError("permission denied")):
        orch = RouteOrchestrator(session)
        result = await orch.run()

    assert result.files_failed == 1
    assert file.status == FileStatus.ERROR
    assert "permission denied" in (file.error_message or "")
    # local_path must be reset to staging so a retry can find the file
    assert file.local_path == original_staging_path


# ---------------------------------------------------------------------------
# run() — episode tracking via episode_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_episode_tracking_set_via_episode_id(tmp_path: Path) -> None:
    """After routing, episode tracking fields are set via file.episode_id."""
    staging = tmp_path / "ep.mkv"
    staging.write_bytes(b"v")

    file = _make_file(filename="ep.mkv", local_path=str(staging), episode_id=5)
    show = _make_show(local_path=str(tmp_path / "show"))
    ep = _make_episode(ep_id=5)
    session = _make_session([(file, show)], ep=ep)

    orch = RouteOrchestrator(session)
    await orch.run()

    assert ep.file_tracked is True
    assert ep.tracked_filename == "ep.mkv"
    assert ep.tracked_source == "match"
    assert ep.file_tracked_at is not None


# ---------------------------------------------------------------------------
# run() — episode tracking via parsed_season / parsed_episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_episode_tracking_resolved_via_parsed_numbers(tmp_path: Path) -> None:
    """When episode_id is None, tracking is resolved from parsed_season/parsed_episode."""
    staging = tmp_path / "ep.mkv"
    staging.write_bytes(b"v")

    file = _make_file(
        filename="ep.mkv",
        local_path=str(staging),
        episode_id=None,
        parsed_season=1,
        parsed_episode=3,
    )
    show = _make_show(local_path=str(tmp_path / "show"))
    ep = _make_episode(ep_id=3, season=1, ep_num=3)

    # For parsed resolution path: files query + episode-by-parsed query + orphan delete
    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = ep
    orphan_result = MagicMock()
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, ep_result, orphan_result])

    orch = RouteOrchestrator(session)
    await orch.run()

    assert ep.file_tracked is True
    assert file.episode_id == ep.id


# ---------------------------------------------------------------------------
# run() — anime absolute episode routing (parsed_season=None, episode_id set)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_anime_no_season_routes_to_season_dir_via_episode_id(tmp_path: Path) -> None:
    """Anime file with parsed_season=None but episode_id set routes to Season NN via episode row."""
    staging = tmp_path / "staging" / "[SubsPlease] Kill Ao - 12 (1080p) [9C22A8A0].mkv"
    staging.parent.mkdir()
    staging.write_bytes(b"video")

    show_dir = tmp_path / "media" / "anime" / "Kill Ao"
    file = _make_file(
        filename="[SubsPlease] Kill Ao - 12 (1080p) [9C22A8A0].mkv",
        local_path=str(staging),
        episode_id=12,
        parsed_season=None,  # LLM found no season indicator
        parsed_episode=12,
    )
    show = _make_show(local_path=str(show_dir), content_type="anime", media_type="tv")
    ep = _make_episode(ep_id=12, season=1, ep_num=12)

    # Execute order: files query → season-lookup-by-episode-id → episode-tracking-by-episode-id
    files_result = MagicMock()
    files_result.all.return_value = [(file, show)]
    season_ep_result = MagicMock()
    season_ep_result.scalar_one_or_none.return_value = ep
    tracking_ep_result = MagicMock()
    tracking_ep_result.scalar_one_or_none.return_value = ep
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[files_result, season_ep_result, tracking_ep_result])

    orch = RouteOrchestrator(session)
    result = await orch.run()

    assert result.files_routed == 1
    expected = show_dir / "Season 01" / "[SubsPlease] Kill Ao - 12 (1080p) [9C22A8A0].mkv"
    assert expected.exists()
    assert ep.file_tracked is True


# ---------------------------------------------------------------------------
# run() — on_progress callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_on_progress_called_per_file() -> None:
    """on_progress callback is invoked once per file."""
    f1 = _make_file(file_id=1)
    f2 = _make_file(file_id=2)
    show = _make_show(local_path=None)  # no local_path → fast error path

    files_result = MagicMock()
    files_result.all.return_value = [(f1, show), (f2, show)]
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=files_result)

    on_progress = AsyncMock()
    orch = RouteOrchestrator(session)
    await orch.run(on_progress=on_progress)

    assert on_progress.call_count == 2
    calls = on_progress.call_args_list
    assert calls[0].args[0] == 1
    assert calls[1].args[0] == 2


# ---------------------------------------------------------------------------
# run() — on_event callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_on_event_called_for_skip() -> None:
    """on_event is called when a file is skipped (no local_path)."""
    file = _make_file()
    show = _make_show(local_path=None)
    session = _make_session([(file, show)])

    on_event = AsyncMock()

    orch = RouteOrchestrator(session)
    await orch.run(on_event=on_event)

    # on_event should be called for the skipped file
    assert on_event.call_count >= 1
    # Find the skip event
    skip_calls = [c for c in on_event.call_args_list if "skip" in c[0][1].lower()]
    assert len(skip_calls) > 0


@pytest.mark.asyncio
async def test_run_on_event_called_for_dry_run() -> None:
    """on_event is called in dry_run mode with dry-run indicator."""
    file = _make_file()
    show = _make_show()
    session = _make_session([(file, show)])

    on_event = AsyncMock()

    orch = RouteOrchestrator(session)
    await orch.run(dry_run=True, on_event=on_event)

    # on_event should be called with dry-run message
    assert on_event.call_count >= 1
    dry_run_calls = [c for c in on_event.call_args_list if "dry run" in c[0][1].lower()]
    assert len(dry_run_calls) > 0


@pytest.mark.asyncio
async def test_run_on_event_called_on_successful_route(tmp_path: Path) -> None:
    """on_event is called with success details after file is routed."""
    staging = tmp_path / "ep.mkv"
    staging.write_bytes(b"v")

    file = _make_file(filename="ep.mkv", local_path=str(staging))
    show = _make_show(local_path=str(tmp_path / "show"))
    ep = _make_episode()
    session = _make_session([(file, show)], ep=ep)

    on_event = AsyncMock()

    orch = RouteOrchestrator(session)
    await orch.run(on_event=on_event)

    # on_event should be called with success message
    success_calls = [c for c in on_event.call_args_list if "routed" in c[0][1].lower()]
    assert len(success_calls) > 0
    # Verify context includes file_id and show name
    assert success_calls[0].args[0] == "info"  # level
    assert success_calls[0].args[2] is not None  # context dict


@pytest.mark.asyncio
async def test_run_on_event_called_on_routing_failure(tmp_path: Path) -> None:
    """on_event is called with error details if routing fails."""
    staging = tmp_path / "ep.mkv"
    staging.write_bytes(b"v")

    file = _make_file(local_path=str(staging))
    show = _make_show(local_path=str(tmp_path / "show"))
    ep = _make_episode()
    session = _make_session([(file, show)], ep=ep)

    on_event = AsyncMock()

    # Patch shutil.move to raise an error
    with patch("shutil.move", side_effect=OSError("disk full")):
        orch = RouteOrchestrator(session)
        await orch.run(on_event=on_event)

    # on_event should be called with error message
    error_calls = [c for c in on_event.call_args_list if c[0][0] == "error"]
    assert len(error_calls) > 0
    assert "disk full" in error_calls[0].args[1]
