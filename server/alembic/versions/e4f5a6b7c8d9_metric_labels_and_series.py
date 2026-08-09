"""Labels on pushed metrics + series registry (plan V2, C-1).

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-09

Why
───
Until now a pushed metric was identified by its name alone, so an application
could report ``http_latency`` but not ``http_latency`` *per route*. Labels turn
a name into a family of series, which is the whole point of pushing metrics
rather than reading a single aggregate.

It is also the classic way to destroy this kind of table. With one unbounded
label — a user id, a request id, a URL with an id in it — the row count stops
being governed by how often the application pushes and starts being governed by
how many distinct values it happens to observe. C-2 partitioned ``custom_metrics``
and gave it a retention window; neither helps against cardinality.

So the ceiling is enforced, and ``metric_series`` is what makes enforcing it
cheap: one row per distinct ``(monitor, name, labels)``, so the check is a
``COUNT(*)`` on a small table rather than a ``COUNT(DISTINCT …)`` across every
monthly partition of the points table.

Backfill
────────
Existing rows get ``labels = '{}'`` and the matching ``series_hash``, so every
metric pushed before this migration keeps working and shows up as a
label-less series. The registry is seeded from the distinct
``(monitor_id, metric_name)`` pairs already present, with their real first/last
timestamps — a monitor's history therefore appears in the UI immediately rather
than only after the next push.

``series_hash`` is computed in SQL to match ``models.custom_metric.series_hash``
exactly: ``sha256('{"n":<name>,"l":{}}')`` truncated to 32 hex chars. The
label-less canonical form is a constant shape, so it can be built with
``json_build_object`` without reimplementing the Python sorting rule — which
only matters once labels are non-empty, and no existing row has any.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# Mirrors models.custom_metric.series_hash for the empty-labels case:
#   json.dumps({"n": name, "l": {}}, separators=(",", ":"))
# json_build_object emits `{"n" : "x", "l" : {}}` with spaces, so the string is
# assembled by hand to match Python's separators byte for byte.
_EMPTY_LABEL_HASH = (
    "substr(encode(digest('{\"n\":' || to_json(metric_name)::text || ',\"l\":{}}', 'sha256'), "
    "'hex'), 1, 32)"
)


def upgrade() -> None:
    # ── Alert rules: which series, not just which name ────────────────────────
    # C-4 selected a series by ``metric_name`` alone, which was unambiguous only
    # while a name *was* a series. With labels a name is a family, so a rule
    # needs to say which member it watches. NULL keeps the C-4 behaviour — see
    # services/conditions/metrics.py for what a rule without a selector does
    # when the family has several members.
    op.add_column("alert_rules", sa.Column("metric_labels", _JSON, nullable=True))

    # ── Points: dimensions + denormalised series identity ─────────────────────
    op.add_column(
        "custom_metrics",
        sa.Column("labels", _JSON, nullable=False, server_default="{}"),
    )
    op.add_column(
        "custom_metrics",
        sa.Column("series_hash", sa.String(length=32), nullable=False, server_default=""),
    )

    # pgcrypto for digest(); available in every stock PostgreSQL image. If the
    # extension cannot be created the backfill below falls back to md5, which is
    # not the same hash — so fail loudly instead, and let the operator install it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(f"UPDATE custom_metrics SET series_hash = {_EMPTY_LABEL_HASH}")

    op.create_index(
        "ix_custom_metrics_series_time",
        "custom_metrics",
        ["monitor_id", "series_hash", "pushed_at"],
    )

    # ── Series registry ───────────────────────────────────────────────────────
    op.create_table(
        "metric_series",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "monitor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("labels", _JSON, nullable=False, server_default="{}"),
        sa.Column("series_hash", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("monitor_id", "series_hash", name="uq_metric_series_monitor_hash"),
    )
    op.create_index("ix_metric_series_monitor_id", "metric_series", ["monitor_id"])
    op.create_index("ix_metric_series_last_seen_at", "metric_series", ["last_seen_at"])
    op.create_index("ix_metric_series_monitor_name", "metric_series", ["monitor_id", "metric_name"])
    op.execute(
        "CREATE INDEX ix_metric_series_labels_gin ON metric_series "
        "USING gin (labels jsonb_path_ops)"
    )

    # Seed from what has already been pushed, with real timestamps so a
    # monitor's existing metrics are listable straight away.
    op.execute(
        f"""
        INSERT INTO metric_series
            (id, monitor_id, metric_name, labels, series_hash, unit,
             first_seen_at, last_seen_at)
        SELECT gen_random_uuid(),
               monitor_id,
               metric_name,
               '{{}}'::jsonb,
               {_EMPTY_LABEL_HASH},
               (array_agg(unit ORDER BY pushed_at DESC))[1],
               min(pushed_at),
               max(pushed_at)
          FROM custom_metrics
         GROUP BY monitor_id, metric_name
        """
    )


def downgrade() -> None:
    op.drop_column("alert_rules", "metric_labels")
    op.drop_table("metric_series")
    op.drop_index("ix_custom_metrics_series_time", table_name="custom_metrics")
    op.drop_column("custom_metrics", "series_hash")
    op.drop_column("custom_metrics", "labels")
