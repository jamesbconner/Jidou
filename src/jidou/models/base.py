"""Base model with common fields for all SQLAlchemy models."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


def str_enum(enum_cls: type[StrEnum], **kwargs: Any) -> SAEnum:
    """Build an SQLAlchemy ``Enum`` column type that stores member *values*.

    SQLAlchemy persists enum member *names* by default, but this schema stores
    the lower-case values.  Centralising ``values_callable`` here keeps every
    enum column consistent.  The Postgres type name is left at SQLAlchemy's
    default (the lower-cased class name) so no migration is needed.

    Args:
        enum_cls: The ``StrEnum`` whose values are stored.
        **kwargs: Passed through to ``sqlalchemy.Enum`` (e.g. ``native_enum=False``,
            ``length=50``).

    Returns:
        A configured ``sqlalchemy.Enum`` type.
    """
    return SAEnum(enum_cls, values_callable=lambda e: [m.value for m in e], **kwargs)


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns to a model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
