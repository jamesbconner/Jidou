"""Tests for jidou.services.path_resolution."""

import pytest

from jidou.services.path_resolution import library_root, resolve_show_local_path

_PATHS = {
    "local_tv_path": "/data/media/tv",
    "local_anime_path": "/data/media/anime",
    "local_movie_path": "/data/media/movies",
}


def test_movie_content_type_uses_movie_root_flat() -> None:
    """Movies resolve to the shared movies root with no per-title subdirectory."""
    result = resolve_show_local_path(
        content_type="movie", media_type=None, sys_name="Show", **_PATHS
    )
    assert result == "/data/media/movies"


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
    assert result == "/data/media/movies"


def test_none_content_type_and_none_media_type_defaults_to_tv() -> None:
    result = resolve_show_local_path(content_type=None, media_type=None, sys_name="Show", **_PATHS)
    assert result == "/data/media/tv/Show"


def test_content_type_takes_priority_over_media_type() -> None:
    """A show's own content_type classification is always authoritative over media_type."""
    result = resolve_show_local_path(
        content_type="anime", media_type="movie", sys_name="Show", **_PATHS
    )
    assert result == "/data/media/anime/Show"


def test_media_type_fallback_and_default_tv() -> None:
    """content_type wins, media_type is the fallback, and anything else is TV."""
    kwargs = {"sys_name": "Show", **_PATHS}
    assert resolve_show_local_path(content_type=None, media_type="movie", **kwargs) == (
        "/data/media/movies"
    )
    assert resolve_show_local_path(content_type="tv", media_type="movie", **kwargs) == (
        "/data/media/tv/Show"
    )
    assert resolve_show_local_path(content_type=None, media_type=None, **kwargs) == (
        "/data/media/tv/Show"
    )
    assert resolve_show_local_path(content_type="weird", media_type=None, **kwargs) == (
        "/data/media/tv/Show"
    )


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("movie", "M"),
        ("anime", "A"),
        ("tv", "T"),
        (None, "T"),
        ("unknown", "T"),
    ],
)
def test_library_root_mapping(content_type: str | None, expected: str) -> None:
    """movie and anime pick their own root; everything else (incl. None) is TV."""
    assert library_root(content_type, tv="T", anime="A", movie="M") == expected


def test_library_root_returns_windows_style_root_untouched() -> None:
    """Host roots may be Windows paths; the helper must not normalise them."""
    root = "D:\\Media\\Anime"
    assert library_root("anime", tv="T", anime=root, movie="M") == root
