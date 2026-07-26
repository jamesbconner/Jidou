"""add ignored file status and ignored_reason column

Revision ID: a563ec7cddae
Revises: 287c0908e5d1
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a563ec7cddae"
down_revision: str | Sequence[str] | None = "287c0908e5d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ignored_reason_enum = postgresql.ENUM("noscan_path", "manual", name="ignoredreason")


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

    Unlike ``op.create_table``, ``op.add_column`` does not auto-create a new
    Postgres enum type for an inline ``sa.Enum(...)`` column — the type must
    be created explicitly first, or the ``ADD COLUMN`` fails with
    ``UndefinedObjectError: type "ignoredreason" does not exist``.
    """
    op.execute("ALTER TYPE filestatus ADD VALUE IF NOT EXISTS 'ignored'")
    _ignored_reason_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "downloaded_files",
        sa.Column("ignored_reason", _ignored_reason_enum, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema.

    Postgres has no ``ALTER TYPE ... DROP VALUE``, so ``'ignored'`` remains
    in the ``filestatus`` enum after downgrade. If any row has
    ``status='ignored'``, reassign it manually before relying on code that
    predates this migration.
    """
    op.drop_column("downloaded_files", "ignored_reason")
    _ignored_reason_enum.drop(op.get_bind(), checkfirst=True)
