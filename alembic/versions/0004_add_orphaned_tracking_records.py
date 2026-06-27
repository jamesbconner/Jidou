"""Add orphaned_tracking_records table.

Revision ID: 0004_add_orphaned_tracking_records
Revises: 0003_add_tracking_metadata
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_orphaned_tracking_records"
down_revision: str | None = "0003_add_tracking_metadata"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "orphaned_tracking_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "show_id",
            sa.Integer,
            sa.ForeignKey("shows.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tracked_filename", sa.String(500), nullable=True),
        sa.Column("tracked_source", sa.String(20), nullable=False),
        sa.Column("old_season_number", sa.Integer, nullable=False),
        sa.Column("old_episode_number", sa.Integer, nullable=False),
        sa.Column(
            "downloaded_file_id",
            sa.Integer,
            sa.ForeignKey("downloaded_files.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
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
    )


def downgrade() -> None:
    op.drop_table("orphaned_tracking_records")
