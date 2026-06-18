"""add episodes and downloaded_files tables, extend shows with paths

Revision ID: 20260617_0003_episodes_and_files
Revises: 20260616_0002_background_tasks
Create Date: 2026-06-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0003_episodes_and_files"
down_revision: str | None = "20260616_0002_background_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extend shows with SFTP / local path fields
    op.add_column("shows", sa.Column("remote_path", sa.String(length=1000), nullable=True))
    op.add_column("shows", sa.Column("local_path", sa.String(length=1000), nullable=True))

    # Episodes table
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

    # Downloaded files table
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
                "downloading",
                "downloaded",
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
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["show_id"], ["shows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
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

    op.drop_column("shows", "local_path")
    op.drop_column("shows", "remote_path")
