"""Tests for ManualMatchOrchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from jidou.models.downloaded_file import FileStatus, MatchedBy
from jidou.orchestrators.manual_match_orchestrator import ManualMatchOrchestrator
from jidou.schemas.file_schema import FileMatchRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(
    *,
    file_id: int = 1,
    status: str = FileStatus.UNMATCHED,
    show_id: int | None = None,
    episode_id: int | None = None,
    parsed_season: int | None = None,
    parsed_episode: int | None = None,
    original_filename: str = "show.s01e01.mkv",
    local_path: str | None = None,
) -> MagicMock:
    f = MagicMock()
    f.id = file_id
    f.status = status
    f.show_id = show_id
    f.episode_id = episode_id
    f.matched_by = None
    f.error_message = None
    f.parsed_season = parsed_season
    f.parsed_episode = parsed_episode
    f.original_filename = original_filename
    f.local_path = local_path
    return f


def _make_show(
    *,
    show_id: int = 5,
    title: str = "Test Show",
    local_path: str | None = "/media/test",
    tmdb_id: int = 100,
    media_type: str = "tv",
) -> MagicMock:
    s = MagicMock()
    s.id = show_id
    s.title = title
    s.local_path = local_path
    s.tmdb_id = tmdb_id
    s.media_type = media_type
    return s


def _make_session(execute_results: list) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute_results)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


def _exec_result(scalar: object = None, count: int | None = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    if count is not None:
        r.scalar.return_value = count
    return r


def _payload(**kwargs: object) -> FileMatchRequest:
    return FileMatchRequest(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Reset path
# ---------------------------------------------------------------------------


async def test_match_no_show_id_or_tmdb_id_resets_to_downloaded() -> None:
    """No show_id/tmdb_id resets the file to DOWNLOADED and clears match fields."""
    f = _make_file(status=FileStatus.UNMATCHED, show_id=10)
    session = _make_session([])

    result = await ManualMatchOrchestrator(session).match(f, _payload())

    assert result is f
    assert f.status == FileStatus.DOWNLOADED
    assert f.show_id is None
    assert f.episode_id is None
    assert f.matched_by is None
    session.commit.assert_awaited_once()


async def test_match_routed_file_resets_to_downloaded() -> None:
    """A ROUTED file with an empty payload is also reset to DOWNLOADED."""
    f = _make_file(status=FileStatus.ROUTED, show_id=10)
    session = _make_session([])

    await ManualMatchOrchestrator(session).match(f, _payload())

    assert f.status == FileStatus.DOWNLOADED
    assert f.show_id is None


# ---------------------------------------------------------------------------
# show_id path
# ---------------------------------------------------------------------------


async def test_match_show_id_not_found_raises_404() -> None:
    """A nonexistent show_id raises 404 'Show not found'."""
    f = _make_file()
    session = _make_session([_exec_result(scalar=None)])

    with pytest.raises(HTTPException) as exc_info:
        await ManualMatchOrchestrator(session).match(f, _payload(show_id=9999))

    assert exc_info.value.status_code == 404
    assert "Show not found" in exc_info.value.detail


async def test_match_show_with_no_local_path_raises_422() -> None:
    """A resolved show with local_path=None raises 422."""
    f = _make_file()
    show = _make_show(local_path=None)
    session = _make_session([_exec_result(scalar=show)])

    with pytest.raises(HTTPException) as exc_info:
        await ManualMatchOrchestrator(session).match(f, _payload(show_id=show.id))

    assert exc_info.value.status_code == 422
    assert "local_path" in exc_info.value.detail


async def test_match_show_id_sets_matched_status() -> None:
    """A valid show_id transitions the file to MATCHED and extracts S/E via heuristic."""
    f = _make_file(parsed_season=None, parsed_episode=None)
    show = _make_show()
    # show lookup, then episode-resolution lookup (no episode found in DB)
    session = _make_session([_exec_result(scalar=show), _exec_result(scalar=None)])

    result = await ManualMatchOrchestrator(session).match(f, _payload(show_id=show.id))

    assert result is f
    assert f.status == FileStatus.MATCHED
    assert f.show_id == show.id
    assert f.matched_by == MatchedBy.MANUAL
    assert f.parsed_season == 1  # extracted from "show.s01e01.mkv"
    assert f.parsed_episode == 1


async def test_match_flushes_before_commit() -> None:
    """The final assignment flushes before committing so DB state is visible."""
    f = _make_file(parsed_season=None, parsed_episode=None)
    show = _make_show()
    session = _make_session([_exec_result(scalar=show), _exec_result(scalar=None)])
    call_order: list[str] = []
    session.flush = AsyncMock(side_effect=lambda: call_order.append("flush"))
    session.commit = AsyncMock(side_effect=lambda: call_order.append("commit"))

    await ManualMatchOrchestrator(session).match(f, _payload(show_id=show.id))

    assert call_order == ["flush", "commit"]


# ---------------------------------------------------------------------------
# Stale-episode-tracking cleanup
# ---------------------------------------------------------------------------


async def test_match_clears_old_episode_tracking_on_show_change() -> None:
    """Moving a file to a different show clears stale tracking on the old episode."""
    f = _make_file(status=FileStatus.ROUTED, show_id=5, episode_id=10, parsed_season=None)
    show = _make_show(show_id=7, title="New Show", local_path="/media/new-show")
    old_ep = MagicMock()
    old_ep.id = 10
    old_ep.file_tracked = True
    old_ep.tracked_filename = "old.s01e01.mkv"
    old_ep.tracked_source = "match"

    session = _make_session(
        [
            _exec_result(scalar=show),  # show lookup
            _exec_result(scalar=None),  # heuristic episode lookup (miss)
            _exec_result(count=0),  # count of other files on old episode
            _exec_result(scalar=old_ep),  # old episode lookup
        ]
    )

    await ManualMatchOrchestrator(session).match(f, _payload(show_id=show.id))

    assert old_ep.file_tracked is False
    assert old_ep.tracked_filename is None
    assert old_ep.tracked_source is None


async def test_match_clears_old_episode_tracking_same_show() -> None:
    """Moving a file between episodes on the SAME show also clears the old tracking."""
    f = _make_file(status=FileStatus.ROUTED, show_id=5, episode_id=10, parsed_season=None)
    show = _make_show(show_id=5, title="Same Show", local_path="/media/same-show")
    old_ep = MagicMock()
    old_ep.id = 10
    old_ep.file_tracked = True
    old_ep.tracked_filename = "old.s01e01.mkv"
    old_ep.tracked_source = "match"

    session = _make_session(
        [
            _exec_result(scalar=show),
            _exec_result(scalar=None),
            _exec_result(count=0),
            _exec_result(scalar=old_ep),
        ]
    )

    await ManualMatchOrchestrator(session).match(f, _payload(show_id=show.id))

    assert old_ep.file_tracked is False
    assert old_ep.tracked_filename is None
    assert old_ep.tracked_source is None


async def test_match_does_not_clear_tracking_when_episode_unchanged() -> None:
    """Stale-episode clear is skipped when the heuristic re-links the same episode."""
    f = _make_file(
        status=FileStatus.ROUTED,
        show_id=5,
        episode_id=10,
        parsed_season=None,
        local_path=None,
        original_filename="show.s01e01.mkv",
    )
    show = _make_show(show_id=5, title="Same Show", local_path="/media/same-show")
    same_ep = MagicMock()
    same_ep.id = 10
    same_ep.file_tracked = True
    same_ep.tracked_filename = "show.s01e01.mkv"
    same_ep.tracked_source = "match"

    session = _make_session(
        [
            _exec_result(scalar=show),
            _exec_result(scalar=same_ep),  # heuristic resolves back to the SAME episode
            _exec_result(),  # orphan-dismiss delete (result ignored)
        ]
    )

    await ManualMatchOrchestrator(session).match(f, _payload(show_id=show.id))

    # Tracking must NOT be cleared -- the episode didn't change.
    assert same_ep.file_tracked is True
    assert same_ep.tracked_filename == "show.s01e01.mkv"


# ---------------------------------------------------------------------------
# tmdb_id path -- on-demand show creation
# ---------------------------------------------------------------------------


def _tmdb_data(**overrides: object) -> dict:
    data: dict[str, object] = {
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
    data.update(overrides)
    return data


async def test_match_tmdb_id_without_local_path_raises_422() -> None:
    """Creating a show via tmdb_id without local_path raises 422."""
    f = _make_file()
    session = _make_session([_exec_result(scalar=None)])  # tmdb_id lookup miss

    with pytest.raises(HTTPException) as exc_info:
        await ManualMatchOrchestrator(session).match(f, _payload(tmdb_id=1396))

    assert exc_info.value.status_code == 422
    assert "local_path" in exc_info.value.detail


async def test_match_tmdb_id_lookup_failure_raises_404() -> None:
    """A TMDB fetch failure while creating a show raises 404."""
    f = _make_file()
    session = _make_session([_exec_result(scalar=None)])

    with patch(
        "jidou.orchestrators.manual_match_orchestrator.TMDBService", autospec=True
    ) as mock_tmdb:
        mock_tmdb.return_value.get_details = AsyncMock(side_effect=RuntimeError("network error"))

        with pytest.raises(HTTPException) as exc_info:
            await ManualMatchOrchestrator(session).match(
                f, _payload(tmdb_id=1396, local_path="/media/tv/Breaking Bad", content_type="tv")
            )

    assert exc_info.value.status_code == 404
    assert "TMDB lookup failed" in exc_info.value.detail


async def test_match_tmdb_id_creates_show_and_matches() -> None:
    """A tmdb_id with local_path creates a show and marks the file MATCHED."""
    f = _make_file(parsed_season=None, parsed_episode=None)
    created_show_id = 42

    def _add(obj: object) -> None:
        obj.id = created_show_id  # type: ignore[attr-defined]
        obj.local_path = "/media/tv/Breaking Bad"  # type: ignore[attr-defined]

    session = _make_session(
        [
            _exec_result(scalar=None),  # tmdb_id lookup miss -> create
            _exec_result(scalar=None),  # heuristic episode lookup miss -> orphan not dismissed
        ]
    )
    session.add = MagicMock(side_effect=_add)

    with patch(
        "jidou.orchestrators.manual_match_orchestrator.TMDBService", autospec=True
    ) as mock_tmdb:
        mock_tmdb.return_value.get_details.return_value = _tmdb_data()
        mock_tmdb.return_value.get_external_ids.return_value = {}
        mock_tmdb.return_value.get_episode_groups.return_value = {}
        mock_tmdb.return_value.get_show_seasons = AsyncMock(return_value={"seasons": []})
        mock_tmdb.return_value.get_alternative_titles = AsyncMock(return_value={"results": []})

        result = await ManualMatchOrchestrator(session).match(
            f, _payload(tmdb_id=1396, local_path="/media/tv/Breaking Bad", content_type="tv")
        )

    assert result is f
    assert f.status == FileStatus.MATCHED
    assert f.matched_by == MatchedBy.MANUAL
    assert f.parsed_season == 1
    assert f.parsed_episode == 1


async def test_match_tmdb_id_creates_show_with_adult_flag() -> None:
    """The Show created via manual match carries TMDB's adult flag."""
    f = _make_file(parsed_season=None, parsed_episode=None)
    captured: dict[str, object] = {}

    def _add(obj: object) -> None:
        obj.id = 43  # type: ignore[attr-defined]
        obj.local_path = "/media/tv/Adult Show"  # type: ignore[attr-defined]
        captured["adult"] = obj.adult  # type: ignore[attr-defined]

    session = _make_session([_exec_result(scalar=None), _exec_result(scalar=None)])
    session.add = MagicMock(side_effect=_add)

    with patch(
        "jidou.orchestrators.manual_match_orchestrator.TMDBService", autospec=True
    ) as mock_tmdb:
        mock_tmdb.return_value.get_details.return_value = _tmdb_data(
            id=1397, name="Adult Show", adult=True
        )
        mock_tmdb.return_value.get_external_ids.return_value = {}
        mock_tmdb.return_value.get_episode_groups.return_value = {}
        mock_tmdb.return_value.get_show_seasons = AsyncMock(return_value={"seasons": []})
        mock_tmdb.return_value.get_alternative_titles = AsyncMock(return_value={"results": []})

        await ManualMatchOrchestrator(session).match(
            f, _payload(tmdb_id=1397, local_path="/media/tv/Adult Show", content_type="tv")
        )

    assert captured["adult"] is True


