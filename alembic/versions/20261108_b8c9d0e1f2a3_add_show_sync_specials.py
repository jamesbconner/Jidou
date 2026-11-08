"""add shows.sync_specials

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds the non-null ``sync_specials`` opt-in flag. Existing shows get false,
    which keeps today's behavior (season 0 is not synced).
    """
    op.add_column(
        "shows",
        sa.Column("sync_specials", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the column; the opt-in choices are lost but no other show data is.
    """
    op.drop_column("shows", "sync_specials")
