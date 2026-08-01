"""split downloaded_files.crc32 into extracted/declared/computed

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Splits the single ``crc32`` column (the computed value) into three
    independently-sourced readings so a mismatch can be pinpointed to a
    specific pipeline stage: the cheap filename-regex extraction done at
    download time (``crc32_extracted``), parse_filename()'s own reading
    persisted later by ParseOrchestrator (``crc32_declared``), and the
    value actually computed from the downloaded bytes (``crc32_computed``,
    renamed from the original ``crc32`` column — its data is preserved).
    """
    op.alter_column("downloaded_files", "crc32", new_column_name="crc32_computed")
    op.add_column(
        "downloaded_files",
        sa.Column("crc32_extracted", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "downloaded_files",
        sa.Column("crc32_declared", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("downloaded_files", "crc32_declared")
    op.drop_column("downloaded_files", "crc32_extracted")
    op.alter_column("downloaded_files", "crc32_computed", new_column_name="crc32")
