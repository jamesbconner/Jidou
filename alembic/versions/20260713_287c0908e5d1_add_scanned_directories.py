"""add scanned_directories table

Revision ID: 287c0908e5d1
Revises: f437cd782b1b
Create Date: 2026-07-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "287c0908e5d1"
down_revision: str | Sequence[str] | None = "f437cd782b1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "scanned_directories",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("remote_path", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("remote_path", name="uq_scanned_directories_remote_path"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scanned_directories")
