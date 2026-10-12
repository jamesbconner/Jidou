"""DF-10 (D16): one ``local_path`` auto-population rule for every show flow.

``auto_local_path_for`` returns ``None`` unless the show's ``content_type`` is
set or its ``media_type`` is ``"movie"``. Parse, path import and show creation
all go through it. Expected paths are built with ``PurePosixPath`` because the
helper always produces container-side (Linux) paths, on every host OS.
"""

from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.show import ContentType
from jidou.orchestrators.show_creation_orchestrator import ShowSeed, get_or_create_show_from_tmdb
from jidou.schemas.show_schema import ShowCreate
from jidou.services.path_parser import ParsedPathEntry

_TV = "/data/media/tv"
_ANIME = "/data/media/anime"
_MOVIE = "/data/media/movies"
_ROOTS = {"tv": _TV, "anime": _ANIME, "movie": _MOVIE}


def _under(root: str, name: str) -> str:
    return str(PurePosixPath(root) / name)


def _show(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "content_type": None,
        "media_type": "tv",
        "sys_name": "Some Show",
        "title": "Some Show",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _helper() -> Any:
    # Imported per test so the rest of this module still runs before the helper exists.
    from jidou.services.path_resolution import auto_local_path_for

    return auto_local_path_for


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("show_kw", "expected"),
    [
        ({"content_type": "anime"}, _under(_ANIME, "Some Show")),
        ({"content_type": ContentType.ANIME}, _under(_ANIME, "Some Show")),
        ({"content_type": "tv"}, _under(_TV, "Some Show")),
        ({"content_type": "tv", "media_type": "movie"}, _under(_TV, "Some Show")),
        ({"content_type": "movie"}, str(PurePosixPath(_MOVIE))),
        ({"content_type": "anime", "media_type": "movie"}, _under(_ANIME, "Some Show")),
        ({"content_type": "documentary"}, _under(_TV, "Some Show")),
        ({"content_type": None, "media_type": "movie"}, str(PurePosixPath(_MOVIE))),
        ({"content_type": None, "media_type": "tv"}, None),
        ({"content_type": None, "media_type": None}, None),
        ({"content_type": None, "media_type": "anime"}, None),
        ({"content_type": "", "media_type": "tv"}, None),
    ],
)
def test_auto_local_path_rule(show_kw: dict[str, Any], expected: str | None) -> None:
    """Only a set content_type, or a movie media_type, yields a path."""
    assert _helper()(_show(**show_kw), **_ROOTS) == expected


def test_auto_local_path_falls_back_to_sanitised_title_without_sys_name() -> None:
    show = _show(content_type="anime", sys_name=None, title="Re:Zero")
    assert _helper()(show, **_ROOTS) == _under(_ANIME, "Re Zero")


def test_auto_local_path_uses_the_given_roots_untouched() -> None:
    show = _show(content_type="tv")
    assert _helper()(show, tv="/srv/tv", anime="/srv/anime", movie="/srv/movies") == _under(
        "/srv/tv", "Some Show"
    )


# ---------------------------------------------------------------------------
# Path import: content_type is set on every show it creates, so its paths are
# unchanged (characterization); only a pre-existing show with no content_type
# and a non-movie media_type changes (it is no longer guessed into TV).
# ---------------------------------------------------------------------------


def _entry() -> ParsedPathEntry:
    return ParsedPathEntry(
        raw_path=r"Z:\host\Some Show\Season 01\ep.mkv",
        show_dir="Some Show",
        show_root=r"Z:\host\Some Show",
        season=1,
        episode=1,
        is_absolute=False,
    )


async def _path_import(show: MagicMock, action: str) -> MagicMock:
    from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator

    episode = MagicMock(
        id=10, show_id=1, season_number=1, episode_number=1, absolute_episode_number=None
    )
    episode.file_tracked = False
    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute.return_value = ep_result
    orch = PathImportOrchestrator(
        session,
        AsyncMock(),
        local_tv_path=_TV,
        local_anime_path=_ANIME,
        local_movie_path=_MOVIE,
    )
    with patch.object(orch, "_resolve_show", AsyncMock(return_value=(show, action))):
        await orch.run([_entry()])
    return show


