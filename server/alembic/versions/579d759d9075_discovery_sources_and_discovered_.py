"""Discovery sources and discovered services (plan D, D-0).

Revision ID: 579d759d9075
Revises: f5a6b7c8d9e0
Create Date: 2026-08-17

Lays the two tables the discovery chantier reads and writes without wiring
anything up yet: no probe-facing endpoint, no reconciliation, no ``Monitor``
ever created from here. ``discovery_sources`` is a scan configuration (owner +
optional team, one probe, a bounded ``params`` blob whose shape depends on
``source_type``); ``discovered_services`` is one inventoried target per
source, unique by its canonical ``proto://host:port`` form, moving through
``proposed -> accepted | dismissed`` (plus ``orphaned``) as later lots review
it. See ``models/discovery.py`` for the full rationale.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "579d759d9075"
down_revision: str | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "discovery_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # CASCADE: a source has no meaning without the probe that runs it, and
        # its discovered_services cascade in turn.
        sa.Column(
            "probe_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("probes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Plain String validated by Pydantic Literal at the schema layer, not a
        # PostgreSQL enum — a new source_type (dns_zone, D-4) must not cost an
        # ALTER TYPE.
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("params", _JSON, nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discovery_sources_owner_id", "discovery_sources", ["owner_id"])
    op.create_index("ix_discovery_sources_team_id", "discovery_sources", ["team_id"])
    op.create_index("ix_discovery_sources_probe_id", "discovery_sources", ["probe_id"])

    op.create_table(
        "discovered_services",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("discovery_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Posed now, wired in D-2: which monitor an accepted proposal became.
        sa.Column(
            "monitor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("proto", sa.String(length=20), nullable=False),
        # Canonical `proto://host:port` form, computed by the D-1 ingestion
        # pipeline — this table only declares the shape and the uniqueness it
        # anchors.
        sa.Column("normalized_target", sa.String(length=400), nullable=False),
        sa.Column("hints", _JSON, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed','accepted','dismissed','orphaned')",
            name="ck_discovered_services_status",
        ),
        sa.UniqueConstraint(
            "source_id", "normalized_target", name="uq_discovered_services_source_target"
        ),
    )
    op.create_index(
        "ix_discovered_services_normalized_target", "discovered_services", ["normalized_target"]
    )
    op.create_index("ix_discovered_services_monitor_id", "discovered_services", ["monitor_id"])
    # The list endpoint's two filters (source_id alone, source_id+status). No
    # separate index on source_id alone: this composite already serves it as a
    # leftmost prefix, same as uq_discovered_services_source_target above.
    op.create_index(
        "ix_discovered_services_source_status", "discovered_services", ["source_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_discovered_services_source_status", table_name="discovered_services")
    op.drop_index("ix_discovered_services_monitor_id", table_name="discovered_services")
    op.drop_index("ix_discovered_services_normalized_target", table_name="discovered_services")
    op.drop_table("discovered_services")

    op.drop_index("ix_discovery_sources_probe_id", table_name="discovery_sources")
    op.drop_index("ix_discovery_sources_team_id", table_name="discovery_sources")
    op.drop_index("ix_discovery_sources_owner_id", table_name="discovery_sources")
    op.drop_table("discovery_sources")
