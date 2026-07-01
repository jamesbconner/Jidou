"""Pydantic schemas for Show API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShowCreate(BaseModel):
    """Payload for adding a show to the database.

    All TMDB fields mirror the search/trending response so the frontend can
    pass a result card directly to ``POST /shows`` without an extra round-trip.
    ``content_type`` and ``sys_name`` are optional user-assigned fields.
    """

    tmdb_id: int
    title: str
    media_type: str = Field(default="tv", pattern="^(tv|movie)$")
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    vote_average: float | None = None
    vote_count: int = 0
    release_date: str | None = None
    original_language: str | None = None
    genres: list[dict[str, object]] | None = Field(
        default=None,
        description='TMDB genre objects: [{"id": 16, "name": "Animation"}]',
    )
    genre_ids: list[int] | None = Field(
        default=None,
        description="TMDB genre ID list from search/trending cards: [16, 18]",
    )
    origin_country: list[str] | None = Field(
        default=None,
        description='ISO 3166-1 country codes: ["JP", "US"]',
    )
    last_air_date: str | None = None
    last_episode_to_air: dict[str, object] | None = None
    next_episode_to_air: dict[str, object] | None = None
    homepage: str | None = None
    external_ids: dict[str, object] | None = None
    episode_groups: list[dict[str, object]] | None = None
    status: str | None = Field(
        default=None,
        description='TMDB show status: "Returning Series", "Ended", "Released", etc.',
    )
    in_production: bool | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    networks: list[dict[str, object]] | None = Field(
        default=None,
        description="Broadcast networks / streaming services",
    )
    show_type: str | None = Field(
        default=None,
        description='TV series type: "Scripted", "Miniseries", "Documentary", etc.',
    )
    runtime: int | None = Field(default=None, description="Episode or movie runtime in minutes")
    tagline: str | None = None
    content_type: str | None = Field(
        default=None, pattern="^(anime|tv|movie)$", description="Routing category"
    )
    sys_name: str | None = Field(
        default=None,
        max_length=500,
        description="Windows-safe directory name; auto-derived from title if omitted",
    )
    local_path: str | None = Field(
        default=None,
        description="Absolute path to the show's root directory on the local filesystem",
    )


class ShowPatch(BaseModel):
    """Payload for partial updates to a show's user-managed fields.

    Only fields present in the request body are applied; omitted fields are
    left unchanged.  Use ``null`` to clear a field.
    """

    content_type: str | None = Field(
        default=None, pattern="^(anime|tv|movie)$", description="Routing category"
    )

    model_config = ConfigDict(populate_by_name=True)


class ShowPaths(BaseModel):
    """Payload for updating a show's local filesystem path."""

    local_path: str | None = None


class ShowAliasesUpdate(BaseModel):
    """Payload for replacing the full aliases list on a show."""

    aliases: list[str] = Field(default_factory=list)


class ShowRead(BaseModel):
    """Full show record returned by ``GET /shows/{id}``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_id: int
    title: str
    media_type: str
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    vote_average: float | None = None
    vote_count: int
    release_date: str | None = None
    original_language: str | None = None
    cached: bool
    content_type: str | None = None
    sys_name: str | None = None
    aliases: list[str] | None = None
    genres: list[dict[str, object]] | None = None
    origin_country: list[str] | None = None
    last_air_date: str | None = None
    last_episode_to_air: dict[str, object] | None = None
    next_episode_to_air: dict[str, object] | None = None
    homepage: str | None = None
    external_ids: dict[str, object] | None = None
    episode_groups: list[dict[str, object]] | None = None
    status: str | None = None
    in_production: bool | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    networks: list[dict[str, object]] | None = None
    show_type: str | None = None
    runtime: int | None = None
    tagline: str | None = None
    local_path: str | None = None
    created_at: datetime
    updated_at: datetime


class AssignImportRequest(BaseModel):
    """Payload for reassigning an imported episode's tracked filename."""

    filename: str


class RematchRequest(BaseModel):
    """Payload for re-matching a show to a different TMDB entry."""

    tmdb_id: int
    media_type: str = "tv"
    preserve_tracking: bool = Field(
        default=True,
        description=(
            "When True (default), tracked episode data is migrated to the new TMDB entry "
            "by matching on (season_number, episode_number). Set to False for a clean-slate "
            "rematch that discards all existing tracking state."
        ),
    )


class ShowList(BaseModel):
    """Slim show record returned by ``GET /shows``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_id: int
    title: str
    media_type: str
    poster_path: str | None = None
    vote_average: float | None = None
    release_date: str | None = None
    original_language: str | None = None
    content_type: str | None = None
    sys_name: str | None = None
    genres: list[dict[str, object]] | None = None
    origin_country: list[str] | None = None
    last_air_date: str | None = None
    last_episode_to_air: dict[str, object] | None = None
    next_episode_to_air: dict[str, object] | None = None
    homepage: str | None = None
    external_ids: dict[str, object] | None = None
    episode_groups: list[dict[str, object]] | None = None
    status: str | None = None
    in_production: bool | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    networks: list[dict[str, object]] | None = None
    show_type: str | None = None
    runtime: int | None = None
    tagline: str | None = None
    local_path: str | None = None
    episode_count: int = 0
    matched_file_count: int = 0
    created_at: datetime
