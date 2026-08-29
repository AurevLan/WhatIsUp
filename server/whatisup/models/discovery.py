"""Discovery sources and discovered services (plan D, D-0).

The product only ever saw what a human named in a form. This chantier turns a
probe already sitting inside the customer's network into an inventory sensor:
it is pointed at a source (a Docker socket, a bounded CIDR/port range, later a
DNS zone) and reports back what it sees. Nothing here creates a ``Monitor`` —
D-0 only lays the two tables the rest of the chantier reads and writes.

``DiscoverySource`` is the config: which probe runs the job, what kind of job
it is, and its bounded parameters. Scoping mirrors ``AlertChannel`` /
``OnCallSchedule`` — ``owner_id`` NOT NULL plus a nullable ``team_id`` — because
a source without a tenant would have nowhere to route what it finds.

``source_type`` is a plain ``String``, not a PostgreSQL enum: the set of types
grows over this chantier (``docker`` + ``port_scan`` now, ``dns_zone`` in D-4),
and ``ALTER TYPE ... ADD VALUE`` on every new lot is exactly the operational
cost a plain string with Pydantic-side ``Literal`` validation avoids. See
``schemas/discovery.py``.

``probe_group_id`` / ``elected_probe_id`` (plan E, E-2) let a source target a
``ProbeGroup`` instead of one ``Probe`` — ``probe_id``/``probe_group_id`` are
exclusive (``ck_discovery_sources_probe_xor_group``: exactly one is set).
A ``docker`` group source fans out to every capable member (the cross-push
dedup on ``DiscoveredService`` already handles the overlap); ``port_scan``/
``dns_zone`` mutate the network from one vantage point, so exactly one member
runs them — the server "sticks" that choice on ``elected_probe_id``
(``services/discovery_election.py``) and only re-elects when the pick stops
being usable. ``elected_probe_id`` is meaningless without a group
(``ck_discovery_sources_elected_requires_group``) and, like
``last_scan_probe_id``, is a breadcrumb (``SET NULL``), not an ownership edge.

``DiscoveredService`` is one inventoried target, unique per source by its
canonical ``proto://host:port`` form (``normalized_target`` — computed by the
D-1 ingestion pipeline, not here). The transport is a full snapshot per source
on every probe run (decision D-0-3): a service missing from the latest
snapshot is not deleted, it survives as a row the reconciler (D-2) can flip to
``orphaned`` — and one that reappears is reactivated rather than re-created,
which is why ``first_seen_at``/``last_seen_at`` exist from day one even though
nothing populates them yet.

The state machine — ``proposed -> accepted | dismissed``, plus ``orphaned`` —
encodes the chantier's one non-negotiable rule: discovery proposes, it never
writes a ``Monitor`` on its own (D-2 does that, and only on ``accept``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.monitor import Monitor

#: jsonb on PostgreSQL, plain JSON on SQLite (tests) — same helper as
#: models/incident.py / models/oncall.py / models/custom_metric.py.
_JSON = JSON().with_variant(JSONB(), "postgresql")

#: Closed, stable vocabulary — unlike ``source_type`` this one is not expected
#: to grow with new source kinds, so a DB-level CHECK is worth its keep.
DISCOVERED_SERVICE_STATUSES = ("proposed", "accepted", "dismissed", "orphaned")


class DiscoverySource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A discovery job: one probe, one kind of scan, bounded parameters."""

    __tablename__ = "discovery_sources"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # CASCADE: a source has no meaning without the probe that runs it, and its
    # discovered_services cascade in turn — losing a probe's config along with
    # its inventory is the expected outcome of deleting the probe itself.
    # Nullable since plan E, E-2: a source targets *either* one probe or one
    # ProbeGroup — see `ck_discovery_sources_probe_xor_group` below.
    probe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("probes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # plan E, E-2 — CASCADE for the same reason as probe_id: a group-targeted
    # source has no meaning once its group is gone.
    probe_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("probe_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # plan E, E-2 (E-0-2: sticky server-side election) — which group member
    # runs a port_scan/dns_zone source. SET NULL: losing the elected probe
    # must not take the source down, just trigger a re-election (see
    # `services/discovery_election.py`). Never set for a `docker` source
    # (fan-out, no single runner) or a probe-targeted source.
    elected_probe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("probes.id", ondelete="SET NULL"), nullable=True
    )
    # Validated by Pydantic's Literal["docker", "port_scan"] at the schema
    # layer, not a PostgreSQL enum — see module docstring.
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    params: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict, server_default="{}")
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    # Feedback loop (plan E, E-1): all three NULL until the first push, so
    # "never scanned" stays distinguishable from "scanned, nothing found" —
    # `last_scan_target_count=0` is a legitimate value, unlike a NULL count.
    # Set unconditionally by `api/v1/probes.py::push_discovery` on every
    # accepted snapshot, including an empty one (piège n°1 du lot E-1).
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scan_target_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SET NULL, not CASCADE: this column is a feedback breadcrumb ("who last
    # ran this"), not an ownership edge — losing the probe that once pushed
    # must not take the source's scan history down with it. Redundant with
    # `probe_id` today (a source has exactly one runner in E-1) but the two
    # diverge once E-2 lets a probe *group* run a source; recorded from day
    # one so the column doesn't need backfilling when that lands.
    last_scan_probe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("probes.id", ondelete="SET NULL"), nullable=True
    )

    services: Mapped[list[DiscoveredService]] = relationship(
        "DiscoveredService", back_populates="source", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # plan E, E-2 — exactly one target. Enforced at the schema layer too
        # (`DiscoverySourceIn`'s model_validator) so a bad request gets a
        # clean 422 instead of surfacing this constraint as a 500.
        CheckConstraint(
            "(probe_id IS NOT NULL AND probe_group_id IS NULL) "
            "OR (probe_id IS NULL AND probe_group_id IS NOT NULL)",
            name="ck_discovery_sources_probe_xor_group",
        ),
        CheckConstraint(
            "elected_probe_id IS NULL OR probe_group_id IS NOT NULL",
            name="ck_discovery_sources_elected_requires_group",
        ),
    )

    def __repr__(self) -> str:
        target = f"probe={self.probe_id}" if self.probe_id else f"group={self.probe_group_id}"
        return f"<DiscoverySource {self.source_type} {target}>"


