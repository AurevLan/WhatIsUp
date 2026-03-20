"""MonitorTemplate — reusable monitor configuration blueprints."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Use JSONB on PostgreSQL (indexable), fall back to JSON on SQLite (tests)
_JSON = JSON().with_variant(JSONB(), "postgresql")

if TYPE_CHECKING:
    from whatisup.models.user import User


class MonitorTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monitor_templates"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # List of variable defs: [{name, description, default?}]
    variables: Mapped[list | None] = mapped_column(_JSON, nullable=True, default=list)
    # Monitor config dict (mirrors MonitorCreate fields, supports {{VAR}} placeholders)
    monitor_config: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    owner: Mapped[User] = relationship("User")

    __table_args__ = (Index("ix_monitor_templates_owner", "owner_id"),)
