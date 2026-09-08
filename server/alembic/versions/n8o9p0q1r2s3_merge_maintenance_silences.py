"""Merge AlertSilence into MaintenanceWindow — plan cap v2, 6d (F3).

Two tables answered the same question — "suppress alerts on a bounded time
window" — differing only in one bit: whether the window counted as *planned*
downtime (excluded from uptime, eligible for the public status page) or a
bare mute of dispatch. Two tables, two endpoints, two consecutive nav
entries, and no way for the person opening the modal to know which door to
use — see ``models/maintenance.py`` for the full rationale.

``MaintenanceWindow`` is the survivor: it already carries the richer scope
(monitor **or** group, team-scoped), the public-page integration from 5a
(``public_message``), and is the model every suppression call site
(``services/maintenance.py``, ``services/escalation.py``,
``services/incident_slo.py``, ``services/metric_alerts.py``) already reads.
``AlertSilence``'s two capabilities that ``MaintenanceWindow`` didn't have are
preserved as behaviour, not as a second table:

- the channel-owner-scoped dispatch mute (``services.alert._is_silenced``,
  repointed at ``maintenance_windows`` in the same commit as this migration);
- the "no target at all = every monitor I own" catch-all, now legal on
  ``maintenance_windows`` whenever ``is_maintenance`` is False (enforced in
  ``schemas/maintenance.py``, not at the database level — a maintenance
  window created before this migration keeps requiring an explicit target).

Data safety: both tables are empty on the real instance (checked in base as
part of this lot, 2026-09-08), but this migration migrates ``alert_silences``
rows rather than dropping them, in case another deployment has some —
unlike lot 6a's ``udp``/``composite`` cut, there's a lossless destination for
every row here, so refusing to run would just be dropping data that has
somewhere to go. Each row becomes a ``maintenance_windows`` row with
``is_maintenance=false``, ``reason`` folded into ``description`` (the closest
existing field — a silence's ``reason`` and a maintenance window's
``description`` answer the same "why" question), ``id``/``created_at``/
``updated_at`` preserved (no FK anywhere references ``alert_silences.id``,
so reusing it is safe), and ``group_id``/``team_id``/``public_message`` left
NULL (``AlertSilence`` never had those scopes).

``downgrade()`` reverses both halves: recreates ``alert_silences`` (same
shape as ``f8a9b0c1d2e3``), moves every ``is_maintenance=false`` row back
into it, deletes those rows from ``maintenance_windows``, then drops the
``is_maintenance`` column. A downgraded silence that had somehow acquired a
``group_id`` (impossible through the API before this migration, but not
impossible for a superadmin poking the database) loses it — ``AlertSilence``
has no such column — which is the same kind of narrowing lot 6a's downgrade
already accepts for data outside the API's own guarantees.

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n8o9p0q1r2s3"
down_revision: str | None = "m7n8o9p0q1r2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "maintenance_windows",
        sa.Column("is_maintenance", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO maintenance_windows (
                id, created_at, updated_at, name, description, public_message,
                owner_id, team_id, monitor_id, group_id, starts_at, ends_at,
                suppress_alerts, is_maintenance
            )
            SELECT
                id, created_at, updated_at, name, reason, NULL,
                owner_id, NULL, monitor_id, NULL, starts_at, ends_at,
                true, false
            FROM alert_silences
            """
        )
    )

    op.drop_index("ix_alert_silences_owner_monitor", table_name="alert_silences")
    op.drop_index("ix_alert_silences_window", table_name="alert_silences")
    op.drop_index("ix_alert_silences_monitor_id", table_name="alert_silences")
    op.drop_index("ix_alert_silences_owner_id", table_name="alert_silences")
    op.drop_table("alert_silences")


def downgrade() -> None:
    op.create_table(
        "alert_silences",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "monitor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_silences_owner_id", "alert_silences", ["owner_id"])
    op.create_index("ix_alert_silences_monitor_id", "alert_silences", ["monitor_id"])
    op.create_index("ix_alert_silences_window", "alert_silences", ["starts_at", "ends_at"])
    op.create_index("ix_alert_silences_owner_monitor", "alert_silences", ["owner_id", "monitor_id"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO alert_silences (
                id, created_at, updated_at, name, reason, owner_id, monitor_id,
                starts_at, ends_at
            )
            SELECT
                id, created_at, updated_at, name, description, owner_id, monitor_id,
                starts_at, ends_at
            FROM maintenance_windows
            WHERE is_maintenance = false
            """
        )
    )
    bind.execute(sa.text("DELETE FROM maintenance_windows WHERE is_maintenance = false"))

    op.drop_column("maintenance_windows", "is_maintenance")
