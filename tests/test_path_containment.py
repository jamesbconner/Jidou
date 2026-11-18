"""Tests for jidou.services.path_containment."""

import os
from pathlib import Path

import pytest

from jidou.services.path_containment import is_within_directory


def test_file_inside_root_is_within(tmp_path: Path) -> None:
    assert is_within_directory(str(tmp_path / "Movie.mkv"), str(tmp_path))


def test_nested_file_inside_root_is_within(tmp_path: Path) -> None:
    assert is_within_directory(str(tmp_path / "a" / "b" / "Movie.mkv"), str(tmp_path))


def test_root_itself_is_within(tmp_path: Path) -> None:
    assert is_within_directory(str(tmp_path), str(tmp_path))


def test_sibling_directory_is_not_within(tmp_path: Path) -> None:
    root = tmp_path / "movies"
    root.mkdir()
    assert not is_within_directory(str(tmp_path / "other" / "x.mkv"), str(root))


def test_sibling_sharing_name_prefix_is_not_within(tmp_path: Path) -> None:
    """``/movies-private`` must not pass as inside ``/movies`` (string-prefix trap)."""
    root = tmp_path / "movies"
    root.mkdir()
    assert not is_within_directory(str(tmp_path / "movies-private" / "x.mkv"), str(root))


def test_parent_traversal_is_not_within(tmp_path: Path) -> None:
    root = tmp_path / "movies"
    root.mkdir()
    assert not is_within_directory(str(root / ".." / "secret.txt"), str(root))


def test_nonexistent_path_inside_root_is_within(tmp_path: Path) -> None:
    assert is_within_directory(str(tmp_path / "missing.mkv"), str(tmp_path))


def test_symlink_pointing_outside_root_is_not_within(tmp_path: Path) -> None:
    root = tmp_path / "movies"
    root.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.write_text("data")
    link = root / "link.mkv"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform/account")
    assert not is_within_directory(str(link), str(root))
