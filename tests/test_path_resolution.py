"""Tests for jidou.services.path_resolution."""

from jidou.services.path_resolution import resolve_show_local_path

_PATHS = {
    "local_tv_path": "/data/media/tv",
    "local_anime_path": "/data/media/anime",
    "local_movie_path": "/data/media/movies",
}


def test_movie_content_type_uses_movie_root() -> None:
    result = resolve_show_local_path(
        content_type="movie", media_type=None, sys_name="Show", **_PATHS
    )
    assert result == "/data/media/movies/Show"


def test_anime_content_type_uses_anime_root() -> None:
    result = resolve_show_local_path(
        content_type="anime", media_type=None, sys_name="Show", **_PATHS
    )
    assert result == "/data/media/anime/Show"


def test_tv_content_type_uses_tv_root() -> None:
    result = resolve_show_local_path(content_type="tv", media_type=None, sys_name="Show", **_PATHS)
    assert result == "/data/media/tv/Show"


def test_unrecognized_content_type_defaults_to_tv_root() -> None:
    result = resolve_show_local_path(
        content_type="documentary", media_type=None, sys_name="Show", **_PATHS
    )
    assert result == "/data/media/tv/Show"


def test_none_content_type_falls_back_to_media_type() -> None:
    result = resolve_show_local_path(
        content_type=None, media_type="movie", sys_name="Show", **_PATHS
    )
    assert result == "/data/media/movies/Show"


def test_none_content_type_and_none_media_type_defaults_to_tv() -> None:
    result = resolve_show_local_path(content_type=None, media_type=None, sys_name="Show", **_PATHS)
    assert result == "/data/media/tv/Show"


def test_content_type_takes_priority_over_media_type() -> None:
    """A show's own content_type classification is always authoritative over media_type."""
    result = resolve_show_local_path(
        content_type="anime", media_type="movie", sys_name="Show", **_PATHS
    )
    assert result == "/data/media/anime/Show"
