"""Drop the two redundant/unused check_results indexes (plan V2, A-0 bis).

Revision ID: f2a3b4c5d6e7
Revises: b2c3d4e5f6a8
Create Date: 2026-07-29

Measured on a 4.9M-row production table (3 065 MB total, of which 1 527 MB of
indexes — see plan_v2.md § "Résultats A-0"):

- ``ix_cr_probe_checked_at`` (probe_id, checked_at) — 372 MB, ``idx_scan = 0``
  over 5+ days of uptime. No query uses ``probe_id`` as a leading equality
  predicate: the per-probe aggregations (``api/v1/probes.py``,
  ``api/v1/monitors/stats.py``) filter on ``checked_at`` and only *group by*
  ``probe_id``, and ``latest_results_subq(group_col=CheckResult.probe_id)``
  (``services/incident.py``, ``services/network_verdict.py``) is always scoped
  by ``monitor_id`` first.
- ``ix_cr_monitor_checked_at`` (monitor_id, checked_at) — 480 MB, 3 849 scans,
  fully covered by ``ix_check_results_monitor_checked``
  (monitor_id, checked_at DESC) which took 1.7M scans: a btree is scannable in
  both directions, so the DESC index serves the ASC ordering too.

Total reclaimed: ~852 MB, i.e. 28 % of the table, with no refactor.
Both are plain btrees and are recreated verbatim by ``downgrade()``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "b2c3d4e5f6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cr_probe_checked_at")
    op.execute("DROP INDEX IF EXISTS ix_cr_monitor_checked_at")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cr_monitor_checked_at "
        "ON check_results (monitor_id, checked_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cr_probe_checked_at ON check_results (probe_id, checked_at)"
    )
