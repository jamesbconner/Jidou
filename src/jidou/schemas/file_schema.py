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

    When ``show_id`` is supplied the show is assigned directly (manual match).
    When omitted the file is reset to ``downloaded`` so the parse/match
    pipeline will re-process it automatically on the next sync.
    """

    show_id: int | None = Field(
        default=None,
        description="Show to assign; omit to trigger automatic re-matching",
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
