"""Cut metric_above/below/absent alerting — plan cap v2, 6f (C1).

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-09-10

Why
───
0 rules, 0 points, 0 series on the real instance (2026-09-10) for pushed-metric
alerting. What it did — page when an application-pushed number crosses a
threshold, or stops arriving — has a better replacement already in the
product: an application endpoint that returns 500 past its own threshold
(the threshold then lives in the code that knows it, not in a second alerting
system), monitored by a plain ``http`` check; or a pushed ``heartbeat`` for
"the agent is dead". The signal that would prove this cut wrong: three
distinct instances that both push metrics *and* ask to alert on them.

⚠️ The ingestion path (``services/metric_ingest.py``, ``metric_series.py``)
and the incident↔metric correlation panel (``services/metric_correlation.py``)
are **not** touched here, and neither are the ``custom_metrics`` /
``metric_series`` tables — they serve the product's thesis independently of
whether an alert can fire on a metric. This migration only removes the
*alerting* half (C-4).

The real payoff: ``Incident.alert_rule_id`` disappears
────────────────────────────────────────────────────────
That column existed for exactly one reason: the alert pipeline is anchored on
``Incident``, but a pushed-metric breach has no ``CheckResult`` to hang an
incident's cause on — so a metric alert had to open its own incident, and
without a discriminator ``process_check_result`` would pick up an open metric
incident via its ``scalar_one_or_none()`` and treat it as *the* incident for
that monitor, silently swallowing the next real outage. Cutting the only
thing that ever created a metric incident removes the reason the
discriminator existed. The invariant returns to what it was before C-4: one
open incident per monitor, full stop.

What this migration does
─────────────────────────
- **Refuses to run**, changing nothing, if it finds any ``alert_rules`` row
  still on ``metric_above``/``metric_below``/``metric_absent``, or any
  ``incidents`` row with ``alert_rule_id IS NOT NULL``. Unlike the F1/F4
  merges above, there is no lossless conversion to offer for either — an
  operator hitting this must delete those rules/incidents (or migrate the
  alerting need to an ``http``/``heartbeat`` monitor first) before upgrading
  past this revision.
- Drops ``alert_rules.metric_name``, ``metric_window_seconds``,
  ``metric_labels``.
- Drops ``incidents.alert_rule_id`` (FK + index) and, with it, the split
  unique-open-incident invariant: ``uq_incidents_monitor_open`` (restricted
  to ``alert_rule_id IS NULL``) and ``uq_incidents_monitor_rule_open`` both
  go, replaced by a single unqualified ``uq_incidents_monitor_open`` on
  ``(monitor_id) WHERE resolved_at IS NULL`` — exactly the shape it had
  before C-4 (``d3e4f5a6b7c8``).
- Strips any ``metric_above``/``metric_below``/``metric_absent`` row out of
  every ``alert_matrix_templates`` row's frozen ``rows`` JSON. Defensive: the
  matrix has never accepted these conditions as input (``PUT
  /monitors/{id}/matrix`` rejects them), but a template's JSON is
  independent of any live rule, so nothing guarantees one wasn't hand-crafted
  via ``POST /alerts/matrix-templates`` before this cut existed.

``downgrade()`` restores the three ``alert_rules`` columns and
``incidents.alert_rule_id`` (empty — this revision refused to run past any
data that would need them) and reverts the unique index split. It cannot
restore rows this migration refused to run past, nor the metric rows it
stripped from template JSON.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r2s3t4u5v6w7"
down_revision: str | None = "q1r2s3t4u5v6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

_METRIC_CONDITIONS = ("metric_above", "metric_below", "metric_absent")


def upgrade() -> None:
    bind = op.get_bind()

    stale_rules = bind.execute(
        sa.text(
            "SELECT count(*) FROM alert_rules WHERE condition IN "
            "('metric_above', 'metric_below', 'metric_absent')"
        )
    ).scalar_one()
    stale_incidents = bind.execute(
        sa.text("SELECT count(*) FROM incidents WHERE alert_rule_id IS NOT NULL")
    ).scalar_one()

    if stale_rules or stale_incidents:
        raise RuntimeError(
            "Refus de migrer : "
            f"{stale_rules} règle(s) d'alerte metric_above/below/absent et "
            f"{stale_incidents} incident(s) métrique encore ouverts/résolus existent. "
            "La coupe des alertes sur métrique poussée (plan cap v2, 6f, C1) n'a aucune "
            "conversion sans perte à proposer — supprime ces règles (et laisse leurs "
            "incidents se résoudre ou supprime-les) manuellement, en remplaçant le besoin "
            "par un endpoint applicatif surveillé en http ou un heartbeat, puis rejoue "
            "cette migration."
        )

    # ── Frozen matrix template rows: strip any metric row defensively ──────
    rows_by_id = bind.execute(sa.text("SELECT id, rows FROM alert_matrix_templates")).fetchall()
    for tpl_id, rows in rows_by_id:
        new_rows = [r for r in rows if r.get("condition") not in _METRIC_CONDITIONS]
        if new_rows != rows:
            bind.execute(
                sa.text("UPDATE alert_matrix_templates SET rows = :rows WHERE id = :id"),
                {"rows": json.dumps(new_rows), "id": tpl_id},
            )

    # ── incidents: drop the C-4 discriminator, un-split the invariant ──────
    op.execute("DROP INDEX IF EXISTS uq_incidents_monitor_rule_open")
    op.execute("DROP INDEX IF EXISTS uq_incidents_monitor_open")
    op.execute(
        "CREATE UNIQUE INDEX uq_incidents_monitor_open "
        "ON incidents (monitor_id) WHERE resolved_at IS NULL"
    )
    op.drop_index("ix_incidents_alert_rule_id", table_name="incidents")
    op.drop_constraint("fk_incidents_alert_rule_id", "incidents", type_="foreignkey")
    op.drop_column("incidents", "alert_rule_id")

    # ── alert_rules: drop the pushed-metric selector columns ───────────────
    op.drop_column("alert_rules", "metric_labels")
    op.drop_column("alert_rules", "metric_window_seconds")
    op.drop_column("alert_rules", "metric_name")


def downgrade() -> None:
    op.add_column("alert_rules", sa.Column("metric_name", sa.String(length=100), nullable=True))
    op.add_column("alert_rules", sa.Column("metric_window_seconds", sa.Integer(), nullable=True))
    op.add_column("alert_rules", sa.Column("metric_labels", _JSON, nullable=True))

    op.add_column("incidents", sa.Column("alert_rule_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_incidents_alert_rule_id",
        "incidents",
        "alert_rules",
        ["alert_rule_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_incidents_alert_rule_id", "incidents", ["alert_rule_id"])

    op.execute("DROP INDEX IF EXISTS uq_incidents_monitor_open")
    op.execute(
        "CREATE UNIQUE INDEX uq_incidents_monitor_open "
        "ON incidents (monitor_id) WHERE resolved_at IS NULL AND alert_rule_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_incidents_monitor_rule_open "
        "ON incidents (monitor_id, alert_rule_id) "
        "WHERE resolved_at IS NULL AND alert_rule_id IS NOT NULL"
    )
