"""add shows.season_aliases

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds the nullable ``season_aliases`` JSONB map of season names (for example
    an arc title) to season numbers. Existing rows stay NULL ("no season
    names"); no backfill is needed. No index: the key check is OR'd into the
    existing alias lookup on the small shows table.
    """
    op.add_column(
        "shows",
        sa.Column("season_aliases", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the column; user-entered season names are lost but no other show
    data is.
    """
    op.drop_column("shows", "season_aliases")
