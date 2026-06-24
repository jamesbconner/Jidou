"""Add file_tracked_at to episodes.

Revision ID: 0002_add_file_tracked_at
Revises: 0001_initial
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_file_tracked_at"
down_revision: str | None = "0001_initial"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "episodes",
        sa.Column("file_tracked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episodes", "file_tracked_at")
