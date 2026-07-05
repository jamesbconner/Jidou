"""Add aliases_sources column to shows.

Revision ID: 0002_add_aliases_sources
Revises: 0001_initial
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_add_aliases_sources"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shows", sa.Column("aliases_sources", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("shows", "aliases_sources")
