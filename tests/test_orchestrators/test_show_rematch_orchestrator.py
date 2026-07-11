"""Tests for ShowRematchOrchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators.show_rematch_orchestrator import ShowRematchOrchestrator, TrackingSnapshot
from jidou.schemas.show_schema import RematchRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_show(
    show_id: int = 1,
    tmdb_id: int = 100,
    title: str = "Test Show",
    media_type: str = "tv",
) -> MagicMock:
    s = MagicMock()
    s.id = show_id
    s.tmdb_id = tmdb_id
    s.title = title
    s.media_type = media_type
    return s


def _make_episode(
    ep_id: int = 1,
    show_id: int = 1,
    season: int = 1,
    ep_num: int = 1,
    name: str = "Pilot",
    file_tracked: bool = False,
    tracked_filename: str | None = None,
    tracked_source: str | None = None,
    file_tracked_at: object = None,
) -> MagicMock:
    e = MagicMock()
    e.id = ep_id
    e.show_id = show_id
    e.season_number = season
    e.episode_number = ep_num
    e.name = name
    e.file_tracked = file_tracked
    e.file_tracked_at = file_tracked_at
    e.tracked_filename = tracked_filename
    e.tracked_source = tracked_source
    return e


def _make_file(
    file_id: int = 1,
    show_id: int = 1,
    episode_id: int | None = None,
    parsed_season: int | None = None,
    parsed_episode: int | None = None,
    original_filename: str = "show.S01E01.mkv",
    local_path: str | None = None,
) -> MagicMock:
    f = MagicMock()
    f.id = file_id
    f.show_id = show_id
    f.episode_id = episode_id
    f.parsed_season = parsed_season
    f.parsed_episode = parsed_episode
    f.original_filename = original_filename
    f.local_path = local_path
    return f


def _make_payload(
    tmdb_id: int = 200,
    media_type: str = "tv",
    preserve_tracking: bool = True,
) -> RematchRequest:
    return RematchRequest(
        tmdb_id=tmdb_id, media_type=media_type, preserve_tracking=preserve_tracking
    )


def _make_tmdb_data(title: str = "New Show Title") -> dict:
    return {
        "name": title,
        "overview": "A great show.",
        "poster_path": "/poster.jpg",
        "backdrop_path": "/backdrop.jpg",
        "vote_average": 8.5,
        "vote_count": 1000,
        "first_air_date": "2020-01-01",
        "original_language": "en",
        "genres": [{"id": 18, "name": "Drama"}],
        "origin_country": ["US"],
        "status": "Ended",
        "in_production": False,
        "number_of_seasons": 2,
        "number_of_episodes": 20,
        "networks": [],
        "type": "Scripted",
        "episode_run_time": [45],
        "tagline": "A tagline.",
        "external_ids": {},
        "episode_groups": [],
    }


def _make_session(
    *,
    episode_list_result: list | None = None,
    new_episode_list_result: list | None = None,
    orphaned_files_result: list | None = None,
) -> MagicMock:
    """Build a minimal mock AsyncSession."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()

    # Build the side-effect chain for execute():
    # 1. Episode delete (result ignored)
    # 2. OrphanedTrackingRecord delete (result ignored)
    # 3. (conditional) tracked episode query for snapshot
    # 4. (conditional) new episode query for restore
    # 5. (conditional) orphaned files query for relink
    # We set up a flexible side_effect list.
    delete_result = MagicMock()

    tracked_result = MagicMock()
    tracked_result.scalars.return_value.all.return_value = episode_list_result or []

    new_eps_result = MagicMock()
    new_eps_result.scalars.return_value.all.return_value = new_episode_list_result or []

    orphan_result = MagicMock()
    orphan_result.scalars.return_value.all.return_value = orphaned_files_result or []

    session.execute = AsyncMock(
        side_effect=[
            tracked_result,  # snapshot query
            delete_result,  # episode delete
            delete_result,  # orphan record delete
            new_eps_result,  # new episodes for restore
            orphan_result,  # orphaned files for relink
            # Extras so the mock doesn't raise StopIteration on unexpected calls
            MagicMock(),
            MagicMock(),
        ]
    )
    return session


# ---------------------------------------------------------------------------
# _fetch_tmdb_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_tmdb_details_returns_data() -> None:
    """_fetch_tmdb_details returns raw TMDB dict on success."""
    session = MagicMock()
    tmdb = MagicMock()
    tmdb.get_details = AsyncMock(return_value={"name": "My Show"})

    orch = ShowRematchOrchestrator(session, tmdb)
    result = await orch._fetch_tmdb_details(_make_payload())

    assert result["name"] == "My Show"


