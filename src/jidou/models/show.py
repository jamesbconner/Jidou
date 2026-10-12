"""Show model for movies and TV series metadata."""

from enum import StrEnum
from typing import Literal

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin, str_enum


class ContentType(StrEnum):
    """User-assigned routing category for a show."""

    ANIME = "anime"
    TV = "tv"
    MOVIE = "movie"


# Who owns a Show column's value: "key" = identity/bookkeeping, "tmdb" = overwritten from
# the TMDB response on every sync, "user" = curated locally and never written by a sync,
# "derived" = computed locally but user-overridable (so a backfill must not clobber it).
ShowColumnSource = Literal["tmdb", "user", "derived", "key"]


def _source(source: ShowColumnSource) -> dict[str, ShowColumnSource]:
    """Build the ``info=`` payload that tags a Show column with its provenance.

    ``info`` is SQLAlchemy metadata only, so it never affects DDL or ``alembic check``.

    Args:
        source: The provenance tag to record.

    Returns:
        The ``info`` dict to pass to ``mapped_column``.
    """
    return {"source": source}


class Show(TimestampMixin, Base):
    """Represents a movie or TV series discovered via TMDB."""

    __tablename__ = "shows"
    __table_args__ = (
        # GIN index for the JSONB containment (@>) alias lookup in
        # services/show_lookup. Created by hand in a migration, so it must be
        # declared here or ``alembic check`` reports it as drift.
        Index(
            "ix_shows_aliases_gin",
            "aliases",
            postgresql_using="gin",
            postgresql_ops={"aliases": "jsonb_path_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, info=_source("key"))
    tmdb_id: Mapped[int] = mapped_column(unique=True, index=True, info=_source("key"))
    title: Mapped[str] = mapped_column(String(500), info=_source("tmdb"))
    overview: Mapped[str | None] = mapped_column(Text, info=_source("tmdb"))
    media_type: Mapped[str] = mapped_column(
        String(20), info=_source("tmdb")
    )  # "tv" or "movie" — from TMDB
    poster_path: Mapped[str | None] = mapped_column(String(500), info=_source("tmdb"))
    backdrop_path: Mapped[str | None] = mapped_column(String(500), info=_source("tmdb"))
    vote_average: Mapped[float | None] = mapped_column(Float, info=_source("tmdb"))
    vote_count: Mapped[int] = mapped_column(default=0, info=_source("tmdb"))
    release_date: Mapped[str | None] = mapped_column(String(20), info=_source("tmdb"))
    original_language: Mapped[str | None] = mapped_column(String(10), info=_source("tmdb"))
    cached: Mapped[bool] = mapped_column(Boolean, default=False, info=_source("derived"))
    # User-assigned routing category (anime/tv/movie); None until explicitly set
    # Stored as the lower-case value in VARCHAR(20) (no native enum, no CHECK), so the
    # DDL is unchanged from the plain-string column it replaces.
    content_type: Mapped[ContentType | None] = mapped_column(
        str_enum(ContentType, native_enum=False, length=20),
        info=_source("user"),
    )
    # Windows-safe sanitized title for local directory names
    sys_name: Mapped[str | None] = mapped_column(String(500), info=_source("derived"))
    # Alternative names used to match parsed filenames; stored as a JSON array
    aliases: Mapped[list[str] | None] = mapped_column(JSONB, info=_source("user"))
    # Source-tagged alias dict: {"tmdb": [...], "llm": [...], "user": [...]}
    # aliases is the materialized flat union used for GIN-indexed lookup.
    aliases_sources: Mapped[dict[str, list[str]] | None] = mapped_column(
        JSONB, info=_source("user")
    )
    # TMDB genres array: [{"id": 16, "name": "Animation"}, ...]
    genres: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, info=_source("tmdb"))
    # TMDB "adult" flag. NULL means unknown (never populated from a TMDB
    # response) and is treated as non-adult by dashboard filtering.
    adult: Mapped[bool | None] = mapped_column(Boolean, info=_source("tmdb"))
    # ISO 3166-1 origin country codes: ["JP", "US", ...]
    origin_country: Mapped[list[str] | None] = mapped_column(JSONB, info=_source("tmdb"))
    # Date the show last aired (TV only)
    last_air_date: Mapped[str | None] = mapped_column(String(20), info=_source("tmdb"))
    # Most recently aired episode object (TV only)
    last_episode_to_air: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, info=_source("tmdb")
    )
    # Next scheduled episode object (TV only, null when ended)
    next_episode_to_air: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, info=_source("tmdb")
    )
    # Show/movie homepage URL
    homepage: Mapped[str | None] = mapped_column(String(500), info=_source("tmdb"))
    # Cross-service IDs: {"imdb_id": "tt...", "tvdb_id": 123, "wikidata_id": "Q...", ...}
    external_ids: Mapped[dict[str, object] | None] = mapped_column(JSONB, info=_source("tmdb"))
    # TMDB episode groups; type-6 (Production) enables correct anime numbering
    episode_groups: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSONB, info=_source("tmdb")
    )
    # Resolved season/cour-position -> [season_number, episode_number] map, built
    # from episode_groups by services/episode_group_mapping.py. Nested by TMDB
    # group type ("6"/"2") -> sub-group order (as a declared season number would
    # read it) -> 1-based position within that sub-group. Derived/cache data,
    # not user data -- always safe to drop and recompute on the next TMDB sync.
    episode_group_map: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, info=_source("derived")
    )
    # Manual per-show override: when set, this TMDB episode_group's own
    # structure replaces the native season/episode catalog entirely (see
    # TMDBOrchestrator.apply_episode_group). None means "use TMDB's native
    # season/episode structure" -- the default for every show.
    active_episode_group_id: Mapped[str | None] = mapped_column(String(64), info=_source("user"))
    active_episode_group_name: Mapped[str | None] = mapped_column(String(500), info=_source("user"))
    # TMDB show status: "Returning Series", "Ended", "Cancelled", "Released", etc.
    status: Mapped[str | None] = mapped_column(String(100), info=_source("tmdb"))
    # TV only: whether the show is currently in production
    in_production: Mapped[bool | None] = mapped_column(Boolean, info=_source("tmdb"))
    # TV only: total number of seasons
    number_of_seasons: Mapped[int | None] = mapped_column(Integer, info=_source("tmdb"))
    # TV only: total number of episodes across all seasons
    number_of_episodes: Mapped[int | None] = mapped_column(Integer, info=_source("tmdb"))
    # TV only: broadcast networks / streaming services [{"id": 49, "name": "HBO", ...}]
    networks: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, info=_source("tmdb"))
    # TV only: "Scripted", "Miniseries", "Documentary", "Reality", etc.
    show_type: Mapped[str | None] = mapped_column(String(50), info=_source("tmdb"))
    # Episode runtime in minutes (TV: first value of episode_run_time; movie: runtime)
    runtime: Mapped[int | None] = mapped_column(Integer, info=_source("tmdb"))
    # Short promotional tagline
    tagline: Mapped[str | None] = mapped_column(Text, info=_source("tmdb"))
    # Local filesystem path to this show's root directory
    local_path: Mapped[str | None] = mapped_column(String(1000), info=_source("user"))
    # Manual poster overrides (TMDB file_path values) that survive metadata
    # resyncs -- tmdb_mapping.py always overwrites poster_path/backdrop_path
    # from the raw TMDB response, so a user's picked poster would otherwise
    # be silently reverted on the next sync. NULL falls back to poster_path.
    list_poster_path: Mapped[str | None] = mapped_column(String(500), info=_source("user"))
    detail_poster_path: Mapped[str | None] = mapped_column(String(500), info=_source("user"))
    # Manual banner (backdrop) override for the Show Details header, same
    # NULL-falls-back-to-backdrop_path pattern as the poster overrides above.
    # Single field, not split list/detail -- the banner only ever renders on
    # the Show Details page today.
    banner_path: Mapped[str | None] = mapped_column(String(500), info=_source("user"))
    # User opt-out: excludes this show from missing-episode counts/lists when False
    track_missing_episodes: Mapped[bool] = mapped_column(
        Boolean, default=True, info=_source("user")
    )

    def __repr__(self) -> str:
        """Return a concise representation of the Show."""
        return f"<Show(tmdb_id={self.tmdb_id}, title={self.title!r})>"


def show_columns(*sources: ShowColumnSource) -> frozenset[str]:
    """Return the names of ``Show`` columns tagged with any of the given sources.

    Args:
        *sources: One or more provenance tags (``"tmdb"``, ``"user"``, ``"derived"``,
            ``"key"``).

    Returns:
        Column names whose ``info["source"]`` is in ``sources``.

    Raises:
        KeyError: If a ``Show`` column has no ``source`` tag (a new column was added
            without declaring its provenance).

    Examples:
        >>> "sys_name" in show_columns("derived")
        True
    """
    return frozenset(
        column.name for column in Show.__table__.columns if column.info["source"] in sources
    )
