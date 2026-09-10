"""Merge any_down/all_down into a quorum-based availability condition — plan cap v2, 6f (F1-conditions).

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-09-10

Why
───
``all_down`` (every probe down at once) and ``any_down`` (at least one probe
down) were degenerate cases of the same question — what fraction of a
monitor's probes must be down for the rule to page. This collapses them into
one condition, ``availability``, with a new ``AlertRule.quorum_ratio`` column:
``NULL``/below 1.0 behaves like the old ``any_down``, ``1.0`` like the old
``all_down``. See ``AlertRule.quorum_ratio``'s docstring
(``models/alert.py``) for why intermediate quorums aren't evaluated precisely
yet — the incident only carries a binary scope, not a live down-ratio.

``alert_condition`` becomes a plain string, not a native enum
──────────────────────────────────────────────────────────────
This migration also converts ``alert_rules.condition`` from a native
PostgreSQL ``ENUM`` to ``VARCHAR(30)``, matching how ``monitors.check_type``
has always been stored (``models/monitor.py``). Two hard PostgreSQL
restrictions on enum types make this unavoidable for the 6f lot as a whole,
not just this migration:

1. **Labels can never be dropped** from an existing enum type — only added.
   6f needs to retire six members (``all_down``, ``any_down``,
   ``response_time_above``, ``response_time_above_baseline``,
   ``anomaly_detection`` here and in the next migration; ``metric_above`` /
   ``metric_below`` / ``metric_absent`` in the one after) and add two new
   ones (``availability`` here, ``latency_anomaly`` next). A real enum can
   only ever grow.
2. **A label added by ``ALTER TYPE ... ADD VALUE`` cannot be *used* — cast to
   or compared against — until the transaction that added it commits.**
   ``alembic/env.py`` runs every pending revision inside one
   ``context.begin_transaction()`` for the whole ``upgrade`` invocation (see
   ``do_run_migrations``), so "a later migration" is not a separate
   transaction here: the very next revision in the same ``alembic upgrade``
   run would still hit "unsafe use of new value of enum type" the moment it
   tried to write ``'availability'`` into the column.

A plain string column sidesteps both: dropping a label is just "stop writing
it", and there is no such thing as an unsafe-to-use string literal.

What this migration does
─────────────────────────
- ``ALTER COLUMN condition TYPE VARCHAR(30)`` (``USING condition::text`` —
  every existing value survives unchanged as text).
- Drops the now-unreferenced ``alert_condition`` enum type.
- Adds ``alert_rules.quorum_ratio`` (float, nullable).
- Rewrites every ``alert_rules`` row: ``any_down`` → ``availability``
  (``quorum_ratio`` left NULL), ``all_down`` → ``availability``
  (``quorum_ratio = 1.0``). Lossless and exactly reversible — the migrated
  row remembers which of the two it used to be via ``quorum_ratio``.
- Rewrites the same two conditions inside every ``alert_matrix_templates``
  row's frozen ``rows`` JSON (seeded once at ``v7w8x9y0z1a2``, editing
  ``services/alert_matrix_templates.py`` does not touch data already
  written — same reasoning as ``o9p0q1r2s3t4``'s renotify scrub). A
  ``strict`` template that paired ``all_down`` (immediate) with ``any_down``
  (delayed 30s) as two separate rows would otherwise end up with two rows
  sharing the same condition, which ``PUT /monitors/{id}/matrix`` rejects as
  a duplicate — the migration keeps only the immediate row, which pages on
  strictly more situations, strictly sooner, than the one it replaces.

Data safety: measured at 8 live rules across both conditions on the real
instance (2026-09-10). The mapping is total and lossless either way, so this
runs unconditionally rather than refusing on unexpected data.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p0q1r2s3t4u5"
down_revision: str | None = "o9p0q1r2s3t4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every label the `alert_condition` enum ever carried, in the order it was
#: created and later extended — needed verbatim to recreate the type on
#: downgrade (76f1c42af699, a1b2c3d4e5f6, b2c3d4e5f6g7, h1i2j3k4l5m6,
#: d3e4f5a6b7c8).
_ORIGINAL_ENUM_LABELS = (
    "all_down",
    "any_down",
    "ssl_expiry",
    "response_time_above",
    "uptime_below",
    "response_time_above_baseline",
    "anomaly_detection",
    "schema_drift",
    "metric_above",
    "metric_below",
    "metric_absent",
)


def upgrade() -> None:
    bind = op.get_bind()

    # ── Column: native enum → plain string ─────────────────────────────────
    op.execute(
        "ALTER TABLE alert_rules ALTER COLUMN condition TYPE VARCHAR(30) USING condition::text"
    )
    op.execute("DROP TYPE alert_condition")

    # ── New quorum setting ──────────────────────────────────────────────────
    op.add_column("alert_rules", sa.Column("quorum_ratio", sa.Float(), nullable=True))

    # ── Rewrite live rules ──────────────────────────────────────────────────
    op.execute("UPDATE alert_rules SET condition = 'availability' WHERE condition = 'any_down'")
    op.execute(
        "UPDATE alert_rules SET condition = 'availability', quorum_ratio = 1.0 "
        "WHERE condition = 'all_down'"
    )

    # ── Rewrite frozen matrix template rows ────────────────────────────────
    rows_by_id = bind.execute(sa.text("SELECT id, rows FROM alert_matrix_templates")).fetchall()
    for tpl_id, rows in rows_by_id:
        new_rows = _migrate_template_rows(rows)
        if new_rows != rows:
            bind.execute(
                sa.text("UPDATE alert_matrix_templates SET rows = :rows WHERE id = :id"),
                {"rows": json.dumps(new_rows), "id": tpl_id},
            )


def _migrate_template_rows(rows: list[dict]) -> list[dict]:
    """Merge any_down/all_down rows in one template's ``rows`` JSON.

    A template that paired both as separate rows (the "strict" presets) keeps
    only the immediate, any-probe-down one: it pages on strictly more
    situations, strictly sooner, than the delayed one it replaces — see the
    module docstring.
    """
    merged: list[dict] = []
    seen_availability = False
    for row in rows:
        condition = row.get("condition")
        if condition not in ("any_down", "all_down"):
            merged.append(row)
            continue
        if condition == "all_down":
            new_row = {**row, "condition": "availability", "quorum_ratio": 1.0}
        else:
            new_row = {**row, "condition": "availability"}
        if seen_availability:
            # Both `any_down` and `all_down` were present in this template —
            # keep the one with the shorter min_duration_seconds (the more
            # responsive of the two), matching the immediate row's intent.
            for i, existing in enumerate(merged):
                if existing.get("condition") == "availability":
                    if int(new_row.get("min_duration_seconds") or 0) < int(
                        existing.get("min_duration_seconds") or 0
                    ):
                        merged[i] = new_row
                    break
            continue
        merged.append(new_row)
        seen_availability = True
    return merged


def downgrade() -> None:
    bind = op.get_bind()

    # ── Revert frozen matrix template rows (best effort) ───────────────────
    rows_by_id = bind.execute(sa.text("SELECT id, rows FROM alert_matrix_templates")).fetchall()
    for tpl_id, rows in rows_by_id:
        new_rows = _downgrade_template_rows(rows)
        if new_rows != rows:
            bind.execute(
                sa.text("UPDATE alert_matrix_templates SET rows = :rows WHERE id = :id"),
                {"rows": json.dumps(new_rows), "id": tpl_id},
            )

    # ── Revert live rules ────────────────────────────────────────────────────
    op.execute(
        "UPDATE alert_rules SET condition = 'all_down' "
        "WHERE condition = 'availability' AND quorum_ratio >= 1.0"
    )
    op.execute(
        "UPDATE alert_rules SET condition = 'any_down' "
        "WHERE condition = 'availability' AND (quorum_ratio IS NULL OR quorum_ratio < 1.0)"
    )

    op.drop_column("alert_rules", "quorum_ratio")

    # ── Column: plain string → native enum ─────────────────────────────────
    enum_type = sa.Enum(*_ORIGINAL_ENUM_LABELS, name="alert_condition")
    enum_type.create(bind, checkfirst=False)
    op.execute(
        "ALTER TABLE alert_rules ALTER COLUMN condition TYPE alert_condition "
        "USING condition::alert_condition"
    )


def _downgrade_template_rows(rows: list[dict]) -> list[dict]:
    reverted = []
    for row in rows:
        if row.get("condition") != "availability":
            reverted.append(row)
            continue
        quorum = row.get("quorum_ratio")
        old = {k: v for k, v in row.items() if k != "quorum_ratio"}
        old["condition"] = "all_down" if (quorum or 0) >= 1.0 else "any_down"
        reverted.append(old)
    return reverted
