"""Declarative range partitioning for ``check_results`` (plan V2, A-1).

``check_results`` is the only table in the product whose size is driven by time
rather than by what the user configures: ~60 500 rows/day for 16 monitors, 3 GB
at a 90-day retention (measured, see plan_v2.md § "Résultats A-0"). It is now
``PARTITION BY RANGE (checked_at)`` with one partition per calendar month
(UTC), which buys two things:

* **Purge becomes ``DROP TABLE``** — O(1), no bloat, no autovacuum debt. The
  nightly ``DELETE`` of :mod:`whatisup.services.retention` was the worst
  possible write pattern for PostgreSQL on this table.
* **Partition pruning** on every query with a ``checked_at`` range, which is
  all of the analytical ones (``services/stats.py``).

Two invariants this module exists to hold:

1. **A partition must always exist for "now"**, otherwise every INSERT fails
   and the product stops recording anything. :func:`ensure_check_result_partitions`
   creates months ahead of time and runs both at startup and on a background
   loop.
2. **An out-of-range row must never be lost.** A probe with a broken clock can
   report a ``checked_at`` years away; a DEFAULT partition catches it instead
   of rejecting the whole batch. The cost is that creating the real partition
   for that month later requires draining the default first — which is exactly
   what :func:`ensure_check_result_partitions` falls back to.

Everything here is a no-op outside PostgreSQL: the test suite runs on SQLite,
which has no notion of partitions, and the ORM model is deliberately identical
on both (the ``postgresql_partition_by`` dialect kwarg is simply ignored).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import dialect_name

logger = structlog.get_logger(__name__)

PARENT_TABLE = "check_results"
DEFAULT_PARTITION = "check_results_default"

#: Partition holding everything that predates the cut-over migration. It spans
#: up to one full retention window, so it can only be dropped as a whole once
#: *all* of it has expired — until then the row-level DELETE still applies to
#: it. It ages out on its own and is never recreated.
LEGACY_PARTITION = "check_results_legacy"

#: Months of head-room created ahead of the current one. Three months means a
#: server that never restarts *and* whose background loop dies still records
#: results for a full quarter before anything lands in the default partition.
DEFAULT_MONTHS_AHEAD = 3

_BOUND_TO_RE = re.compile(r"TO \((.+)\)\s*$")


def reflected_partition_names(connection) -> set[str]:
    """Every table in the database that is a partition of another one.

    Used to keep partitions out of Alembic's sight (``alembic/env.py`` and
    ``scripts/check_model_drift.py``): they are real relations, so reflection
    finds them, but they are not in ``Base.metadata`` — autogenerate would
    propose to **drop every partition** and the model-drift gate would fail on
    a schema that is perfectly correct.

    Takes a *sync* ``Connection`` (that is what Alembic hands out).
    """
    if connection.dialect.name != "postgresql":
        return set()
    rows = connection.execute(text("SELECT relname FROM pg_class WHERE relispartition")).all()
    return {name for (name,) in rows}


def make_alembic_include_object(connection):
    """Build the ``include_object`` hook that hides partitions from autogenerate.

    The catalog lookup is deliberately **lazy**. Alembic only calls this hook
    during autogenerate, and querying the connection eagerly (at ``env.py``
    configure time) puts it in a transaction *before*
    ``context.begin_transaction()``: Alembic then treats the transaction as
    someone else's and never commits, so ``alembic upgrade head`` reports every
    migration as applied and leaves the database untouched. Exit code 0, empty
    schema, no error anywhere.
    """
    cache: dict[str, set[str]] = {}

    def include_object(object_, name, type_, reflected, compare_to):
        if not reflected:
            return True
        partitions = cache.get("names")
        if partitions is None:
            partitions = cache["names"] = reflected_partition_names(connection)
        if type_ == "table":
            return name not in partitions
        table = getattr(object_, "table", None)
        if table is not None and table.name in partitions:
            return False
        return True

    return include_object


def month_start(moment: datetime) -> datetime:
    """First instant of ``moment``'s UTC month."""
    moment = moment.astimezone(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(start: datetime) -> datetime:
    """First instant of the month following ``start``'s month.

    Normalises first so a mid-month or end-of-month argument cannot skip a
    month: 31 January + 32 days lands in March.
    """
    return month_start(month_start(start) + timedelta(days=32))


def partition_name(start: datetime) -> str:
    """Deterministic partition name for the month beginning at ``start``."""
    return f"{PARENT_TABLE}_{start.year:04d}_{start.month:02d}"


def _literal(moment: datetime) -> str:
    """A timestamptz literal safe to inline in DDL (no bind params in utility statements)."""
    return f"TIMESTAMPTZ '{moment.astimezone(UTC).isoformat()}'"


def _parse_upper_bound(bound: str) -> datetime | None:
    """Upper bound of a ``FOR VALUES FROM (…) TO (…)`` expression, or None.

    Returns None for the DEFAULT partition and for anything unparseable —
    callers treat that as "never droppable", which is the safe direction: a
    partition we cannot date is a partition we must not destroy.
    """
    bound = bound.strip()
    if not bound.startswith("FOR VALUES"):
        return None  # DEFAULT
    match = _BOUND_TO_RE.search(bound)
    if match is None:
        return None
    raw = match.group(1).strip()
    if not raw.startswith("'") or not raw.endswith("'"):
        return None  # MAXVALUE
    try:
        parsed = datetime.fromisoformat(raw[1:-1])
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def list_check_result_partitions(db: AsyncSession) -> list[tuple[str, datetime | None]]:
    """(name, upper bound) for every partition of ``check_results``.

    The upper bound is None for the DEFAULT partition and for any bound this
    module cannot parse.
    """
    if dialect_name(db) != "postgresql":
        return []
    rows = (
        await db.execute(
            text(
                "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) "
                "FROM pg_class c "
                "JOIN pg_inherits i ON i.inhrelid = c.oid "
                f"WHERE i.inhparent = '{PARENT_TABLE}'::regclass "
                "ORDER BY c.relname"
            )
        )
    ).all()
    return [(name, _parse_upper_bound(bound or "")) for name, bound in rows]


async def ensure_check_result_partitions(
    db: AsyncSession,
    *,
    months_ahead: int = DEFAULT_MONTHS_AHEAD,
    now: datetime | None = None,
) -> list[str]:
    """Create the missing monthly partitions from the current month onwards.

    Idempotent and safe to run concurrently on several replicas: a partition
    already created by another one simply isn't in the missing list, and a race
    on the same month surfaces as a duplicate-table error that is logged and
    skipped rather than crashing the loop.

    Returns the names actually created.
    """
    if dialect_name(db) != "postgresql":
        return []

    now = now or datetime.now(UTC)
    existing = {name for name, _ in await list_check_result_partitions(db)}
    created: list[str] = []

    start = month_start(now)
    for _ in range(months_ahead + 1):
        end = next_month(start)
        name = partition_name(start)
        if name not in existing:
            try:
                await _create_partition(db, name, start, end)
            except SQLAlchemyError as exc:
                # Never let one bad month stop the others: the current month is
                # created first, so the critical one is already in place. The
                # failed statement ran inside a SAVEPOINT, so the session (and
                # any partition created earlier in this loop) is still usable.
                logger.error(
                    "partition_create_failed",
                    partition=name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                created.append(name)
                logger.info("partition_created", partition=name, upper_bound=end.isoformat())
        start = end

    if created:
        await db.commit()
    return created


async def _create_partition(db: AsyncSession, name: str, start: datetime, end: datetime) -> None:
    """Attach one monthly partition, draining the default partition if needed.

    The fast path is a plain ``CREATE TABLE … PARTITION OF``. It fails with a
    check violation when the DEFAULT partition already holds rows belonging to
    the new range (a probe reported ahead of time, or the loop was down for
    months): PostgreSQL refuses to create a partition that would strand rows in
    the default. The slow path moves those rows into a standalone table and
    attaches *that*, so the rows end up where they belong instead of blocking
    partition creation forever.
    """
    bounds = f"FOR VALUES FROM ({_literal(start)}) TO ({_literal(end)})"
    try:
        async with db.begin_nested():
            await db.execute(
                text(f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF {PARENT_TABLE} {bounds}')
            )
        return
    except SQLAlchemyError as exc:
        # 23514 check_violation — the default partition holds matching rows.
        if "would be violated by some row" not in str(exc):
            raise

    logger.warning("partition_draining_default", partition=name)
    async with db.begin_nested():
        await db.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{name}" '
                f"(LIKE {PARENT_TABLE} INCLUDING DEFAULTS INCLUDING STORAGE)"
            )
        )
        moved = await db.execute(
            text(
                f"WITH moved AS ("
                f"  DELETE FROM {DEFAULT_PARTITION} "
                f"  WHERE checked_at >= {_literal(start)} AND checked_at < {_literal(end)} "
                f"  RETURNING *"
                f') INSERT INTO "{name}" SELECT * FROM moved'
            )
        )
        # A valid CHECK proving the partition constraint lets ATTACH skip its
        # validation scan of the (freshly filled) table.
        await db.execute(
            text(
                f'ALTER TABLE "{name}" ADD CONSTRAINT "{name}_range" '
                f"CHECK (checked_at >= {_literal(start)} AND checked_at < {_literal(end)})"
            )
        )
        await db.execute(text(f'ALTER TABLE {PARENT_TABLE} ATTACH PARTITION "{name}" {bounds}'))
        await db.execute(text(f'ALTER TABLE "{name}" DROP CONSTRAINT "{name}_range"'))
    logger.info("partition_drained_default", partition=name, rows=moved.rowcount)


async def drop_expired_check_result_partitions(db: AsyncSession, cutoff: datetime) -> list[str]:
    """Drop every partition whose whole range predates ``cutoff``.

    ``cutoff`` must be the *longest* retention in force, not the global one:
    a monitor with a longer ``data_retention_days`` still has its rows spread
    across the same partitions, and dropping one on the global cutoff alone
    would silently destroy history the user explicitly asked to keep.

    The DEFAULT partition is never dropped — it has no upper bound, so nothing
    can prove its contents have expired.
    """
    if dialect_name(db) != "postgresql":
        return []

    dropped: list[str] = []
    for name, upper in await list_check_result_partitions(db):
        if upper is None or upper > cutoff:
            continue
        await db.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        dropped.append(name)
        logger.info("partition_dropped", partition=name, upper_bound=upper.isoformat())
    if dropped:
        await db.commit()
    return dropped
