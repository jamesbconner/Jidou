"""Characterization tests: what show creation persists for a given ShowCreate.

These pin the exact ``Show`` attributes the orchestrator builds, so the
``ShowSeed`` refactor (DF-16) can be proven behaviour-preserving.
"""

import dataclasses
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.show import Show
from jidou.orchestrators.show_creation_orchestrator import ShowSeed, get_or_create_show_from_tmdb
from jidou.schemas.show_schema import ShowCreate

_ORCH = "jidou.orchestrators.show_creation_orchestrator"

# Every ShowCreate field populated with a non-default value.
FULL_PAYLOAD: dict[str, Any] = {
    "tmdb_id": 4242,
    "title": "Full Card",
    "media_type": "tv",
    "overview": "an overview",
    "poster_path": "/p.jpg",
    "backdrop_path": "/b.jpg",
    "vote_average": 8.25,
    "vote_count": 123,
    "release_date": "2020-01-02",
    "original_language": "ja",
    "genres": [{"id": 16, "name": "Animation"}],
    "genre_ids": [16, 18],
    "origin_country": ["JP"],
    "last_air_date": "2021-03-04",
    "last_episode_to_air": {"id": 1, "episode_number": 12},
    "next_episode_to_air": {"id": 2, "episode_number": 13},
    "homepage": "https://example.invalid/show",
    "external_ids": {"imdb_id": "tt1"},
    "episode_groups": [{"id": "g1"}],
    "status": "Returning Series",
    "in_production": True,
    "number_of_seasons": 2,
    "number_of_episodes": 24,
    "networks": [{"id": 9, "name": "Net"}],
    "show_type": "Scripted",
    "runtime": 24,
    "tagline": "a tagline",
    "content_type": "tv",
    "sys_name": "Custom Sys",
    "local_path": "/custom/path",
    "adult": False,
}
# Fields applied explicitly by the orchestrator rather than via the fallback dict.
NOT_IN_FALLBACK = {"genre_ids", "sys_name", "content_type", "local_path"}


def test_full_payload_covers_every_show_create_field() -> None:
    assert set(FULL_PAYLOAD) == set(ShowCreate.model_fields)


def _session() -> AsyncMock:
    session = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=r)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", 5))
    return session


@pytest.fixture
def externals():
    with (
        patch(f"{_ORCH}.TMDBOrchestrator"),
        patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as orch_cls,
        patch(f"{_ORCH}.fetch_show_metadata", new=AsyncMock(return_value={"name": "x"})) as fetch,
        patch("jidou.orchestrators._show_provisioning.generate_aliases", new=AsyncMock()),
        patch(
            f"{_ORCH}.auto_local_path_for",
            side_effect=lambda show, **roots: f"/auto/{show.content_type}/{show.sys_name}",
        ) as auto,
    ):
        orch_cls.return_value.sync_show_episodes = AsyncMock()
        yield {"fetch": fetch, "auto": auto}


async def _create(payload: ShowCreate) -> Show:
    result = await get_or_create_show_from_tmdb(
        _session(), MagicMock(), ShowSeed.from_create(payload), llm=MagicMock()
    )
    assert result.created is True
    return result.show


async def test_fallback_persists_every_search_card_field(externals) -> None:
    externals["fetch"].side_effect = RuntimeError("tmdb down")

    show = await _create(ShowCreate(**FULL_PAYLOAD))

    checked = 0
    for name, value in FULL_PAYLOAD.items():
        if name not in NOT_IN_FALLBACK:
            assert getattr(show, name) == value, name
            checked += 1
    assert checked == len(FULL_PAYLOAD) - len(NOT_IN_FALLBACK)
    assert show.sys_name == "Custom Sys"
    assert show.content_type == "tv"
    assert show.local_path == "/custom/path"
    assert show.cached is False
    assert show.track_missing_episodes is True
    externals["auto"].assert_not_called()


