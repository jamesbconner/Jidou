"""Pydantic schemas for DownloadedFile API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field

from jidou.models.downloaded_file import FileStatus, IgnoredReason, MatchedBy
from jidou.schemas._base import ORMModel


class FileShowBrief(ORMModel):
    """Minimal show fields embedded in file responses."""

    id: int
    title: str


class EpisodeBrief(ORMModel):
    """Minimal episode fields embedded in file responses."""

    id: int
    season_number: int
    episode_number: int
    name: str


class FileRead(ORMModel):
    """Full downloaded-file record."""

    id: int
    show_id: int | None = None
    episode_id: int | None = None
    original_filename: str
    remote_path: str
    local_path: str | None = None
    file_size: int
    hash_sha256: str | None = None
    status: FileStatus
    matched_by: MatchedBy | None = None
    ignored_reason: IgnoredReason | None = None
    error_message: str | None = None
    parsed_show_name: str | None = None
    parsed_season: int | None = None
    parsed_episode: int | None = None
    parsed_confidence: float | None = None
    parsed_content_type: str | None = None
    created_at: datetime
    updated_at: datetime
    show: FileShowBrief | None = None
    episode: EpisodeBrief | None = None


class FileMatchRequest(BaseModel):
    """Request body for assigning a show to an unmatched file.

    Three modes:
    - ``show_id`` only: assign an existing tracked show (fast path).
    - ``tmdb_id`` only or with ``local_path``/``content_type``: look up or
      create the show on demand, then assign.
    - All omitted: reset the file to ``downloaded`` for automatic re-matching.
    """

    show_id: int | None = Field(
        default=None,
        description="Existing DB show to assign; omit to use tmdb_id or to reset",
    )
    tmdb_id: int | None = Field(
        default=None,
        description="TMDB ID to look up or create a show on demand",
    )
    tmdb_media_type: str | None = Field(
        default=None,
        pattern="^(tv|movie)$",
        description="TMDB media type ('tv' or 'movie') for the correct details endpoint",
    )
    local_path: str | None = Field(
        default=None,
        description="Local filesystem root for this show (required when creating via tmdb_id)",
    )
    content_type: str | None = Field(
        default=None,
        pattern="^(tv|anime|movie)$",
        description="Content type for routing (tv/anime/movie)",
    )


class VerifyPathsRequest(BaseModel):
    """Request body for checking which candidate paths still exist on disk."""

    paths: list[str] = Field(max_length=500)


class VerifyPathsResponse(BaseModel):
    """Subset of the requested paths confirmed to exist on disk."""

    existing: list[str]


class FilePatch(BaseModel):
    """Request body for manually overriding fields on a downloaded file."""

    show_id: int | None = None
    episode_id: int | None = None
    status: FileStatus | None = None
    error_message: str | None = None
