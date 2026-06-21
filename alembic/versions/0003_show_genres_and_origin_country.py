"""Add genres and origin_country JSONB columns to shows table.

Revision ID: 0003_show_genres_and_origin_country
Revises: 0002_media_routing_schema
Create Date: 2026-06-21

Changes:
  shows — add genres (JSONB), origin_country (JSONB)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_show_genres_and_origin_country"
down_revision: str | None = "0002_media_routing_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add genres and origin_country columns to shows."""
    op.add_column("shows", sa.Column("genres", JSONB(), nullable=True))
    op.add_column("shows", sa.Column("origin_country", JSONB(), nullable=True))


def downgrade() -> None:
    """Remove genres and origin_country columns from shows."""
    op.drop_column("shows", "origin_country")
    op.drop_column("shows", "genres")
