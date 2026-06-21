"""Pydantic schemas for path-file import API responses."""

from pydantic import BaseModel


class ShowImportResult(BaseModel):
    """Import outcome for a single show directory.

    Attributes:
        show_dir: Directory name from the path file.
        tmdb_id: TMDB ID of the resolved show, or None.
        tmdb_title: English title from TMDB, or None.
        action: ``"created"`` | ``"found"`` | ``"not_found"``.
        episodes_tracked: Episode rows marked ``file_tracked=True``.
        episodes_unmatched: Entries with no matching episode row.
    """

    show_dir: str
    tmdb_id: int | None = None
    tmdb_title: str | None = None
    action: str
    episodes_tracked: int
    episodes_unmatched: int


class PathImportResult(BaseModel):
    """Aggregate result returned by ``POST /api/import/text``.

    Attributes:
        shows_processed: Unique show directories in the uploaded file.
        shows_created: Shows newly created from TMDB.
        shows_found: Shows that already existed in the DB.
        shows_not_found: Shows that could not be matched on TMDB.
        episodes_tracked: Total episode rows marked ``file_tracked=True``.
        episodes_unmatched: Total entries with no matching episode row.
        show_results: Per-show breakdown.
    """

    shows_processed: int
    shows_created: int
    shows_found: int
    shows_not_found: int
    episodes_tracked: int
    episodes_unmatched: int
    show_results: list[ShowImportResult]
