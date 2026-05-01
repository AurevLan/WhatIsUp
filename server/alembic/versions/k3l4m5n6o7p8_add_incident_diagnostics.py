"""Add incident_diagnostics table (V2-01-01).

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n6o7
Create Date: 2026-05-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "k3l4m5n6o7p8"
down_revision: str | None = "j2k3l4m5n6o7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_diagnostics",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "probe_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("probes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_incident_diagnostics_incident_kind",
        "incident_diagnostics",
        ["incident_id", "kind"],
    )
    op.create_index(
        "ix_incident_diagnostics_incident_probe",
        "incident_diagnostics",
        ["incident_id", "probe_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_incident_diagnostics_incident_probe", table_name="incident_diagnostics"
    )
    op.drop_index(
        "ix_incident_diagnostics_incident_kind", table_name="incident_diagnostics"
    )
    op.drop_table("incident_diagnostics")
