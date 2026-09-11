"""add banner_path to shows

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds a manual banner (backdrop) override for the Show Details header,
    mirroring ``list_poster_path``/``detail_poster_path``. A nullable TMDB
    ``file_path`` value that falls back to ``backdrop_path`` when unset --
    kept separate from ``backdrop_path`` itself because the metadata resync
    mapper (services/tmdb_mapping.py) always overwrites ``backdrop_path``
    from the raw TMDB response, which would otherwise silently discard a
    user's pick. Single field, not split list/detail, because the banner
    only ever renders on the Show Details page today.
    """
    op.add_column("shows", sa.Column("banner_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("shows", "banner_path")
