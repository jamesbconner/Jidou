"""Initial schema — creates all tables in their final state.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
        sa.Column("local_path", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shows_tmdb_id"), "shows", ["tmdb_id"], unique=True)
    op.create_index("ix_shows_aliases_gin", "shows", ["aliases"], postgresql_using="gin")

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
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("show_id", name="uq_watchlist_show_id"),
    )

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
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id"),
    )

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
        sa.Column("file_tracked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_episodes_show_id", "episodes", ["show_id"])
    op.create_index("ix_episodes_tmdb_id", "episodes", ["tmdb_id"], unique=True)

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
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("remote_path", name="uq_downloaded_files_remote_path"),
    )
    op.create_index("ix_downloaded_files_show_id", "downloaded_files", ["show_id"])
    op.create_index("ix_downloaded_files_episode_id", "downloaded_files", ["episode_id"])
    op.create_index("ix_downloaded_files_status", "downloaded_files", ["status"])


def downgrade() -> None:
    op.drop_index("ix_downloaded_files_status", table_name="downloaded_files")
    op.drop_index("ix_downloaded_files_episode_id", table_name="downloaded_files")
    op.drop_index("ix_downloaded_files_show_id", table_name="downloaded_files")
    op.drop_table("downloaded_files")
    op.execute(sa.text("DROP TYPE IF EXISTS filestatus"))
    op.execute(sa.text("DROP TYPE IF EXISTS matchedby"))

    op.drop_index("ix_episodes_tmdb_id", table_name="episodes")
    op.drop_index("ix_episodes_show_id", table_name="episodes")
    op.drop_table("episodes")

    op.drop_table("background_tasks")

    op.drop_table("watchlist")
    op.execute(sa.text("DROP TYPE IF EXISTS watchliststatus"))

    op.drop_index("ix_shows_aliases_gin", table_name="shows")
    op.drop_index(op.f("ix_shows_tmdb_id"), table_name="shows")
    op.drop_table("shows")