async def test_match_tmdb_id_commits_after_sync_before_alias_generation() -> None:
    """The show and any synced episodes commit before alias generation runs.

    Regression test for a Cursor Bugbot finding on PR-04: sync_show_episodes
    only flushes (the caller owns the commit boundary). Without an explicit
    commit right after a successful sync, a subsequent DB-level failure during
    alias generation would roll back the sync's flushed episodes too, even
    though sync itself succeeded -- both steps are meant to be independently
    best-effort. Asserts the actual call order rather than just the return
    value, since a mocked session can't demonstrate data loss directly.
    """
    f = _make_file(parsed_season=None, parsed_episode=None)
    call_order: list[str] = []

    def _add(obj: object) -> None:
        obj.id = 44  # type: ignore[attr-defined]
        obj.local_path = "/media/tv/Commit Order Show"  # type: ignore[attr-defined]

    session = _make_session([_exec_result(scalar=None), _exec_result(scalar=None)])
    session.add = MagicMock(side_effect=_add)
    session.commit = AsyncMock(side_effect=lambda: call_order.append("commit"))

    async def _get_show_seasons(*_args: object, **_kwargs: object) -> dict[str, list[object]]:
        call_order.append("sync")
        return {"seasons": []}

    async def _generate_aliases(*_args: object, **_kwargs: object) -> None:
        call_order.append("alias")

    with (
        patch(
            "jidou.orchestrators.manual_match_orchestrator.TMDBService", autospec=True
        ) as mock_tmdb,
        patch(
            "jidou.orchestrators.alias_orchestrator.generate_aliases",
            new_callable=AsyncMock,
            side_effect=_generate_aliases,
        ),
    ):
        mock_tmdb.return_value.get_details.return_value = _tmdb_data(id=1398, name="Commit Show")
        mock_tmdb.return_value.get_external_ids.return_value = {}
        mock_tmdb.return_value.get_episode_groups.return_value = {}
        mock_tmdb.return_value.get_show_seasons = AsyncMock(side_effect=_get_show_seasons)

        await ManualMatchOrchestrator(session).match(
            f,
            _payload(tmdb_id=1398, local_path="/media/tv/Commit Order Show", content_type="tv"),
        )

    # A commit must land between sync and alias generation -- there's a second
    # commit later for the file-status update, so check relative order only.
    assert call_order[:3] == ["sync", "commit", "alias"]