@pytest.mark.asyncio
async def test_fetch_tmdb_details_raises_502_on_error() -> None:
    """_fetch_tmdb_details wraps TMDB exceptions as 502 HTTPException."""
    from fastapi import HTTPException

    session = MagicMock()
    tmdb = MagicMock()
    tmdb.get_details = AsyncMock(side_effect=RuntimeError("network error"))

    orch = ShowRematchOrchestrator(session, tmdb)

    with pytest.raises(HTTPException) as exc_info:
        await orch._fetch_tmdb_details(_make_payload())

    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_fetch_tmdb_details_includes_external_ids_and_episode_groups() -> None:
    """_fetch_tmdb_details populates external_ids/episode_groups via their own endpoints.

    Regression test for Bug1: get_details() alone never returns these
    fields; a same-entity refresh that only called get_details() would
    silently wipe a show's external_ids/episode_groups on every rematch.
    """
    session = MagicMock()
    tmdb = MagicMock()
    tmdb.get_details = AsyncMock(return_value={"name": "My Show"})
    tmdb.get_external_ids = AsyncMock(return_value={"imdb_id": "tt123"})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": [{"id": "g1"}]})

    orch = ShowRematchOrchestrator(session, tmdb)
    data = await orch._fetch_tmdb_details(_make_payload(tmdb_id=200, media_type="tv"))

    tmdb.get_external_ids.assert_awaited_once_with(200, media_type="tv")
    tmdb.get_episode_groups.assert_awaited_once_with(200)
    assert data["external_ids"] == {"imdb_id": "tt123"}
    assert data["episode_groups"] == [{"id": "g1"}]

    show = _make_show(tmdb_id=200)
    orch._apply_tmdb_metadata(show, _make_payload(tmdb_id=200, media_type="tv"), data)

    assert show.external_ids == {"imdb_id": "tt123"}
    assert show.episode_groups == [{"id": "g1"}]


# ---------------------------------------------------------------------------
# _apply_tmdb_metadata
# ---------------------------------------------------------------------------


def test_apply_tmdb_metadata_updates_show_fields() -> None:
    """_apply_tmdb_metadata writes TMDB-sourced fields and derives sys_name."""
    session = MagicMock()
    tmdb = MagicMock()
    show = _make_show()
    payload = _make_payload(tmdb_id=200, media_type="tv")
    data = _make_tmdb_data(title="New Show: Extended")

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._apply_tmdb_metadata(show, payload, data)

    assert show.tmdb_id == 200
    assert show.title == "New Show: Extended"
    assert show.sys_name == "New Show Extended"  # colon → space
    assert show.overview == "A great show."
    assert show.vote_average == 8.5
    assert show.original_language == "en"
    assert show.number_of_seasons == 2


def test_apply_tmdb_metadata_stores_adult_flag() -> None:
    """_apply_tmdb_metadata writes the TMDB adult flag onto the show."""
    session = MagicMock()
    tmdb = MagicMock()
    show = _make_show()
    payload = _make_payload(tmdb_id=200, media_type="tv")
    data = _make_tmdb_data(title="Adult Show")
    data["adult"] = True

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._apply_tmdb_metadata(show, payload, data)

    assert show.adult is True


def test_apply_tmdb_metadata_preserves_adult_flag_on_same_entity_refresh() -> None:
    """Refreshing the same TMDB entity keeps a known adult flag when the response omits it."""
    session = MagicMock()
    tmdb = MagicMock()
    show = _make_show(tmdb_id=200)  # same tmdb_id as the rematch payload below
    show.adult = True
    payload = _make_payload(tmdb_id=200, media_type="tv")
    data = _make_tmdb_data(title="Still Adult Show")
    assert "adult" not in data

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._apply_tmdb_metadata(show, payload, data)

    assert show.adult is True


def test_apply_tmdb_metadata_clears_adult_flag_on_identity_change() -> None:
    """Rematching to a different tmdb_id does not carry over the old show's adult flag."""
    session = MagicMock()
    tmdb = MagicMock()
    show = _make_show(tmdb_id=100)  # different tmdb_id from the rematch payload below
    show.adult = True
    payload = _make_payload(tmdb_id=200, media_type="tv")
    data = _make_tmdb_data(title="Different Show")
    assert "adult" not in data

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._apply_tmdb_metadata(show, payload, data)

    assert show.adult is None


