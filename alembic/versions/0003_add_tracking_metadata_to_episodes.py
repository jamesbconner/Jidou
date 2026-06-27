"""Add tracked_filename and tracked_source to episodes.

Revision ID: 0003_add_tracking_metadata
Revises: 0002_add_file_tracked_at
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_tracking_metadata"
down_revision: str | None = "0002_add_file_tracked_at"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "episodes",
        sa.Column("tracked_filename", sa.String(500), nullable=True),
    )
    op.add_column(
        "episodes",
        sa.Column("tracked_source", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episodes", "tracked_source")
    op.drop_column("episodes", "tracked_filename")
