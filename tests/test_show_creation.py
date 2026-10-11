"""Tests for the shared TMDB show-creation service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from jidou.models.show import Show
from jidou.schemas.show_schema import ShowCreate
from jidou.services.show_creation import (
    auto_local_path,
    get_or_create_show_from_tmdb,
    infer_content_type,
)

TMDB_FIELDS = {"tmdb_id": 1396, "title": "Brand New Show", "media_type": "tv"}


def _session(*existing_lookups: Show | None) -> AsyncMock:
    """Session whose successive ``select(Show)`` lookups return *existing_lookups*."""
    session = AsyncMock()
    results = []
    for existing in existing_lookups:
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        results.append(r)
    session.execute = AsyncMock(side_effect=results)

    def _add(obj: Show) -> None:
        obj.id = 5  # as the DB would on flush

    session.add = MagicMock(side_effect=_add)
    return session


@pytest.fixture
def externals():
    """Patch the TMDB/alias collaborators at their source modules."""
    with (
        patch("jidou.orchestrators.tmdb_orchestrator.TMDBOrchestrator") as orch_cls,
        patch(
            "jidou.services.tmdb_mapping.fetch_show_metadata", new=AsyncMock(return_value={})
        ) as fetch,
        patch("jidou.services.tmdb_mapping.build_show_fields", return_value=dict(TMDB_FIELDS)),
        patch(
            "jidou.orchestrators.alias_orchestrator.generate_aliases", new=AsyncMock()
        ) as aliases,
    ):
        orch = orch_cls.return_value
        orch.ensure_episode_group_map = AsyncMock()
        orch.sync_show_episodes = AsyncMock()
        yield {"orch": orch, "fetch": fetch, "aliases": aliases}


async def test_existing_show_is_returned_unchanged_and_not_created(externals) -> None:
    existing = MagicMock(spec=Show)
    existing.id = 9
    existing.tmdb_id = 1396
    session = _session(existing)

    result = await get_or_create_show_from_tmdb(
        session, MagicMock(), ShowCreate(tmdb_id=1396, title="X"), llm=MagicMock()
    )

    assert result.show is existing
    assert result.created is False
    session.add.assert_not_called()
    externals["orch"].ensure_episode_group_map.assert_awaited_once_with(existing)
    externals["orch"].sync_show_episodes.assert_not_called()


async def test_new_tv_show_is_created_synced_committed_then_aliased(externals) -> None:
    session = _session(None)
    order: list[str] = []
    session.commit = AsyncMock(side_effect=lambda: order.append("commit"))
    externals["orch"].sync_show_episodes.side_effect = lambda s: order.append("sync")
    externals["aliases"].side_effect = lambda *a, **k: order.append("aliases")

    result = await get_or_create_show_from_tmdb(
        session, MagicMock(), ShowCreate(tmdb_id=1396, title="Brand New Show"), llm=MagicMock()
    )

    assert result.created is True
    assert result.show.id == 5
    assert result.show.content_type == "tv"
    assert result.show.track_missing_episodes is True
    assert order == ["sync", "commit", "aliases"]  # commit isolates sync from alias failures


async def test_new_movie_skips_episode_sync(externals) -> None:
    session = _session(None)

    with patch(
        "jidou.services.tmdb_mapping.build_show_fields",
        return_value={"tmdb_id": 603, "title": "A Movie", "media_type": "movie"},
    ):
        result = await get_or_create_show_from_tmdb(
            session,
            MagicMock(),
            ShowCreate(tmdb_id=603, title="A Movie", media_type="movie"),
            llm=MagicMock(),
        )

    assert result.created is True
    assert result.show.content_type == "movie"
    externals["orch"].sync_show_episodes.assert_not_called()


async def test_concurrent_insert_race_resolves_to_the_existing_show(externals) -> None:
    winner = MagicMock(spec=Show)
    winner.id = 7
    winner.tmdb_id = 1396
    session = _session(None, winner)  # not there, then there after the failed flush
    session.flush = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("dup")))
    session.rollback = AsyncMock()

    result = await get_or_create_show_from_tmdb(
        session, MagicMock(), ShowCreate(tmdb_id=1396, title="X"), llm=MagicMock()
    )

    assert result.show is winner
    assert result.created is False
    session.rollback.assert_awaited_once()


async def test_details_fetch_failure_falls_back_to_search_card_fields(externals) -> None:
    session = _session(None)
    externals["fetch"].side_effect = RuntimeError("tmdb down")

    result = await get_or_create_show_from_tmdb(
        session,
        MagicMock(),
        ShowCreate(tmdb_id=1396, title="Fallback Title", overview="from the card"),
        llm=MagicMock(),
    )

    assert result.created is True
    assert result.show.title == "Fallback Title"
    assert result.show.overview == "from the card"


async def test_alias_generation_failure_does_not_undo_creation(externals) -> None:
    session = _session(None)
    externals["aliases"].side_effect = RuntimeError("llm down")

    result = await get_or_create_show_from_tmdb(
        session, MagicMock(), ShowCreate(tmdb_id=1396, title="X"), llm=MagicMock()
    )

    assert result.created is True
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (ShowCreate(tmdb_id=1, title="m", media_type="movie"), "movie"),
        (ShowCreate(tmdb_id=1, title="a", genre_ids=[16], original_language="ja"), "anime"),
        (ShowCreate(tmdb_id=1, title="a", genres=[{"id": 16}], origin_country=["JP"]), "anime"),
        (ShowCreate(tmdb_id=1, title="cartoon", genre_ids=[16], original_language="en"), "tv"),
        (ShowCreate(tmdb_id=1, title="drama", genre_ids=[18]), "tv"),
    ],
)
def test_infer_content_type(payload: ShowCreate, expected: str) -> None:
    assert infer_content_type(payload) == expected


def test_auto_local_path_uses_the_configured_root_for_the_content_type() -> None:
    with patch("jidou.config.settings") as s:
        s.local_tv_path = "/media/tv"
        s.local_anime_path = "/media/anime"
        s.local_movie_path = "/media/movies"

        assert auto_local_path("anime", "Some_Show").startswith("/media/anime")
