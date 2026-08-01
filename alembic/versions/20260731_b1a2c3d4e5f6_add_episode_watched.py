"""add watched and watched_at to episodes

Revision ID: b1a2c3d4e5f6
Revises: e00342464620
Create Date: 2026-07-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1a2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e00342464620"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds user-driven watch state to episodes, mirroring the existing
    ``file_tracked``/``file_tracked_at`` pair. ``server_default='false'``
    backfills existing rows to unwatched without a separate data migration.
    """
    op.add_column(
        "episodes",
        sa.Column("watched", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "episodes",
        sa.Column("watched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("episodes", "watched_at")
    op.drop_column("episodes", "watched")
