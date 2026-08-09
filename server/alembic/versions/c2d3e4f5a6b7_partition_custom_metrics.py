"""Turn custom_metrics into a monthly range-partitioned table (plan V2, C-2).

Revision ID: c2d3e4f5a6b7
Revises: f7a8b9c0d1e2
Create Date: 2026-08-07

Why
───
``custom_metrics`` is the second table whose size is driven by time rather than
by configuration — and the only one whose ceiling is set by the *tenant's own
application* rather than by the check schedule. Until this migration it was also
the one time-series table with **no retention whatsoever**: nothing in
``services/retention.py`` ever touched it, so it grew without bound for the
lifetime of the deployment.

Fixing the retention alone would have meant a nightly ``DELETE`` — the write
pattern A-1 removed from ``check_results`` precisely because it is the worst one
for PostgreSQL (bloat plus autovacuum debt, every night, forever). So the table
gets the same treatment: ``PARTITION BY RANGE (pushed_at)``, one partition per
UTC month, purge by ``DROP TABLE``.

Doing it *now*, while the table is still small, is the point. The plan's C-1
(batch ingestion, labels) multiplies the row count by whatever an agent decides
to push; converting a flat table afterwards would be a data migration instead of
the near-instant rename below.

How — no bulk copy
──────────────────
Same trick as ``check_results`` (migration ``e6f7a8b9c0d1``), for the same
reason: the existing table is *renamed* and attached as-is as the first
partition, so no row is ever copied.

    custom_metrics ──rename──► custom_metrics_legacy ──ATTACH──► [MINVALUE, cutover)

``cutover`` is the start of the next UTC month, so no month is split between the
legacy partition and a monthly one. The legacy partition then ages out on its
own once its whole range is past retention.

Primary key
───────────
A partitioned table's unique constraints must contain the partition key, so the
PK becomes ``(id, pushed_at)``. ``id`` alone is no longer globally unique;
it is a client-side ``uuid4`` and nothing in the schema has a foreign key to
``custom_metrics``, so this is a formality.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from alembic import op
from sqlalchemy import text

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept in sync with whatisup.core.partitions (imported there rather than here so
# the migration stays independent of the application package).
_MONTHS_AHEAD = 3


def _month_start(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(start: datetime) -> datetime:
    # Normalise first: 31 January + 32 days would otherwise land in March.
    return _month_start(_month_start(start) + timedelta(days=32))


def _literal(moment: datetime) -> str:
    return f"TIMESTAMPTZ '{moment.isoformat()}'"


def _partition_name(start: datetime) -> str:
    return f"custom_metrics_{start.year:04d}_{start.month:02d}"


def _constraint_names(bind, table: str, contype: str) -> list[str]:
    """Names of ``table``'s constraints of a given ``pg_constraint.contype``.

    Discovered rather than hard-coded: an installation restored from a dump may
    spell PostgreSQL-generated constraint names differently.
    """
    # contype is a PostgreSQL "char" (one byte), which asyncpg will not let a
    # Python str bind to. Inlined instead; the whitelist below keeps that safe.
    assert contype in {"p", "f", "c"}
    rows = bind.execute(
        text(
            "SELECT conname FROM pg_constraint "
            f"WHERE conrelid = to_regclass(:t) AND contype = '{contype}' ORDER BY conname"
        ),
        {"t": table},
    ).all()
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (tests) has no partitioning; the ORM model is identical on both
        # because ``postgresql_partition_by`` is a dialect-scoped kwarg.
        return

    cutover = _next_month(_month_start(datetime.now(UTC)))

    # ── 1. Move the existing table out of the way, names included ────────────
    op.execute("ALTER TABLE custom_metrics RENAME TO custom_metrics_legacy")
    op.execute(
        "ALTER INDEX IF EXISTS ix_custom_metrics_monitor_time RENAME TO ix_cm_legacy_monitor_time"
    )
    # The parent owns the canonical constraint names; its foreign key and PK are
    # cloned onto every partition at ATTACH time, so keeping the legacy ones
    # would duplicate the work on every cascade and build the same index twice.
    for contype in ("f", "p"):
        for name in _constraint_names(bind, "custom_metrics_legacy", contype):
            op.execute(f'ALTER TABLE custom_metrics_legacy DROP CONSTRAINT "{name}"')

    # ── 1b. Park the rows the legacy partition cannot hold ───────────────────
    # ``pushed_at`` is client-supplied (the push payload may carry it), so rows
    # dated past the cut-over are entirely possible. They would fail the range
    # CHECK below and abort the migration; they are set aside and re-inserted
    # through the parent once the monthly partitions exist (§5b).
    op.execute("DROP TABLE IF EXISTS custom_metrics_future_hold")
    op.execute(
        "CREATE TABLE custom_metrics_future_hold "
        "(LIKE custom_metrics_legacy INCLUDING DEFAULTS INCLUDING STORAGE)"
    )
    op.execute(
        "WITH moved AS ("
        "  DELETE FROM custom_metrics_legacy "
        f"  WHERE pushed_at >= {_literal(cutover)} RETURNING *"
        ") INSERT INTO custom_metrics_future_hold SELECT * FROM moved"
    )

    # ── 2. The partitioned parent, shaped exactly like the old table ─────────
    op.execute(
        "CREATE TABLE custom_metrics "
        "(LIKE custom_metrics_legacy INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING STORAGE) "
        "PARTITION BY RANGE (pushed_at)"
    )
    op.execute(
        "ALTER TABLE custom_metrics ADD CONSTRAINT custom_metrics_monitor_id_fkey "
        "FOREIGN KEY (monitor_id) REFERENCES monitors (id) ON DELETE CASCADE"
    )

    # ── 3. Attach the old table as the historical partition ──────────────────
    # A *valid* CHECK proving the partition constraint is what lets ATTACH skip
    # its own scan of the heap.
    op.execute(
        "ALTER TABLE custom_metrics_legacy ADD CONSTRAINT custom_metrics_legacy_range "
        f"CHECK (pushed_at IS NOT NULL AND pushed_at < {_literal(cutover)})"
    )
    op.execute(
        "ALTER TABLE custom_metrics ATTACH PARTITION custom_metrics_legacy "
        f"FOR VALUES FROM (MINVALUE) TO ({_literal(cutover)})"
    )
    # Redundant once attached — the partition bound enforces the same thing.
    op.execute("ALTER TABLE custom_metrics_legacy DROP CONSTRAINT custom_metrics_legacy_range")

    # ── 4. Index: adopt the legacy one instead of rebuilding it ──────────────
    op.execute(
        "CREATE INDEX ix_custom_metrics_monitor_time ON ONLY custom_metrics (monitor_id, pushed_at)"
    )
    op.execute(
        "ALTER INDEX ix_custom_metrics_monitor_time ATTACH PARTITION ix_cm_legacy_monitor_time"
    )

    # ── 5. Future partitions + the safety net ────────────────────────────────
    # DEFAULT catches rows no monthly partition covers — here that is an agent
    # pushing a timestamp beyond the provisioned head-room, which must not cost
    # the tenant the data point. core.partitions drains it when it later creates
    # the real partition for that month.
    op.execute("CREATE TABLE custom_metrics_default PARTITION OF custom_metrics DEFAULT")
    start = cutover
    for _ in range(_MONTHS_AHEAD + 1):
        end = _next_month(start)
        op.execute(
            f'CREATE TABLE "{_partition_name(start)}" PARTITION OF custom_metrics '
            f"FOR VALUES FROM ({_literal(start)}) TO ({_literal(end)})"
        )
        start = end

    # ── 5b. Give the parked rows back, now that routing can place them ───────
    # Before the primary key exists, so the insert pays no index upkeep.
    op.execute("INSERT INTO custom_metrics SELECT * FROM custom_metrics_future_hold")
    op.execute("DROP TABLE custom_metrics_future_hold")

    # ── 6. Primary key, built once across every partition ────────────────────
    op.execute(
        "ALTER TABLE custom_metrics ADD CONSTRAINT custom_metrics_pkey PRIMARY KEY (id, pushed_at)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Detach the historical partition, fold every other partition's rows back
    # into it, then drop the parent. Unless it has already expired and been
    # dropped by the retention job, in which case the flat table is rebuilt.
    legacy_exists = (
        bind.execute(text("SELECT to_regclass('custom_metrics_legacy')")).scalar() is not None
    )
    if legacy_exists:
        op.execute("ALTER TABLE custom_metrics DETACH PARTITION custom_metrics_legacy")
    else:
        op.execute(
            "CREATE TABLE custom_metrics_legacy "
            "(LIKE custom_metrics INCLUDING DEFAULTS INCLUDING STORAGE)"
        )
    op.execute("INSERT INTO custom_metrics_legacy SELECT * FROM custom_metrics")
    op.execute("DROP TABLE custom_metrics")

    # Constraints cloned from the parent survive the detach under names
    # PostgreSQL chose; discover and replace them with the canonical ones.
    for contype in ("f", "p"):
        for name in _constraint_names(bind, "custom_metrics_legacy", contype):
            op.execute(f'ALTER TABLE custom_metrics_legacy DROP CONSTRAINT "{name}"')
    rows = bind.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = to_regclass('custom_metrics_legacy') AND contype = 'c' "
            "AND pg_get_constraintdef(oid) LIKE '%pushed_at%'"
        )
    ).all()
    for (name,) in rows:
        op.execute(f'ALTER TABLE custom_metrics_legacy DROP CONSTRAINT "{name}"')

    op.execute(
        "ALTER TABLE custom_metrics_legacy ADD CONSTRAINT custom_metrics_pkey PRIMARY KEY (id)"
    )
    op.execute(
        "ALTER TABLE custom_metrics_legacy ADD CONSTRAINT custom_metrics_monitor_id_fkey "
        "FOREIGN KEY (monitor_id) REFERENCES monitors (id) ON DELETE CASCADE"
    )
    op.execute("ALTER TABLE custom_metrics_legacy RENAME TO custom_metrics")
    op.execute(
        "ALTER INDEX IF EXISTS ix_cm_legacy_monitor_time RENAME TO ix_custom_metrics_monitor_time"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_custom_metrics_monitor_time "
        "ON custom_metrics (monitor_id, pushed_at)"
    )
