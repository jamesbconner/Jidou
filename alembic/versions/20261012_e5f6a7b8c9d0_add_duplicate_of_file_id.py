"""add downloaded_files.duplicate_of_file_id

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# PostgreSQL's default name for this constraint, spelled out so the
# downgrade can drop it by name.
_FK_NAME = "downloaded_files_duplicate_of_file_id_fkey"
_INDEX_NAME = "ix_downloaded_files_duplicate_of_file_id"


def upgrade() -> None:
    """Upgrade schema.

    Adds the nullable self-referencing ``duplicate_of_file_id`` column
    (decision D33): the parse orchestrator sets it when a file is linked to
    an episode another file already covers. ``ON DELETE SET NULL`` so
    deleting the original clears the flag. Existing rows stay NULL: there is
    no backfill, only later parses set the flag.

    The index is built with CREATE INDEX CONCURRENTLY so writes to
    ``downloaded_files`` are not blocked; concurrent builds cannot run inside
    a transaction, hence the autocommit block.
    """
    op.add_column(
        "downloaded_files",
        sa.Column("duplicate_of_file_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        _FK_NAME,
        "downloaded_files",
        "downloaded_files",
        ["duplicate_of_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    with op.get_context().autocommit_block():
        op.create_index(
            _INDEX_NAME,
            "downloaded_files",
            ["duplicate_of_file_id"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema.

    Drops the index, the foreign key and the column. The duplicate flags are
    lost; the files themselves are untouched.
    """
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX_NAME,
            table_name="downloaded_files",
            postgresql_concurrently=True,
        )
    op.drop_constraint(_FK_NAME, "downloaded_files", type_="foreignkey")
    op.drop_column("downloaded_files", "duplicate_of_file_id")