class DiscoveredService(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One inventoried service, unique within its source by canonical target."""

    __tablename__ = "discovered_services"

    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("discovery_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Posed now, wired in D-2: which monitor an accepted proposal became.
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proto: Mapped[str] = mapped_column(String(20), nullable=False)
    # Canonical `proto://host:port` form (`proto://host` when port is null),
    # computed by the D-1 ingestion pipeline before insert — this column only
    # declares the shape and the uniqueness it anchors.
    normalized_target: Mapped[str] = mapped_column(String(400), nullable=False, index=True)
    # tls / http_status / server_header / container_labels… — whatever the
    # source kind can observe. Never secrets: filtering happens probe-side
    # before transport (plan_discovery.md § Sécurité).
    hints: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposed", server_default="proposed"
    )
    # Set by dismiss() (D-3), cleared the moment the row leaves `dismissed`
    # (re-proposed via a reappearance, or accepted) — a stale reason on a
    # service that is now `accepted` would misreport why it's in the review
    # queue.
    dismissed_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Captured by dismiss() (D-4) from a stable subset of `hints` at the
    # moment of the refusal — never recomputed from the live row, because
    # ingestion refreshes `hints` in place on every push (see
    # `api/v1/probes.py::push_discovery`) and would otherwise erase the
    # baseline the reconciler needs to detect drift. NULL for rows dismissed
    # before D-4 (or never dismissed): the reconciler treats that as "nothing
    # to compare against", never as a silent re-proposition. See
    # `services/discovery.py::dismissal_fingerprint`.
    dismissed_fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    source: Mapped[DiscoverySource] = relationship("DiscoverySource", back_populates="services")
    monitor: Mapped[Monitor | None] = relationship("Monitor")

    __table_args__ = (
        UniqueConstraint(
            "source_id", "normalized_target", name="uq_discovered_services_source_target"
        ),
        CheckConstraint(
            "status IN ('proposed','accepted','dismissed','orphaned')",
            name="ck_discovered_services_status",
        ),
        # The list endpoint's two filters (source_id alone, source_id+status).
        # No separate index on source_id alone: this composite already serves
        # it as a leftmost prefix, same reasoning as uq_...source_target above.
        Index("ix_discovered_services_source_status", "source_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<DiscoveredService {self.normalized_target} status={self.status}>"
