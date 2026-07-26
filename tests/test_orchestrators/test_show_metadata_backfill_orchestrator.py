"""Tests for ShowMetadataBackfillOrchestrator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.orchestrators.show_metadata_backfill_orchestrator import (
    ShowMetadataBackfillOrchestrator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_show(
    *,
    show_id: int = 1,
    tmdb_id: int = 100,
    title: str = "Test Show",
    media_type: str = "tv",
    genres: object = None,
    sys_name: str = "Test Show",
) -> MagicMock:
    s = MagicMock()
    s.id = show_id
    s.tmdb_id = tmdb_id
    s.title = title
    s.media_type = media_type
    s.genres = genres
    s.sys_name = sys_name
    return s


def _session_with_shows(shows: list[MagicMock]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = shows
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_tmdb(details: dict[str, object] | None = None) -> AsyncMock:
    tmdb = AsyncMock()
    tmdb.get_details = AsyncMock(return_value=details or {})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})
    return tmdb


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_shows_that_already_have_genres() -> None:
    """A show with a non-empty genres list is not a backfill candidate."""
    with_genres = _make_show(show_id=1, tmdb_id=100, genres=[{"id": 16, "name": "Animation"}])
    without_genres = _make_show(show_id=2, tmdb_id=200, genres=None)
    session = _session_with_shows([with_genres, without_genres])
    tmdb = _make_tmdb()

    result = await ShowMetadataBackfillOrchestrator(session, tmdb).run()

    assert result.shows_checked == 1
    assert result.updated_titles == ["Test Show"]
    tmdb.get_details.assert_awaited_once_with(200, media_type="tv")


@pytest.mark.asyncio
async def test_skips_shows_with_a_legitimately_empty_genre_list() -> None:
    """A show TMDB genuinely has no genres for (genres == []) is not re-selected.

    Regression test: an earlier version of the filter matched any falsy
    genres value, including []. Since a successful backfill sets genres to
    [] for a show TMDB reports zero genres for, that show would have been
    re-selected as a candidate forever, never converging.
    """
    empty_list = _make_show(show_id=1, genres=[])
    null_genres = _make_show(show_id=2, genres=None)
    session = _session_with_shows([empty_list, null_genres])
    tmdb = _make_tmdb()

    result = await ShowMetadataBackfillOrchestrator(session, tmdb).run()

    assert result.shows_checked == 1
    tmdb.get_details.assert_awaited_once_with(100, media_type="tv")


# ---------------------------------------------------------------------------
# Applying fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfilling_a_zero_genre_show_makes_it_converge_on_a_second_run() -> None:
    """A show TMDB has zero genres for is not a candidate again after one run."""
    show = _make_show(genres=None)
    session = _session_with_shows([show])
    tmdb = _make_tmdb({"genres": []})

    first = await ShowMetadataBackfillOrchestrator(session, tmdb).run()
    assert first.shows_checked == 1
    assert show.genres == []

    tmdb.get_details.reset_mock()
    second = await ShowMetadataBackfillOrchestrator(session, tmdb).run()

    assert second.shows_checked == 0
    tmdb.get_details.assert_not_awaited()


@pytest.mark.asyncio
async def test_applies_fetched_genres_and_commits() -> None:
    """A successful fetch sets genres (and other TMDB fields) and commits."""
    show = _make_show(genres=None)
    session = _session_with_shows([show])
    tmdb = _make_tmdb({"name": "Test Show", "genres": [{"id": 35, "name": "Comedy"}]})

    result = await ShowMetadataBackfillOrchestrator(session, tmdb).run()

    assert show.genres == [{"id": 35, "name": "Comedy"}]
    assert result.shows_updated == 1
    assert result.shows_failed == 0
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_never_overwrites_sys_name() -> None:
    """sys_name must stay untouched -- it may already back a populated local folder."""
    show = _make_show(genres=None, sys_name="My Custom Folder Name")
    session = _session_with_shows([show])
    tmdb = _make_tmdb({"name": "A Totally Different Title"})

    await ShowMetadataBackfillOrchestrator(session, tmdb).run()

    assert show.sys_name == "My Custom Folder Name"


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_does_not_mutate_or_commit() -> None:
    """dry_run identifies candidates without writing anything."""
    show = _make_show(genres=None)
    session = _session_with_shows([show])
    tmdb = _make_tmdb({"genres": [{"id": 16, "name": "Animation"}]})

    result = await ShowMetadataBackfillOrchestrator(session, tmdb).run(dry_run=True)

    assert show.genres is None  # untouched
    assert result.shows_updated == 1
    session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_failure_for_one_show_does_not_abort_the_batch() -> None:
    """A TMDB fetch failure is recorded and the batch continues."""
    failing = _make_show(show_id=1, tmdb_id=100, title="Failing Show", genres=None)
    ok = _make_show(show_id=2, tmdb_id=200, title="OK Show", genres=None)
    session = _session_with_shows([failing, ok])

    tmdb = _make_tmdb({"genres": [{"id": 16, "name": "Animation"}]})

    async def _get_details(tmdb_id: int, media_type: str) -> dict[str, object]:
        if tmdb_id == 100:
            raise RuntimeError("TMDB unavailable")
        return {"genres": [{"id": 16, "name": "Animation"}]}

    tmdb.get_details = AsyncMock(side_effect=_get_details)

    result = await ShowMetadataBackfillOrchestrator(session, tmdb).run()

    assert result.shows_checked == 2
    assert result.shows_failed == 1
    assert result.failed_titles == ["Failing Show"]
    assert result.shows_updated == 1
    assert result.updated_titles == ["OK Show"]


@pytest.mark.asyncio
async def test_save_failure_rolls_back_and_continues() -> None:
    """A DB failure while saving one show is rolled back without aborting the batch."""
    show = _make_show(genres=None)
    session = _session_with_shows([show])
    session.flush = AsyncMock(side_effect=RuntimeError("db down"))
    tmdb = _make_tmdb({"genres": [{"id": 16, "name": "Animation"}]})

    result = await ShowMetadataBackfillOrchestrator(session, tmdb).run()

    assert result.shows_failed == 1
    assert result.shows_updated == 0
    session.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reports_progress_per_candidate() -> None:
    """on_progress is invoked once per candidate with the running count and total."""
    shows = [_make_show(show_id=i, tmdb_id=i, title=f"Show {i}", genres=None) for i in range(1, 4)]
    session = _session_with_shows(shows)
    tmdb = _make_tmdb({"genres": []})

    calls: list[tuple[int, int, str]] = []

    async def on_progress(current: int, total: int, message: str) -> None:
        calls.append((current, total, message))

    await ShowMetadataBackfillOrchestrator(session, tmdb).run(on_progress=on_progress)

    assert calls == [
        (1, 3, "Backfilling Show 1"),
        (2, 3, "Backfilling Show 2"),
        (3, 3, "Backfilling Show 3"),
    ]