def test_apply_tmdb_metadata_movie_uses_title_field() -> None:
    """Movie responses use 'title' + 'release_date' instead of 'name' + 'first_air_date'."""
    session = MagicMock()
    tmdb = MagicMock()
    show = _make_show(media_type="movie")
    payload = _make_payload(media_type="movie")
    data = {"title": "Great Movie", "release_date": "2023-06-01"}

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._apply_tmdb_metadata(show, payload, data)

    assert show.title == "Great Movie"
    assert show.release_date == "2023-06-01"


def test_apply_tmdb_metadata_falls_back_to_existing_title() -> None:
    """When TMDB returns no name/title, the existing show title is preserved."""
    session = MagicMock()
    tmdb = MagicMock()
    show = _make_show(title="Existing Title")
    payload = _make_payload()
    data: dict = {}

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._apply_tmdb_metadata(show, payload, data)

    assert show.title == "Existing Title"


def test_apply_tmdb_metadata_runtime_from_episode_run_time() -> None:
    """runtime falls back to episode_run_time[0] when runtime key is absent."""
    session = MagicMock()
    tmdb = MagicMock()
    show = _make_show()
    payload = _make_payload()
    data = {"name": "Show", "episode_run_time": [42]}

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._apply_tmdb_metadata(show, payload, data)

    assert show.runtime == 42


# ---------------------------------------------------------------------------
# _snapshot_tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_tracking_returns_empty_for_movie() -> None:
    """Snapshot is skipped (empty dict) for movie media type."""
    session = MagicMock()
    tmdb = MagicMock()
    payload = _make_payload(media_type="movie")

    orch = ShowRematchOrchestrator(session, tmdb)
    result = await orch._snapshot_tracking(1, payload)

    assert result == {}
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_tracking_returns_empty_when_preserve_false() -> None:
    """Snapshot is skipped when preserve_tracking=False."""
    session = MagicMock()
    tmdb = MagicMock()
    payload = _make_payload(preserve_tracking=False)

    orch = ShowRematchOrchestrator(session, tmdb)
    result = await orch._snapshot_tracking(1, payload)

    assert result == {}
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_tracking_captures_tracked_episodes() -> None:
    """Snapshot captures (season, episode) → TrackingSnapshot for tracked episodes."""
    ep = _make_episode(season=1, ep_num=3, file_tracked=True, tracked_filename="ep3.mkv")

    session = MagicMock()
    ep_result = MagicMock()
    ep_result.scalars.return_value.all.return_value = [ep]
    session.execute = AsyncMock(return_value=ep_result)

    tmdb = MagicMock()
    payload = _make_payload(preserve_tracking=True)

    orch = ShowRematchOrchestrator(session, tmdb)
    result = await orch._snapshot_tracking(1, payload)

    assert (1, 3) in result
    assert result[(1, 3)]["tracked_filename"] == "ep3.mkv"


# ---------------------------------------------------------------------------
# _restore_tracking_and_relink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_tracking_migrates_matched_episodes() -> None:
    """Tracked episodes whose (season, episode) key exists in new list are restored."""
    new_ep = _make_episode(ep_id=99, season=1, ep_num=1)

    new_eps_result = MagicMock()
    new_eps_result.scalars.return_value.all.return_value = [new_ep]

    orphan_result = MagicMock()
    orphan_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=[new_eps_result, orphan_result])

    tmdb = MagicMock()
    old_tracking: dict[tuple[int, int], TrackingSnapshot] = {
        (1, 1): TrackingSnapshot(
            tracked_filename="ep1.mkv",
            tracked_source="match",
            file_tracked_at=None,
        )
    }

    orch = ShowRematchOrchestrator(session, tmdb)
    await orch._restore_tracking_and_relink(1, old_tracking)

    assert new_ep.file_tracked is True
    assert new_ep.tracked_filename == "ep1.mkv"
    assert new_ep.tracked_source == "match"


@pytest.mark.asyncio
async def test_restore_tracking_relinks_orphaned_files() -> None:
    """Orphaned DownloadedFiles are re-linked when a matching new episode exists."""
    new_ep = _make_episode(ep_id=99, season=1, ep_num=5)
    orphaned_file = _make_file(
        file_id=7, show_id=1, episode_id=None, parsed_season=1, parsed_episode=5
    )

    new_eps_result = MagicMock()
    new_eps_result.scalars.return_value.all.return_value = [new_ep]
    orphan_result = MagicMock()
    orphan_result.scalars.return_value.all.return_value = [orphaned_file]

    session = MagicMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=[new_eps_result, orphan_result])

    tmdb = MagicMock()

    orch = ShowRematchOrchestrator(session, tmdb)
    await orch._restore_tracking_and_relink(1, {})

    assert orphaned_file.episode_id == new_ep.id


