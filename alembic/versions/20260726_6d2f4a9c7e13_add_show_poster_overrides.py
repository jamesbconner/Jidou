"""add list_poster_path and detail_poster_path to shows

Revision ID: 6d2f4a9c7e13
Revises: a563ec7cddae
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6d2f4a9c7e13"
down_revision: str | Sequence[str] | None = "a563ec7cddae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds manual poster overrides for the Shows-page card and the Show
    Details page header. Both are nullable TMDB ``file_path`` values that
    fall back to ``poster_path`` when unset -- kept separate from
    ``poster_path`` itself because the metadata resync mapper
    (services/tmdb_mapping.py) always overwrites ``poster_path`` from the
    raw TMDB response, which would otherwise silently discard a user's pick.
    """
    op.add_column("shows", sa.Column("list_poster_path", sa.String(length=500), nullable=True))
    op.add_column("shows", sa.Column("detail_poster_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("shows", "detail_poster_path")
    op.drop_column("shows", "list_poster_path")
