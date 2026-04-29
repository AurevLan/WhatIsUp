"""Probe (remote agent) model."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Double, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.result import CheckResult


class NetworkType(enum.StrEnum):
    internal = "internal"  # Réseau d'entreprise / LAN privé
    external = "external"  # Internet public


class Probe(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "probes"

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Double, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Double, nullable=True)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    network_type: Mapped[NetworkType] = mapped_column(
        SQLEnum(NetworkType, name="networktype"),
        default=NetworkType.external,
        server_default="external",
    )

    # V2-02-01 — Network intelligence enrichment.
    # Populated asynchronously by services/probe_enrichment.py from Team Cymru
    # DNS lookups (and optionally MaxMind GeoLite2 ASN). All nullable so the
    # probe stays usable before enrichment completes.
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True, index=True)
    asn: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    asn_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ixp_membership: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    asn_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    check_results: Mapped[list[CheckResult]] = relationship("CheckResult", back_populates="probe")

    def __repr__(self) -> str:
        return f"<Probe {self.name!r} location={self.location_name!r}>"