@pytest.mark.asyncio
async def test_restore_tracking_creates_orphan_record_for_unrecoverable_key() -> None:
    """Unrecoverable tracking keys (no matching new episode) become OrphanedTrackingRecords."""
    new_eps_result = MagicMock()
    new_eps_result.scalars.return_value.all.return_value = []  # no new episodes
    orphan_result = MagicMock()
    orphan_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=[new_eps_result, orphan_result])

    tmdb = MagicMock()
    old_tracking: dict[tuple[int, int], TrackingSnapshot] = {
        (2, 3): TrackingSnapshot(
            tracked_filename="s02e03.mkv",
            tracked_source="match",
            file_tracked_at=None,
        )
    }

    orch = ShowRematchOrchestrator(session, tmdb)
    await orch._restore_tracking_and_relink(1, old_tracking)

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.old_season_number == 2
    assert added.old_episode_number == 3


# ---------------------------------------------------------------------------
# rematch — integration (mocked sub-methods)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rematch_calls_all_phases_for_tv() -> None:
    """rematch() calls all pipeline phases for a TV show."""
    show = _make_show()
    payload = _make_payload(media_type="tv", preserve_tracking=True)

    session = MagicMock()
    session.refresh = AsyncMock()
    tmdb = MagicMock()

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._fetch_tmdb_details = AsyncMock(return_value=_make_tmdb_data())
    orch._apply_tmdb_metadata = MagicMock()
    orch._snapshot_tracking = AsyncMock(return_value={(1, 1): {}})
    orch._purge_episodes = AsyncMock()
    orch._sync_new_episodes = AsyncMock()
    orch._restore_tracking_and_relink = AsyncMock()

    await orch.rematch(show, payload)

    orch._fetch_tmdb_details.assert_awaited_once()
    orch._apply_tmdb_metadata.assert_called_once()
    orch._snapshot_tracking.assert_awaited_once()
    orch._purge_episodes.assert_awaited_once()
    orch._sync_new_episodes.assert_awaited_once()
    orch._restore_tracking_and_relink.assert_awaited_once()
    session.refresh.assert_awaited_once_with(show)


@pytest.mark.asyncio
async def test_rematch_skips_episode_sync_for_movie() -> None:
    """rematch() skips episode sync and tracking restore for movies."""
    show = _make_show(media_type="movie")
    payload = _make_payload(media_type="movie")

    session = MagicMock()
    session.refresh = AsyncMock()
    tmdb = MagicMock()

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._fetch_tmdb_details = AsyncMock(return_value=_make_tmdb_data())
    orch._apply_tmdb_metadata = MagicMock()
    orch._snapshot_tracking = AsyncMock(return_value={})
    orch._purge_episodes = AsyncMock()
    orch._sync_new_episodes = AsyncMock()
    orch._restore_tracking_and_relink = AsyncMock()

    await orch.rematch(show, payload)

    orch._sync_new_episodes.assert_not_awaited()
    orch._restore_tracking_and_relink.assert_not_awaited()


@pytest.mark.asyncio
async def test_rematch_skips_restore_when_preserve_tracking_false() -> None:
    """rematch() skips _restore_tracking_and_relink when preserve_tracking=False."""
    show = _make_show()
    payload = _make_payload(media_type="tv", preserve_tracking=False)

    session = MagicMock()
    session.refresh = AsyncMock()
    tmdb = MagicMock()

    orch = ShowRematchOrchestrator(session, tmdb)
    orch._fetch_tmdb_details = AsyncMock(return_value=_make_tmdb_data())
    orch._apply_tmdb_metadata = MagicMock()
    orch._snapshot_tracking = AsyncMock(return_value={})
    orch._purge_episodes = AsyncMock()
    orch._sync_new_episodes = AsyncMock()
    orch._restore_tracking_and_relink = AsyncMock()

    await orch.rematch(show, payload)

    orch._sync_new_episodes.assert_awaited_once()
    orch._restore_tracking_and_relink.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_new_episodes_raises_502_on_failure() -> None:
    """_sync_new_episodes wraps TMDBOrchestrator failures as 502."""
    from fastapi import HTTPException

    show = _make_show()
    session = MagicMock()
    tmdb = MagicMock()

    orch = ShowRematchOrchestrator(session, tmdb)

    with patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_tmdb_orch_cls:
        mock_tmdb_orch_cls.return_value.sync_show_episodes = AsyncMock(
            side_effect=RuntimeError("TMDB down")
        )
        with pytest.raises(HTTPException) as exc_info:
            await orch._sync_new_episodes(show)

    assert exc_info.value.status_code == 502
    assert "TMDB episode sync failed" in exc_info.value.detail
