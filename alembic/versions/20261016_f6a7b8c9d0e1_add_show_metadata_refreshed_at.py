"""add shows.metadata_refreshed_at

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds the nullable ``metadata_refreshed_at`` timestamp the scheduled show
    metadata refresh uses to rank candidates. Existing rows stay NULL ("never
    refreshed"), so the job picks them up first; no backfill is needed.
    """
    op.add_column(
        "shows",
        sa.Column("metadata_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the column; the refresh history is lost but no show data is.
    """
    op.drop_column("shows", "metadata_refreshed_at")