async def test_fallback_with_defaults_derives_and_keeps_none_fields(externals) -> None:
    externals["fetch"].side_effect = RuntimeError("tmdb down")

    show = await _create(ShowCreate(tmdb_id=7, title="Plain Show!"))

    assert (show.tmdb_id, show.title, show.media_type) == (7, "Plain Show!", "tv")
    assert show.vote_count == 0
    for name in ("overview", "poster_path", "vote_average", "genres", "adult", "runtime"):
        assert getattr(show, name) is None, name
    assert show.content_type == "tv"
    assert show.sys_name == "Plain Show!"
    assert show.local_path == "/auto/tv/Plain Show!"
    externals["auto"].assert_called_once()
    seen = externals["auto"].call_args.args[0]
    assert (seen.content_type, seen.sys_name) == ("tv", "Plain Show!")


async def test_fallback_infers_anime_from_genre_ids_and_derives_path(externals) -> None:
    externals["fetch"].side_effect = RuntimeError("tmdb down")

    show = await _create(
        ShowCreate(tmdb_id=8, title="Anime X", genre_ids=[16], original_language="ja")
    )

    assert show.content_type == "anime"
    assert show.local_path == f"/auto/anime/{show.sys_name}"
    # genre_ids is not a Show column and must not leak into the model.
    assert not hasattr(show, "genre_ids")


async def test_success_path_uses_built_fields_and_caller_derived_names(externals) -> None:
    built = {"tmdb_id": 9, "title": "Fetched", "media_type": "tv", "sys_name": "ignored"}
    with patch(f"{_ORCH}.build_show_fields", return_value=built) as build:
        show = await _create(ShowCreate(tmdb_id=9, title="Card Title", overview="card only"))

    build.assert_called_once_with({"name": "x"}, 9, "tv", title_fallback="Card Title")
    assert externals["fetch"].await_args.args[1:] == (9, "tv")
    assert show.title == "Fetched"
    assert show.overview is None  # card-only fields are not merged on success
    assert show.sys_name == "Card Title"  # fetched sys_name dropped, caller's used
    assert show.content_type == "tv"


async def test_success_path_honours_explicit_overrides(externals) -> None:
    built = {"tmdb_id": 10, "title": "T", "media_type": "movie"}
    with patch(f"{_ORCH}.build_show_fields", return_value=built):
        show = await _create(
            ShowCreate(
                tmdb_id=10,
                title="T",
                media_type="movie",
                content_type="anime",
                sys_name="Mine",
                local_path="/mine",
            )
        )

    assert (show.content_type, show.sys_name, show.local_path) == ("anime", "Mine", "/mine")
    assert show.media_type == "movie"


def test_show_seed_covers_every_show_create_field() -> None:
    """No ShowCreate field may be silently dropped by the seed."""
    seed_fields = {f.name for f in dataclasses.fields(ShowSeed)}
    assert seed_fields == set(ShowCreate.model_fields)
    assert len(seed_fields) >= 30


def test_show_seed_round_trips_every_field_and_is_frozen() -> None:
    seed = ShowSeed.from_create(ShowCreate(**FULL_PAYLOAD))

    assert dataclasses.asdict(seed) == FULL_PAYLOAD
    with pytest.raises(dataclasses.FrozenInstanceError):
        seed.title = "other"  # type: ignore[misc]


def test_search_card_fields_are_exactly_the_old_dump_minus_explicit_fields() -> None:
    fields = ShowSeed.from_create(ShowCreate(**FULL_PAYLOAD)).search_card_fields()

    assert set(fields) == set(FULL_PAYLOAD) - NOT_IN_FALLBACK
    assert fields == {k: v for k, v in FULL_PAYLOAD.items() if k not in NOT_IN_FALLBACK}


def test_from_create_does_not_alias_the_request_payload() -> None:
    payload = ShowCreate(**FULL_PAYLOAD)
    seed = ShowSeed.from_create(payload)

    assert seed.genres == payload.genres
    assert seed.genres is not payload.genres
