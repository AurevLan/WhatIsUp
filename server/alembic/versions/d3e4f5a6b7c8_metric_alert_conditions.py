"""Alert conditions on pushed metrics (plan V2, C-4).

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-09

Why
───
``custom_metrics`` could be written and read, never *reacted to*:
``services/alert_conditions.py`` knew ssl_expiry, response_time, baseline,
anomaly and schema_drift — all derived from a ``CheckResult``. A tenant could
push a metric and look at a graph; nothing ever fired. This migration carries
the schema half of closing that hole.

Two independent families of incident
────────────────────────────────────
The alert pipeline is anchored on ``Incident``: ``alert_events.incident_id`` is
NOT NULL, and ack / snooze / renotify / escalation / silences / digest all key
off an incident. A metric alert therefore has to open one.

That collides head-on with ``uq_incidents_monitor_open``, which enforces **one
open incident per monitor**. The collision is not a nuisance, it is a
correctness bug waiting to happen: with a metric incident sitting open,
``process_check_result`` would find it via ``scalar_one_or_none()`` and treat it
as the *outage* incident — the real outage would open no incident, fire no
``incident_opened`` alert, and be recorded as having started whenever the metric
breached. A silent, total loss of the product's core function.

The health engine lives with the same single-incident rule today
(``incident_slo.open_incident_from_health`` catches the ``IntegrityError`` and
drops the second incident), and that is fine *there*: a legacy incident and an
SLO incident both assert "this monitor is in trouble", so whichever wins says
the truth. "Queue depth above 1000" does not assert that, so metric incidents
need to be a separate population rather than a competitor.

Hence ``incidents.alert_rule_id``:

    alert_rule_id IS NULL      → availability incident (everything before C-4)
    alert_rule_id IS NOT NULL  → metric incident, owned by that alert rule

and the uniqueness invariant splits along the same line: still one open
availability incident per monitor, plus at most one open metric incident per
(monitor, rule). Two metric rules on the same monitor can now both be firing —
which is the whole point, they are watching different metrics.

``ON DELETE CASCADE`` rather than SET NULL: a metric incident is the rule's
state and nothing else. Nulling the column on rule deletion would silently
promote it to an availability incident and could violate the partial unique
index; deleting it is both truthful and safe.

Both indexes are PostgreSQL-only (partial indexes), declared in the model with
``ddl_if(dialect="postgresql")`` so they stay out of the SQLite ``create_all``
the tests use while remaining visible to ``autogenerate`` — see the note in
``models/incident.py`` about the drop-on-every-run this used to cause.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── alert_condition enum: the three pushed-metric conditions ──────────────
    # No literal below may *use* these labels: PostgreSQL forbids using a
    # newly-added enum value until the adding transaction has committed
    # ("unsafe use of new enum value"). Cf. u6v7w8x9y0z1, which had to cast to
    # text for exactly this reason.
    op.execute("ALTER TYPE alert_condition ADD VALUE IF NOT EXISTS 'metric_above'")
    op.execute("ALTER TYPE alert_condition ADD VALUE IF NOT EXISTS 'metric_below'")
    op.execute("ALTER TYPE alert_condition ADD VALUE IF NOT EXISTS 'metric_absent'")

    # ── Rule side: which metric, and over what freshness window ───────────────
    op.add_column("alert_rules", sa.Column("metric_name", sa.String(length=100), nullable=True))
    op.add_column("alert_rules", sa.Column("metric_window_seconds", sa.Integer(), nullable=True))

    # ── Incident side: the discriminator ──────────────────────────────────────
    op.add_column("incidents", sa.Column("alert_rule_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_incidents_alert_rule_id",
        "incidents",
        "alert_rules",
        ["alert_rule_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_incidents_alert_rule_id",
        "incidents",
        ["alert_rule_id"],
    )

    # Narrow the historical invariant to availability incidents, and give metric
    # incidents their own. Every pre-existing row has alert_rule_id NULL, so the
    # rebuilt index covers exactly the same set it did before.
    op.execute("DROP INDEX IF EXISTS uq_incidents_monitor_open")
    op.execute(
        "CREATE UNIQUE INDEX uq_incidents_monitor_open "
        "ON incidents (monitor_id) "
        "WHERE resolved_at IS NULL AND alert_rule_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_incidents_monitor_rule_open "
        "ON incidents (monitor_id, alert_rule_id) "
        "WHERE resolved_at IS NULL AND alert_rule_id IS NOT NULL"
    )


def downgrade() -> None:
    # Metric rules lose the column that says *which* metric they watch, so they
    # would come back as unfireable husks. ``condition::text`` rather than the
    # enum literal — see the note in upgrade().
    op.execute("DELETE FROM alert_rules WHERE condition::text LIKE 'metric\\_%'")

    # Open metric incidents must go before the old invariant can be restored:
    # a monitor with both an open availability incident and an open metric one
    # would make the unqualified unique index impossible to build.
    op.execute("DELETE FROM incidents WHERE alert_rule_id IS NOT NULL")

    op.execute("DROP INDEX IF EXISTS uq_incidents_monitor_rule_open")
    op.execute("DROP INDEX IF EXISTS uq_incidents_monitor_open")
    op.execute(
        "CREATE UNIQUE INDEX uq_incidents_monitor_open "
        "ON incidents (monitor_id) WHERE resolved_at IS NULL"
    )

    op.drop_index("ix_incidents_alert_rule_id", table_name="incidents")
    op.drop_constraint("fk_incidents_alert_rule_id", "incidents", type_="foreignkey")
    op.drop_column("incidents", "alert_rule_id")

    op.drop_column("alert_rules", "metric_window_seconds")
    op.drop_column("alert_rules", "metric_name")

    # The enum gains three labels in this revision's model change; PostgreSQL
    # cannot remove enum labels, and the rows that used them are gone with the
    # rules above. Leaving the labels in place is the standard, harmless
    # trade-off (same as every prior condition added to alert_condition).
