"""DigestWindow model — persists digest accumulation to survive Redis restarts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from whatisup.models.base import Base


class DigestWindow(Base):
    __tablename__ = "digest_windows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    flush_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    events_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    ctx_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_digest_windows_flush_at", "flush_at"),)
