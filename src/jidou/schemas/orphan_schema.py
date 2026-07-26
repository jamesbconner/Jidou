"""Pydantic schemas for orphaned tracking record API requests and responses."""

from datetime import datetime

from pydantic import BaseModel, computed_field

from jidou.services.path_transport import decode_path_bytes_for_display


class OrphanRead(BaseModel):
    """Orphaned tracking record returned by ``GET /orphans``."""

    id: int
    show_id: int
    show_title: str
    tracked_filename: str | None
    tracked_source: str
    old_season_number: int
    old_episode_number: int
    downloaded_file_id: int | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tracked_filename_display(self) -> str | None:
        """Human-readable ``tracked_filename``, for display only.

        Snapshotted verbatim from ``Episode.tracked_filename`` (see
        ShowRematchOrchestrator), which may be percent-encoded — see
        :mod:`~jidou.services.path_transport`. Resolving/dismissing an
        orphan never echoes this value back, so unlike EpisodeList's
        equivalent field this exists purely for readability, not to avoid
        breaking a round trip.
        """
        return (
            decode_path_bytes_for_display(self.tracked_filename)
            if self.tracked_filename is not None
            else None
        )


class OrphanResolveRequest(BaseModel):
    """Payload for resolving an orphaned tracking record."""

    episode_id: int
