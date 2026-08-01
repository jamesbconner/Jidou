"""add crc32 to downloaded_files

Revision ID: c2d3e4f5a6b7
Revises: b1a2c3d4e5f6
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "b1a2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds a column for the CRC32 of the actually-downloaded bytes, computed
    by DownloadOrchestrator's post-download integrity check and compared
    against the fingerprint embedded in fansub filenames (e.g. ``[A0B1C2D3]``).
    """
    op.add_column(
        "downloaded_files",
        sa.Column("crc32", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("downloaded_files", "crc32")
