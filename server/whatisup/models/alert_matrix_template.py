"""Admin-managed alert matrix templates stored in DB."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class AlertMatrixTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_matrix_templates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rows: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def __repr__(self) -> str:
        return f"<AlertMatrixTemplate {self.name!r} ({self.check_type})>"
