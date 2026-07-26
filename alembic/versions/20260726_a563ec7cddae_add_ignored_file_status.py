"""add ignored file status and ignored_reason column

Revision ID: a563ec7cddae
Revises: 287c0908e5d1
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a563ec7cddae"
down_revision: str | Sequence[str] | None = "287c0908e5d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds ``ignored`` to the existing ``filestatus`` enum for files that are
    downloaded (so they're never re-fetched) but deliberately excluded from
    parse/match/route — either because they fell under a configured noscan
    SFTP path, or via manual operator action. ``ignored_reason`` records
    which.

    ``ALTER TYPE ... ADD VALUE`` requires Postgres 12+ to run inside a
    transaction block; it does not insert or update any rows using the new
    value in this same migration, so it stays within that constraint.
    """
    op.execute("ALTER TYPE filestatus ADD VALUE IF NOT EXISTS 'ignored'")
    op.add_column(
        "downloaded_files",
        sa.Column(
            "ignored_reason",
            sa.Enum("noscan_path", "manual", name="ignoredreason", create_constraint=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema.

    Postgres has no ``ALTER TYPE ... DROP VALUE``, so ``'ignored'`` remains
    in the ``filestatus`` enum after downgrade. If any row has
    ``status='ignored'``, reassign it manually before relying on code that
    predates this migration.
    """
    op.drop_column("downloaded_files", "ignored_reason")
    op.execute(sa.text("DROP TYPE IF EXISTS ignoredreason"))
