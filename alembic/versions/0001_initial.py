"""Initial schema — complete schema for all tables, indexes, and constraints.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-01

Squashed from migrations 0001-0009.  The service had not yet reached
production, so all incremental migrations are collapsed here into a single
authoritative initial state.

Dev databases should be wiped and recreated:
    docker compose down -v && docker compose up -d
    alembic upgrade head
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # shows
    # -------------------------------------------------------------------------
    op.create_table(
        "shows",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("poster_path", sa.String(length=500), nullable=True),
        sa.Column("backdrop_path", sa.String(length=500), nullable=True),
        sa.Column("vote_average", sa.Float(), nullable=True),
        sa.Column("vote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("release_date", sa.String(length=20), nullable=True),
        sa.Column("original_language", sa.String(length=10), nullable=True),
        sa.Column("cached", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("content_type", sa.String(length=20), nullable=True),
        sa.Column("sys_name", sa.String(length=500), nullable=True),
        sa.Column("aliases", JSONB(), nullable=True),
        sa.Column("genres", JSONB(), nullable=True),
        sa.Column("origin_country", JSONB(), nullable=True),
        sa.Column("last_air_date", sa.String(length=20), nullable=True),
        sa.Column("last_episode_to_air", JSONB(), nullable=True),
        sa.Column("next_episode_to_air", JSONB(), nullable=True),
        sa.Column("homepage", sa.String(length=500), nullable=True),
        sa.Column("external_ids", JSONB(), nullable=True),
        sa.Column("episode_groups", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=True),
        sa.Column("in_production", sa.Boolean(), nullable=True),
        sa.Column("number_of_seasons", sa.Integer(), nullable=True),
        sa.Column("number_of_episodes", sa.Integer(), nullable=True),
        sa.Column("networks", JSONB(), nullable=True),
        sa.Column("show_type", sa.String(length=50), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column("local_path", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shows_tmdb_id"), "shows", ["tmdb_id"], unique=True)
    # GIN index with jsonb_path_ops for @> containment queries (alias lookup).
    # SQLite does not support JSONB or GIN; guard with a dialect check.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text("CREATE INDEX ix_shows_aliases_gin ON shows USING GIN (aliases jsonb_path_ops)")
        )

    # -------------------------------------------------------------------------
    # watchlist
    # UniqueConstraint on show_id enforces one entry per show and provides the
    # B-tree index needed for cascade deletes and per-show lookups.
    # -------------------------------------------------------------------------
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("show_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "watching",
                "completed",
                "on_hold",
                "dropped",
                name="watchliststatus",
                create_constraint=True,
            ),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("show_id", name="uq_watchlist_show_id"),
    )

    # -------------------------------------------------------------------------
    # background_tasks
    # -------------------------------------------------------------------------
    op.create_table(
        "background_tasks",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=False),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "event_log",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id"),
    )

    # -------------------------------------------------------------------------
    # episodes
    # -------------------------------------------------------------------------
    op.create_table(
        "episodes",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("show_id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("air_date", sa.Date(), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("absolute_episode_number", sa.Integer(), nullable=True),
        sa.Column("episode_type", sa.String(length=50), nullable=True),
        sa.Column("still_path", sa.String(length=500), nullable=True),
        sa.Column("file_tracked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("file_tracked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracked_filename", sa.String(length=500), nullable=True),
        sa.Column("tracked_source", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_episodes_show_id", "episodes", ["show_id"])
    op.create_index("ix_episodes_tmdb_id", "episodes", ["tmdb_id"], unique=True)
    # Composite index for queries that filter by both show_id and file_tracked
    # (rematch, stats, tracking-state checks).  The leading show_id column also
    # covers plain show_id-only lookups, making ix_episodes_show_id redundant for
    # those queries — but we keep it for ORDER BY / range scans on show_id alone.
    op.create_index("ix_episodes_show_id_file_tracked", "episodes", ["show_id", "file_tracked"])

    # -------------------------------------------------------------------------
    # downloaded_files
    # -------------------------------------------------------------------------
    op.create_table(
        "downloaded_files",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("show_id", sa.Integer(), nullable=True),
        sa.Column("episode_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("remote_path", sa.String(length=1000), nullable=False),
        sa.Column("local_path", sa.String(length=1000), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("hash_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "discovered",
                "downloading",
                "downloaded",
                "unmatched",
                "matched",
                "routing",
                "routed",
                "error",
                "seeded",
                name="filestatus",
                create_constraint=True,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "matched_by",
            sa.Enum(
                "llm",
                "heuristic",
                "manual",
                name="matchedby",
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("parsed_show_name", sa.String(length=500), nullable=True),
        sa.Column("parsed_season", sa.Integer(), nullable=True),
        sa.Column("parsed_episode", sa.Integer(), nullable=True),
        sa.Column("parsed_confidence", sa.Float(), nullable=True),
        sa.Column("parsed_content_type", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("remote_path", name="uq_downloaded_files_remote_path"),
    )
    op.create_index("ix_downloaded_files_show_id", "downloaded_files", ["show_id"])
    op.create_index("ix_downloaded_files_episode_id", "downloaded_files", ["episode_id"])
    op.create_index("ix_downloaded_files_status", "downloaded_files", ["status"])

    # -------------------------------------------------------------------------
    # orphaned_tracking_records
    # -------------------------------------------------------------------------
    op.create_table(
        "orphaned_tracking_records",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("show_id", sa.Integer(), nullable=False),
        sa.Column("tracked_filename", sa.String(length=500), nullable=True),
        sa.Column("tracked_source", sa.String(length=20), nullable=False),
        sa.Column("old_season_number", sa.Integer(), nullable=False),
        sa.Column("old_episode_number", sa.Integer(), nullable=False),
        sa.Column("downloaded_file_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["downloaded_file_id"], ["downloaded_files.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_orphaned_tracking_records_show_id", "orphaned_tracking_records", ["show_id"]
    )
    op.create_index(
        "ix_orphaned_tracking_records_downloaded_file_id",
        "orphaned_tracking_records",
        ["downloaded_file_id"],
    )

    # -------------------------------------------------------------------------
    # rss_feeds
    # -------------------------------------------------------------------------
    op.create_table(
        "rss_feeds",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("remote_key", sa.String(length=64), unique=True, nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("default_download_location", sa.String(length=1024), nullable=True),
        sa.Column("default_move_completed", sa.String(length=1024), nullable=True),
        sa.Column("extra_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rss_feeds_remote_key", "rss_feeds", ["remote_key"])

    # -------------------------------------------------------------------------
    # rss_subscriptions
    # -------------------------------------------------------------------------
    op.create_table(
        "rss_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("remote_key", sa.String(length=64), nullable=True),
        sa.Column("feed_id", sa.Integer(), nullable=True),
        sa.Column("show_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("regex_include", sa.String(length=1024), nullable=True),
        sa.Column("regex_exclude", sa.String(length=1024), nullable=True),
        sa.Column("regex_include_ignorecase", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("regex_exclude_ignorecase", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("download_location", sa.String(length=1024), nullable=True),
        sa.Column("move_completed", sa.String(length=1024), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("enabled_in_config", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("last_match", sa.String(length=512), nullable=True),
        sa.Column("extra_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["feed_id"], ["rss_feeds.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rss_subscriptions_remote_key", "rss_subscriptions", ["remote_key"])
    op.create_index("ix_rss_subscriptions_feed_id", "rss_subscriptions", ["feed_id"])
    op.create_index("ix_rss_subscriptions_show_id", "rss_subscriptions", ["show_id"])
    # Partial unique: one enabled subscription per remote_key (non-NULL only).
    op.execute(
        """
        CREATE UNIQUE INDEX uq_rss_subscriptions_remote_key
        ON rss_subscriptions (remote_key)
        WHERE remote_key IS NOT NULL
        """
    )
    # Partial unique: one stub subscription (remote_key IS NULL) per show.
    op.create_index(
        "ix_rss_subscriptions_unique_stub_per_show",
        "rss_subscriptions",
        ["show_id"],
        unique=True,
        postgresql_where=sa.text("remote_key IS NULL"),
    )

    # -------------------------------------------------------------------------
    # rss_config_snapshots
    # -------------------------------------------------------------------------
    op.create_table(
        "rss_config_snapshots",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("snapshot_type", sa.String(length=32), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("rss_config_snapshots")

    op.drop_index("ix_rss_subscriptions_unique_stub_per_show", table_name="rss_subscriptions")
    op.execute("DROP INDEX IF EXISTS uq_rss_subscriptions_remote_key")
    op.drop_index("ix_rss_subscriptions_show_id", table_name="rss_subscriptions")
    op.drop_index("ix_rss_subscriptions_feed_id", table_name="rss_subscriptions")
    op.drop_index("ix_rss_subscriptions_remote_key", table_name="rss_subscriptions")
    op.drop_table("rss_subscriptions")

    op.drop_index("ix_rss_feeds_remote_key", table_name="rss_feeds")
    op.drop_table("rss_feeds")

    op.drop_index(
        "ix_orphaned_tracking_records_downloaded_file_id",
        table_name="orphaned_tracking_records",
    )
    op.drop_index("ix_orphaned_tracking_records_show_id", table_name="orphaned_tracking_records")
    op.drop_table("orphaned_tracking_records")

    op.drop_index("ix_downloaded_files_status", table_name="downloaded_files")
    op.drop_index("ix_downloaded_files_episode_id", table_name="downloaded_files")
    op.drop_index("ix_downloaded_files_show_id", table_name="downloaded_files")
    op.drop_table("downloaded_files")
    op.execute(sa.text("DROP TYPE IF EXISTS filestatus"))
    op.execute(sa.text("DROP TYPE IF EXISTS matchedby"))

    op.drop_index("ix_episodes_show_id_file_tracked", table_name="episodes")
    op.drop_index("ix_episodes_tmdb_id", table_name="episodes")
    op.drop_index("ix_episodes_show_id", table_name="episodes")
    op.drop_table("episodes")

    op.drop_table("background_tasks")

    op.drop_table("watchlist")
    op.execute(sa.text("DROP TYPE IF EXISTS watchliststatus"))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_shows_aliases_gin", table_name="shows")
    op.drop_index(op.f("ix_shows_tmdb_id"), table_name="shows")
    op.drop_table("shows")
