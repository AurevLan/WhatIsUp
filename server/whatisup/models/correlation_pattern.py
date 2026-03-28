"""Correlation pattern — learned co-occurrence between monitors."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from whatisup.models.base import Base


class CorrelationPattern(Base):
    """Tracks monitors that frequently go down together.

    Updated each time an IncidentGroup is created or a new incident
    joins an existing group. High co_occurrence_count pairs can be
    used for proactive suggestions.
    """

    __tablename__ = "correlation_patterns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monitor_a_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    monitor_b_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    co_occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_correlation_pattern_pair", "monitor_a_id", "monitor_b_id", unique=True),
        Index("ix_correlation_pattern_count", "co_occurrence_count"),
    )