async def test_match_tmdb_id_episode_sync_sqlalchemy_error_propagates() -> None:
    """A SQLAlchemyError during episode sync must propagate, not be swallowed.

    A DB failure during sync's internal flush leaves the session's
    transaction in a broken state; silently continuing (as the generic
    Exception branch does) would let the route issue further queries against
    a dead transaction. Mirrors the same guard already tested for POST /shows
    (test_create_show_db_error_during_sync_propagates in test_shows_routes.py).
    """
    from sqlalchemy.exc import OperationalError

    f = _make_file(parsed_season=None, parsed_episode=None)

    def _add(obj: object) -> None:
        obj.id = 45  # type: ignore[attr-defined]
        obj.local_path = "/media/tv/DB Fail Show"  # type: ignore[attr-defined]

    session = _make_session([_exec_result(scalar=None)])
    session.add = MagicMock(side_effect=_add)

    with (
        patch(
            "jidou.orchestrators.manual_match_orchestrator.TMDBService", autospec=True
        ) as mock_tmdb,
        patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls,
    ):
        mock_tmdb.return_value.get_details.return_value = _tmdb_data(id=1399, name="DB Fail Show")
        mock_tmdb.return_value.get_external_ids.return_value = {}
        mock_tmdb.return_value.get_episode_groups.return_value = {}
        mock_orch = MagicMock()
        mock_orch.sync_show_episodes = AsyncMock(
            side_effect=OperationalError("conn lost", None, None)
        )
        mock_orch_cls.return_value = mock_orch

        with pytest.raises(OperationalError):
            await ManualMatchOrchestrator(session).match(
                f,
                _payload(tmdb_id=1399, local_path="/media/tv/DB Fail Show", content_type="tv"),
            )

    # Commit must NOT have run -- the transaction is broken and the caller
    # (the route) is responsible for rolling back, not committing a dead one.
    session.commit.assert_not_awaited()


