"""Tests for jidou.services.file_filters."""

import datetime as dt
from datetime import datetime, timedelta

import pytest

from jidou.services.file_filters import (
    EXCLUDED_EXTENSIONS,
    EXCLUDED_KEYWORDS,
    is_recently_modified,
    is_valid_directory,
    is_valid_media_file,
)


class TestIsValidMediaFile:
    @pytest.mark.parametrize(
        "name",
        [
            "show.s01e01.mkv",
            "episode.mp4",
            "movie.avi",
            "series.S02E05.mkv",
        ],
    )
    def test_valid_video_files_pass(self, name: str) -> None:
        assert is_valid_media_file(name) is True

    @pytest.mark.parametrize("ext", EXCLUDED_EXTENSIONS)
    def test_excluded_extensions_are_rejected(self, ext: str) -> None:
        assert is_valid_media_file(f"file{ext}") is False

    def test_extension_check_is_case_insensitive(self) -> None:
        assert is_valid_media_file("cover.JPG") is False
        assert is_valid_media_file("cover.Nfo") is False

    @pytest.mark.parametrize("kw", EXCLUDED_KEYWORDS)
    def test_excluded_keywords_in_filename_are_rejected(self, kw: str) -> None:
        assert is_valid_media_file(f"show.{kw}.mkv") is False

    def test_keyword_check_is_case_insensitive(self) -> None:
        assert is_valid_media_file("Show.Sample.mkv") is False
        assert is_valid_media_file("Screens.mkv") is False

    def test_valid_file_with_keyword_in_show_name(self) -> None:
        # "sample" appearing as part of a word should still be caught
        assert is_valid_media_file("sample.s01e01.mkv") is False

    def test_empty_extension_is_allowed(self) -> None:
        # Files without an extension that have no excluded keywords are allowed
        assert is_valid_media_file("episode_no_extension") is True


class TestIsValidDirectory:
    def test_normal_directory_passes(self) -> None:
        assert is_valid_directory("Season 01") is True
        assert is_valid_directory("Show.Name") is True

    @pytest.mark.parametrize("kw", EXCLUDED_KEYWORDS)
    def test_excluded_keyword_directories_are_rejected(self, kw: str) -> None:
        assert is_valid_directory(kw) is False
        assert is_valid_directory(f"show_{kw}_dir") is False

    def test_check_is_case_insensitive(self) -> None:
        assert is_valid_directory("Screens") is False
        assert is_valid_directory("SAMPLE") is False


class TestIsRecentlyModified:
    def test_file_modified_just_now_is_recent(self) -> None:
        now = datetime.now(tz=dt.UTC)
        assert is_recently_modified(now) is True

    def test_file_modified_within_grace_window_is_recent(self) -> None:
        recent = datetime.now(tz=dt.UTC) - timedelta(seconds=30)
        assert is_recently_modified(recent) is True

    def test_file_modified_at_grace_boundary_is_not_recent(self) -> None:
        old_enough = datetime.now(tz=dt.UTC) - timedelta(seconds=61)
        assert is_recently_modified(old_enough) is False

    def test_file_modified_yesterday_is_not_recent(self) -> None:
        old = datetime.now(tz=dt.UTC) - timedelta(days=1)
        assert is_recently_modified(old) is False

    def test_custom_grace_seconds(self) -> None:
        mtime = datetime.now(tz=dt.UTC) - timedelta(seconds=90)
        assert is_recently_modified(mtime, grace_seconds=120) is True
        assert is_recently_modified(mtime, grace_seconds=60) is False

    def test_naive_datetime_uses_local_now(self) -> None:
        # Naive datetimes are compared to datetime.now(tz=None) = naive local time
        recent_naive = datetime.now() - timedelta(seconds=10)
        assert is_recently_modified(recent_naive) is True

    def test_future_mtime_is_not_recent(self) -> None:
        # SFTP host clock is ahead of scanner: negative elapsed must not block files.
        future = datetime.now(tz=dt.UTC) + timedelta(minutes=5)
        assert is_recently_modified(future) is False
