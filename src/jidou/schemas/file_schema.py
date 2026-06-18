"""Pydantic schemas for DownloadedFile API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime


class FileMatchRequest(BaseModel):
    """Request body for re-triggering episode matching on a file."""

    method: str = Field(
        default="auto",
        pattern="^(auto|llm|heuristic)$",
        description="Matching strategy: 'auto' tries LLM first then heuristic.",
    )
