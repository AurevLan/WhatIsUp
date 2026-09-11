"""Merge the three latency conditions into latency_anomaly — plan cap v2, 6f (F4).

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-09-10

Why
───
``response_time_above`` (absolute threshold), ``response_time_above_baseline``
(× 7-day rolling average) and ``anomaly_detection`` (z-score) all answer the
same question — "is this slow?" — and the old condition picker presented them
flat, with nothing to tell an operator which one to reach for. This merges the
three into ``latency_anomaly``, a single condition whose sensitivity mode
(absolute / relative / statistical) is inferred from which one of
``AlertRule.threshold_value`` / ``baseline_factor`` / ``anomaly_zscore_threshold``
is set — no new column needed, each rule already carried exactly the field its
old condition used. ``threshold_advisor`` (already unattached) becomes the
natural companion of the absolute mode.

``alert_rules.condition`` is already a plain ``VARCHAR(30)`` as of
``p0q1r2s3t4u5`` — see that migration's docstring for why a native PostgreSQL
enum could not survive 6f. This migration is a plain data rewrite: no enum
ceremony, no column type change.

What this migration does
─────────────────────────
- Rewrites every ``alert_rules`` row: ``response_time_above`` /
  ``response_time_above_baseline`` / ``anomaly_detection`` → ``latency_anomaly``.
  Lossless and exactly reversible — the sensitivity mode is recoverable from
  which of the three numeric fields is still set on the row.
- Rewrites the same three conditions inside every ``alert_matrix_templates``
  row's frozen ``rows`` JSON. A "strict" template that paired an absolute
  latency row with a z-score row as two separate rows would otherwise end up
  with two rows sharing the same condition — the migration keeps only the
  absolute-threshold row (the simpler, more legible default); the statistical
  mode remains selectable manually, just not pre-selected by a built-in
  template.

Data safety: measured at 1 live rule (``response_time_above_baseline``) on
the real instance (2026-09-10). The mapping is total and lossless, so this
runs unconditionally.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q1r2s3t4u5v6"
down_revision: str | None = "p0q1r2s3t4u5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_LATENCY_CONDITIONS = (
    "response_time_above",
    "response_time_above_baseline",
    "anomaly_detection",
)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        "UPDATE alert_rules SET condition = 'latency_anomaly' "
        "WHERE condition IN ('response_time_above', 'response_time_above_baseline', "
        "'anomaly_detection')"
    )

    rows_by_id = bind.execute(sa.text("SELECT id, rows FROM alert_matrix_templates")).fetchall()
    for tpl_id, rows in rows_by_id:
        new_rows = _merge_latency_rows(rows)
        if new_rows != rows:
            bind.execute(
                sa.text("UPDATE alert_matrix_templates SET rows = :rows WHERE id = :id"),
                {"rows": json.dumps(new_rows), "id": tpl_id},
            )


def _merge_latency_rows(rows: list[dict]) -> list[dict]:
    """Merge the three latency rows in one template's ``rows`` JSON.

    A template pairing two of the three as separate rows keeps only the
    absolute-threshold one — see the module docstring.
    """
    merged: list[dict] = []
    seen_latency = False
    for row in rows:
        condition = row.get("condition")
        if condition not in _OLD_LATENCY_CONDITIONS:
            merged.append(row)
            continue
        new_row = {**row, "condition": "latency_anomaly"}
        if seen_latency:
            for i, existing in enumerate(merged):
                if existing.get("condition") == "latency_anomaly":
                    if (
                        existing.get("threshold_value") is None
                        and new_row.get("threshold_value") is not None
                    ):
                        merged[i] = new_row
                    break
            continue
        merged.append(new_row)
        seen_latency = True
    return merged


def downgrade() -> None:
    bind = op.get_bind()

    rows_by_id = bind.execute(sa.text("SELECT id, rows FROM alert_matrix_templates")).fetchall()
    for tpl_id, rows in rows_by_id:
        new_rows = _split_latency_rows(rows)
        if new_rows != rows:
            bind.execute(
                sa.text("UPDATE alert_matrix_templates SET rows = :rows WHERE id = :id"),
                {"rows": json.dumps(new_rows), "id": tpl_id},
            )

    op.execute(
        "UPDATE alert_rules SET condition = 'response_time_above_baseline' "
        "WHERE condition = 'latency_anomaly' AND baseline_factor IS NOT NULL"
    )
    op.execute(
        "UPDATE alert_rules SET condition = 'anomaly_detection' "
        "WHERE condition = 'latency_anomaly' AND baseline_factor IS NULL "
        "AND anomaly_zscore_threshold IS NOT NULL"
    )
    op.execute(
        "UPDATE alert_rules SET condition = 'response_time_above' "
        "WHERE condition = 'latency_anomaly' AND baseline_factor IS NULL "
        "AND anomaly_zscore_threshold IS NULL"
    )


def _split_latency_rows(rows: list[dict]) -> list[dict]:
    reverted = []
    for row in rows:
        if row.get("condition") != "latency_anomaly":
            reverted.append(row)
            continue
        old = dict(row)
        if old.get("baseline_factor") is not None:
            old["condition"] = "response_time_above_baseline"
        elif old.get("anomaly_zscore_threshold") is not None:
            old["condition"] = "anomaly_detection"
        else:
            old["condition"] = "response_time_above"
        reverted.append(old)
    return reverted
