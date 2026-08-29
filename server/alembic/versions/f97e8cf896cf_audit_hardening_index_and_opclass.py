"""Audit hardening: probe_group_members.probe_id index + affected_probe_ids GIN opclass.

Revision ID: f97e8cf896cf
Revises: b6c7d8e9f0a1
Create Date: 2026-08-29

Two independent, purely structural fixes from a security/perf audit:

1. ``probe_group_members`` only carries a composite PK on
   ``(probe_group_id, probe_id)``. Three hot paths filter on ``probe_id``
   alone (probe heartbeat, ``push_discovery``'s scope check, the admin probe
   view) and none of them are served by that composite btree's leading
   column — every one of those was a full scan of the association table.

2. ``ix_incidents_affected_probes_gin`` was built with the ``jsonb_path_ops``
   operator class, but the only query it exists to serve
   (``incident_correlation.correlate_common_cause``) uses the ``?|``
   operator, which ``jsonb_path_ops`` does not support at all (only
   ``@>``/``@?``/``@@``). The index was therefore invisible to the planner
   for that query since the day it was created (migration
   ``p1q2r3s4t5u6``). PostgreSQL cannot ``ALTER ... SET jsonb_ops`` in place,
   so the index is dropped and recreated.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f97e8cf896cf"
down_revision: str | None = "b6c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_probe_group_members_probe_id", "probe_group_members", ["probe_id"])

    op.execute("DROP INDEX IF EXISTS ix_incidents_affected_probes_gin")
    op.execute(
        "CREATE INDEX ix_incidents_affected_probes_gin "
        "ON incidents USING GIN ((affected_probe_ids::jsonb) jsonb_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_incidents_affected_probes_gin")
    op.execute(
        "CREATE INDEX ix_incidents_affected_probes_gin "
        "ON incidents USING GIN ((affected_probe_ids::jsonb) jsonb_path_ops)"
    )
    op.drop_index("ix_probe_group_members_probe_id", table_name="probe_group_members")
