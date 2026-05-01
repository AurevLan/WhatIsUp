"""IncidentDiagnostic model — raw probe diagnostics collected on incident open.

Foundation of the V2-01 Diagnostic Engine: when an incident opens, each affected
probe is asked to run a small battery of network diagnostics (traceroute, dig
+trace, openssl s_client, ICMP ping, verbose HTTP) against the monitor target.
The raw structured payload is stored here so the SRE can inspect what the probe
saw at the time the incident triggered, before noisy retries pollute the trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.incident import Incident
    from whatisup.models.probe import Probe


# Allowed values for ``IncidentDiagnostic.kind``. Kept as a literal list (not an
# Enum) so the probe can extend with new collectors without an enum migration.
DIAGNOSTIC_KINDS = (
    "traceroute",
    "dig_trace",
    "openssl_handshake",
    "icmp_ping",
    "http_verbose",
)


class IncidentDiagnostic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "incident_diagnostics"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL: a probe can be decommissioned while keeping the diagnostic trail.
    probe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("probes.id", ondelete="SET NULL"),
        nullable=True,
    )

    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    incident: Mapped[Incident] = relationship("Incident", foreign_keys=[incident_id])
    probe: Mapped[Probe | None] = relationship("Probe", foreign_keys=[probe_id])

    __table_args__ = (
        Index("ix_incident_diagnostics_incident_kind", "incident_id", "kind"),
        Index("ix_incident_diagnostics_incident_probe", "incident_id", "probe_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IncidentDiagnostic incident={self.incident_id} kind={self.kind}>"