async def test_match_tmdb_id_episode_sync_generic_exception_is_best_effort() -> None:
    """A non-SQLAlchemyError during episode sync is caught, logged, and does not abort."""

    def _add(obj: object) -> None:
        obj.id = 46  # type: ignore[attr-defined]
        obj.local_path = "/media/tv/Sync Fail Show"  # type: ignore[attr-defined]

    session = _make_session([_exec_result(scalar=None), _exec_result(scalar=None)])
    session.add = MagicMock(side_effect=_add)

    with (
        patch(
            "jidou.orchestrators.manual_match_orchestrator.TMDBService", autospec=True
        ) as mock_tmdb,
        patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as mock_orch_cls,
        patch(
            "jidou.orchestrators.alias_orchestrator.generate_aliases",
            new_callable=AsyncMock,
        ),
    ):
        mock_tmdb.return_value.get_details.return_value = _tmdb_data(id=1400, name="Sync Fail Show")
        mock_tmdb.return_value.get_external_ids.return_value = {}
        mock_tmdb.return_value.get_episode_groups.return_value = {}
        mock_orch = MagicMock()
        mock_orch.sync_show_episodes = AsyncMock(side_effect=RuntimeError("transient TMDB hiccup"))
        mock_orch_cls.return_value = mock_orch

        result_show = await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(
            _payload(tmdb_id=1400, local_path="/media/tv/Sync Fail Show", content_type="tv")
        )

    # Sync failure was swallowed -- show creation still completes and commits.
    assert result_show.id == 46
    session.commit.assert_awaited_once()


async def test_match_existing_show_by_tmdb_id_fills_missing_fields_only() -> None:
    """An existing show found by tmdb_id gets local_path/content_type filled only if unset."""
    f = _make_file(parsed_season=None, parsed_episode=None)
    show = _make_show(local_path="/already/set", tmdb_id=1396)
    show.content_type = "tv"

    session = _make_session(
        [
            _exec_result(scalar=show),  # tmdb_id lookup hit
            _exec_result(scalar=None),  # heuristic episode lookup miss
        ]
    )

    await ManualMatchOrchestrator(session).match(
        f, _payload(tmdb_id=1396, local_path="/should/not/overwrite", content_type="movie")
    )

    # Existing values must not be overwritten by the caller-supplied payload.
    assert show.local_path == "/already/set"
    assert show.content_type == "tv"
