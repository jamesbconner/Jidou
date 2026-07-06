"""Application-wide key/value settings, editable at runtime via the API."""

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class AppSetting(TimestampMixin, Base):
    """A single runtime-configurable setting, keyed by a dotted name.

    Unlike the env-var-backed settings in :mod:`jidou.config` (fixed at
    process startup), rows here can be read and updated through the API
    without a restart. ``value`` is JSONB so a single table can hold
    settings of any JSON-serializable shape (bool, string, list, object).
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[object] = mapped_column(JSONB)
