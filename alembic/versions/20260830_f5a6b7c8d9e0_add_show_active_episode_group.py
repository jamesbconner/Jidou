"""add active_episode_group_id/name to shows

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5a6b7c8d9e0"
down_revision: str | Sequence[str] | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds the per-show manual override of which TMDB episode_group to treat
    as the show's episode catalog. NULL (the default) means "use TMDB's
    native season/episode structure" -- the same None-means-unset convention
    already used by episode_groups/episode_group_map.
    """
    op.add_column(
        "shows", sa.Column("active_episode_group_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "shows", sa.Column("active_episode_group_name", sa.String(length=500), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("shows", "active_episode_group_name")
    op.drop_column("shows", "active_episode_group_id")
