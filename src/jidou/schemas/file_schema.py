"""Pydantic schemas for DownloadedFile API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_VALID_STATUSES = "discovered|downloading|downloaded|unmatched|matched|routing|routed|error|pending"


class FileRead(BaseModel):
    """Full downloaded-file record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int | None = None
    episode_id: int | None = None
    original_filename: str
    remote_path: str
    local_path: str | None = None
    file_size: int
    hash_sha256: str | None = None
    status: str
    matched_by: str | None = None
    error_message: str | None = None
    parsed_show_name: str | None = None
    parsed_season: int | None = None
    parsed_episode: int | None = None
    parsed_confidence: float | None = None
    parsed_content_type: str | None = None
    created_at: datetime
    updated_at: datetime


class FileList(BaseModel):
    """Slim downloaded-file record for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    remote_path: str
    file_size: int
    status: str
    show_id: int | None = None
    episode_id: int | None = None
    parsed_show_name: str | None = None
    created_at: datetime


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


class FilePatch(BaseModel):
    """Request body for manually overriding fields on a downloaded file."""

    show_id: int | None = None
    episode_id: int | None = None
    status: str | None = Field(
        default=None,
        pattern=f"^({_VALID_STATUSES})$",
    )
    error_message: str | None = None
