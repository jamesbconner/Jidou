"""Pydantic schemas for Episode API responses."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, computed_field

from jidou.services.path_transport import decode_path_bytes_for_display


class EpisodeRead(BaseModel):
    """Full episode record returned by detail endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    tmdb_id: int
    season_number: int
    episode_number: int
    name: str
    overview: str | None = None
    air_date: date | None = None
    runtime: int | None = None
    absolute_episode_number: int | None = None
    episode_type: str | None = None
    still_path: str | None = None
    file_tracked: bool
    created_at: datetime
    updated_at: datetime


class BackingFile(BaseModel):
    """A DownloadedFile record linked to an episode, for the episode list."""

    id: int
    filename: str


class EpisodeList(BaseModel):
    """Slim episode record returned by list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    season_number: int
    episode_number: int
    name: str
    air_date: date | None = None
    episode_type: str | None = None
    absolute_episode_number: int | None = None
    file_tracked: bool
    tracked_filename: str | None = None
    tracked_source: str | None = None
    backing_files: list[BackingFile] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tracked_filename_display(self) -> str | None:
        """Human-readable ``tracked_filename``, for display only.

        ``tracked_filename`` itself must stay exactly as stored — it may be
        percent-encoded (see :mod:`~jidou.services.path_transport`) when the
        underlying filename has non-UTF-8 bytes, and the frontend echoes it
        back verbatim to ``assign-import`` for an exact database match (see
        ``AssignImportModal.tsx``). Decoding it in place there would break
        that lookup. This lossy (U+FFFD on undecodable bytes), readable form
        is only for showing to a user.
        """
        return (
            decode_path_bytes_for_display(self.tracked_filename)
            if self.tracked_filename is not None
            else None
        )
