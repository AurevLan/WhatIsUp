"""Drop the udp and composite check types — plan cap v2, étape 6a (C2 + C3).

Two independent cuts, bundled in one migration because both retire a
``CheckType`` member and both are zero-row on the real instance:

- **C2 — ``udp``.** Cut because a bare UDP probe (send, wait for a reply)
  cannot distinguish "the service is down" from "the packet was dropped in
  transit" — it renders a false verdict, not just an unused feature.
  ``ping``/``smtp`` stay: they get a real protocol-level acknowledgement.
  Replacement: ``ping`` for host reachability, ``dns`` for DNS, a pushed
  ``heartbeat`` for anything else that needs a real UDP-speaking check.
- **C3 — ``composite``.** Cut because ``_process_composite_result`` was a
  second, parallel incident-opening path next to the Health Engine
  (``services.health.evaluate_slos``) — retiring it is what leaves a single
  detection path, the actual point of plan Cap v2 4b. Replacement: a
  ``MonitorGroup`` for aggregated display, ``MonitorDependency`` +
  ``suppress_on_parent_down`` for causality, the Health Engine's
  ``quorum_down`` for multi-probe consensus.

``CheckType`` (``models/monitor.py``) is a plain Python ``enum.StrEnum`` —
``monitors.check_type`` is stored as ``String(20)``, never a native
PostgreSQL ``ENUM`` type. There is therefore no ``ALTER TYPE ... DROP
VALUE`` dance to do here: dropping the enum members is a schema/application
change only (this migration + the model), not a column type change.

What this migration actually touches:

- Drops ``composite_monitor_members`` (the composite-membership graph).
- Drops ``monitors.composite_aggregation`` and ``monitors.udp_port``.

**Data safety**: 0 rows on the real instance for both cuts, but this
migration must not silently destroy another deployment's monitors. It
refuses to run — raising, changing nothing — if it finds any monitor still
on ``check_type`` ``udp``/``composite``, or any row left in
``composite_monitor_members``. An operator hitting this must retype/delete
those monitors (and their composite links) *before* upgrading past this
revision; there is no automatic conversion because there's no lossless
mapping from "composite aggregation of N monitors" to a single monitor.

``downgrade()`` restores the columns and the ``composite_monitor_members``
table (same shape as it was created in ``d2e3f4a5b6c7``) but obviously
cannot restore rows this migration refused to run past.

Revision ID: m7n8o9p0q1r2
Revises: af00103e3c8a
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m7n8o9p0q1r2"
down_revision: str | None = "af00103e3c8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    stale_monitors = bind.execute(
        sa.text("SELECT count(*) FROM monitors WHERE check_type IN ('udp', 'composite')")
    ).scalar_one()
    stale_members = bind.execute(
        sa.text("SELECT count(*) FROM composite_monitor_members")
    ).scalar_one()

    if stale_monitors or stale_members:
        raise RuntimeError(
            "Refus de migrer : "
            f"{stale_monitors} moniteur(s) en check_type udp/composite et "
            f"{stale_members} lien(s) composite_monitor_members existent encore. "
            "La suppression des types udp/composite (plan cap v2, 6a) n'a aucune "
            "conversion sans perte à proposer (une agrégation composite de N "
            "moniteurs ne devient pas un moniteur unique) — retype ou supprime "
            "ces moniteurs et leurs liens composite manuellement, puis rejoue "
            "cette migration."
        )

    op.drop_table("composite_monitor_members")
    op.drop_column("monitors", "composite_aggregation")
    op.drop_column("monitors", "udp_port")


def downgrade() -> None:
    op.add_column("monitors", sa.Column("udp_port", sa.Integer(), nullable=True))
    op.add_column(
        "monitors",
        sa.Column("composite_aggregation", sa.String(20), nullable=True),
    )

    op.create_table(
        "composite_monitor_members",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "composite_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "monitor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("role", sa.String(50), nullable=True),
    )
    op.create_index("ix_cmm_composite_id", "composite_monitor_members", ["composite_id"])
    op.create_index("ix_cmm_monitor_id", "composite_monitor_members", ["monitor_id"])
    op.create_unique_constraint(
        "uq_composite_member",
        "composite_monitor_members",
        ["composite_id", "monitor_id"],
    )
