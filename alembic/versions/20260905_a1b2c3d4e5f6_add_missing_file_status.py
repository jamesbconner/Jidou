"""add missing file status

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e0
Create Date: 2026-09-05

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds ``missing`` to the existing ``filestatus`` enum for files whose
    ``local_path`` no longer exists on disk (renamed/moved/deleted outside
    the app), detected by the Scan Local Files reconciliation pass — see
    ``services/file_reconciliation.py``.

    ``ALTER TYPE ... ADD VALUE`` requires Postgres 12+ to run inside a
    transaction block; it does not insert or update any rows using the new
    value in this same migration, so it stays within that constraint.
    """
    op.execute("ALTER TYPE filestatus ADD VALUE IF NOT EXISTS 'missing'")


def downgrade() -> None:
    """Downgrade schema.

    Postgres has no ``ALTER TYPE ... DROP VALUE``, so ``'missing'`` remains
    in the ``filestatus`` enum after downgrade. If any row has
    ``status='missing'``, reassign it manually before relying on code that
    predates this migration.
    """