def _pi_show(**kw: Any) -> MagicMock:
    show = MagicMock()
    show.id = 1
    show.tmdb_id = 999
    show.title = kw.get("title", "Some Show")
    show.aliases = []
    show.content_type = kw.get("content_type")
    show.media_type = kw.get("media_type", "tv")
    show.sys_name = kw.get("sys_name", "Some Show")
    show.local_path = kw.get("local_path")
    show.episode_group_map = None
    return show


@pytest.mark.parametrize(
    ("show_kw", "action", "expected"),
    [
        ({"content_type": "anime"}, "created", _under(_ANIME, "Some Show")),
        ({"content_type": "tv"}, "created", _under(_TV, "Some Show")),
        ({"content_type": "movie"}, "created", str(PurePosixPath(_MOVIE))),
        ({"content_type": "anime"}, "found", _under(_ANIME, "Some Show")),
        (
            {"content_type": "anime", "sys_name": None, "title": "Re:Zero"},
            "found",
            _under(_ANIME, "Re Zero"),
        ),
        ({"content_type": None, "media_type": "movie"}, "found", str(PurePosixPath(_MOVIE))),
        ({"content_type": "tv", "local_path": "/kept"}, "found", "/kept"),
    ],
)
async def test_path_import_paths_are_unchanged_when_content_type_is_known(
    show_kw: dict[str, Any], action: str, expected: str
) -> None:
    show = await _path_import(_pi_show(**show_kw), action)
    assert show.local_path == expected


@pytest.mark.parametrize("media_type", ["tv", None])
async def test_path_import_leaves_local_path_unset_without_content_type(
    media_type: str | None,
) -> None:
    """Behaviour change: an existing show with no content_type is no longer guessed into TV."""
    show = await _path_import(_pi_show(content_type=None, media_type=media_type), "found")
    assert show.local_path is None


# ---------------------------------------------------------------------------
# Show creation: content_type is always set (given or inferred), so the path
# comes from the configured settings roots exactly as before.
# ---------------------------------------------------------------------------

_ORCH = "jidou.orchestrators.show_creation_orchestrator"


async def _create(payload: ShowCreate) -> Any:
    session = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=r)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", 5))
    with (
        patch(f"{_ORCH}.TMDBOrchestrator"),
        patch("jidou.orchestrators._show_provisioning.TMDBOrchestrator") as orch_cls,
        patch(f"{_ORCH}.fetch_show_metadata", new=AsyncMock(side_effect=RuntimeError("down"))),
        patch("jidou.orchestrators._show_provisioning.generate_aliases", new=AsyncMock()),
        patch(f"{_ORCH}.settings") as s,
    ):
        orch_cls.return_value.sync_show_episodes = AsyncMock()
        s.local_tv_path = "/cfg/tv"
        s.local_anime_path = "/cfg/anime"
        s.local_movie_path = "/cfg/movies"
        result = await get_or_create_show_from_tmdb(
            session, MagicMock(), ShowSeed.from_create(payload), llm=MagicMock()
        )
    return result.show


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (ShowCreate(tmdb_id=1, title="Plain"), _under("/cfg/tv", "Plain")),
        (
            ShowCreate(tmdb_id=2, title="Ani", genre_ids=[16], original_language="ja"),
            _under("/cfg/anime", "Ani"),
        ),
        (
            ShowCreate(tmdb_id=3, title="Film", media_type="movie"),
            str(PurePosixPath("/cfg/movies")),
        ),
        (
            ShowCreate(tmdb_id=4, title="X", sys_name="Mine", content_type="anime"),
            _under("/cfg/anime", "Mine"),
        ),
        (ShowCreate(tmdb_id=5, title="Y", local_path="/explicit"), "/explicit"),
    ],
)
async def test_show_creation_uses_configured_roots(payload: ShowCreate, expected: str) -> None:
    show = await _create(payload)
    assert show.local_path == expected
