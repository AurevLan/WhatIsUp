"""custom_metrics partitioning against a real PostgreSQL (plan V2, C-2).

Skipped unless ``PG_TEST_DATABASE_URL`` points at a database already migrated
to ``head`` — the CI job ``Alembic migrations`` sets it after its round-trip.

The sibling file ``test_partitions_pg.py`` covers ``check_results``. What is
worth re-testing here rather than trusting by symmetry is precisely what the
generalisation of ``core.partitions`` could get wrong on the *second* table:
the spec's own time column (``pushed_at``, not ``checked_at``) has to reach the
DDL, the drain path and the drop. A spec that silently kept the first table's
column would still pass every check_results test.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whatisup.core import partitions as p
from whatisup.models.custom_metric import CustomMetric
from whatisup.models.monitor import Monitor
from whatisup.models.user import User

PG_URL = os.environ.get("PG_TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="PG_TEST_DATABASE_URL not set"),
]

SPEC = p.CUSTOM_METRICS

#: Far enough ahead that no partition can already cover it, so rows land in the
#: DEFAULT partition and the drain path is what creates the month.
_FAR_AHEAD_MONTHS = 18


@pytest_asyncio.fixture
async def pg_db():
    engine = create_async_engine(PG_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _sweep_far_partitions(pg_db: AsyncSession):
    """Drop scratch far-future partitions before and after each test.

    A test that fails midway would otherwise leave one behind and break the
    *next* run somewhere unrelated — flaky-looking, merely dirty.
    """

    async def _sweep() -> None:
        horizon = p.month_start(datetime.now(UTC))
        for _ in range(12):
            horizon = p.next_month(horizon)
        for name, upper in await p.list_partitions(pg_db, SPEC):
            if upper is not None and upper > horizon:
                await pg_db.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await pg_db.commit()

    await _sweep()
    yield
    await _sweep()


@pytest_asyncio.fixture
async def monitor(pg_db: AsyncSession):
    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"cm-{tag}@example.com", username=f"cm-{tag}", hashed_password="x")
    pg_db.add(owner)
    await pg_db.flush()
    mon = Monitor(name=f"cm-{tag}", url="http://example.com", owner_id=owner.id)
    pg_db.add(mon)
    await pg_db.commit()
    owner_id = owner.id
    yield mon
    await pg_db.rollback()
    await pg_db.execute(text("DELETE FROM users WHERE id = :i"), {"i": owner_id})
    await pg_db.commit()


def _far_ahead(now: datetime) -> datetime:
    start = p.month_start(now)
    for _ in range(_FAR_AHEAD_MONTHS):
        start = p.next_month(start)
    return start


async def _partition_of(db: AsyncSession, metric_id: uuid.UUID) -> str:
    row = await db.execute(
        text("SELECT tableoid::regclass::text FROM custom_metrics WHERE id = :i"),
        {"i": metric_id},
    )
    return row.scalar_one()


def _metric(monitor_id: uuid.UUID, pushed_at: datetime) -> CustomMetric:
    return CustomMetric(
        monitor_id=monitor_id,
        metric_name="queue_depth",
        value=1.0,
        unit="items",
        pushed_at=pushed_at,
    )


# ── Shape produced by migration c2d3e4f5a6b7 ─────────────────────────────────


async def test_parent_is_range_partitioned(pg_db: AsyncSession) -> None:
    relkind = (
        await pg_db.execute(
            text(
                "SELECT relkind::text FROM pg_class "
                "WHERE relname = 'custom_metrics' AND relnamespace = 'public'::regnamespace"
            )
        )
    ).scalar_one()
    assert relkind == "p"


async def test_partition_key_is_pushed_at(pg_db: AsyncSession) -> None:
    """The whole point of the spec: this table cuts on its *own* column."""
    key = (
        await pg_db.execute(
            text("SELECT pg_get_partkeydef('custom_metrics'::regclass)"),
        )
    ).scalar_one()
    assert key == "RANGE (pushed_at)"


async def test_legacy_and_default_partitions_exist(pg_db: AsyncSession) -> None:
    names = {name for name, _ in await p.list_partitions(pg_db, SPEC)}
    assert SPEC.legacy_partition in names
    assert SPEC.default_partition in names
    assert sum(1 for n in names if n.startswith("custom_metrics_20")) >= 3


async def test_primary_key_carries_the_partition_key(pg_db: AsyncSession) -> None:
    definition = (
        await pg_db.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'custom_metrics'::regclass AND contype = 'p'"
            )
        )
    ).scalar_one()
    assert "id" in definition and "pushed_at" in definition


async def test_index_is_valid_across_every_partition(pg_db: AsyncSession) -> None:
    """An invalid partitioned index means a partition is missing its copy —
    which is what happens if the legacy index was not attached."""
    rows = (
        await pg_db.execute(
            text(
                "SELECT c.relname, i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE i.indrelid = 'custom_metrics'::regclass"
            )
        )
    ).all()
    by_name = dict(rows)
    assert by_name["ix_custom_metrics_monitor_time"] is True
    assert by_name["custom_metrics_pkey"] is True


async def test_legacy_index_was_adopted_not_rebuilt(pg_db: AsyncSession) -> None:
    attached = (
        await pg_db.execute(
            text(
                "SELECT inhparent::regclass::text FROM pg_inherits "
                "WHERE inhrelid = 'ix_cm_legacy_monitor_time'::regclass"
            )
        )
    ).scalar_one()
    assert attached == "ix_custom_metrics_monitor_time"


# ── Routing ──────────────────────────────────────────────────────────────────


async def test_rows_route_to_the_partition_of_their_month(
    pg_db: AsyncSession, monitor: Monitor
) -> None:
    target = p.next_month(p.next_month(p.month_start(datetime.now(UTC))))
    metric = _metric(monitor.id, target + timedelta(days=3))
    pg_db.add(metric)
    await pg_db.commit()

    assert await _partition_of(pg_db, metric.id) == SPEC.partition_name(target)


async def test_out_of_range_rows_land_in_default_instead_of_failing(
    pg_db: AsyncSession, monitor: Monitor
) -> None:
    """A tenant agent can push any timestamp it likes. Rejecting the insert
    would cost the data point; the DEFAULT partition catches it."""
    metric = _metric(monitor.id, _far_ahead(datetime.now(UTC)) + timedelta(days=2))
    pg_db.add(metric)
    await pg_db.commit()

    assert await _partition_of(pg_db, metric.id) == SPEC.default_partition


# ── ensure / drain / drop, driven by the spec ────────────────────────────────


async def test_ensure_creates_missing_months_and_is_idempotent(pg_db: AsyncSession) -> None:
    base = _far_ahead(datetime.now(UTC))
    created = await p.ensure_partitions(pg_db, SPEC, months_ahead=1, now=base)

    assert created == [SPEC.partition_name(base), SPEC.partition_name(p.next_month(base))]
    assert await p.ensure_partitions(pg_db, SPEC, months_ahead=1, now=base) == []


async def test_ensure_drains_rows_stranded_in_the_default_partition(
    pg_db: AsyncSession, monitor: Monitor
) -> None:
    """The drain has to filter on ``pushed_at``. A generalisation that kept
    ``checked_at`` would fail here and nowhere else."""
    base = _far_ahead(datetime.now(UTC))
    metric = _metric(monitor.id, base + timedelta(days=1))
    pg_db.add(metric)
    await pg_db.commit()
    assert await _partition_of(pg_db, metric.id) == SPEC.default_partition

    created = await p.ensure_partitions(pg_db, SPEC, months_ahead=0, now=base)

    assert created == [SPEC.partition_name(base)]
    assert await _partition_of(pg_db, metric.id) == SPEC.partition_name(base)


async def test_drop_expired_drops_exactly_what_it_can_prove_has_expired(
    pg_db: AsyncSession,
) -> None:
    base = _far_ahead(datetime.now(UTC))
    await p.ensure_partitions(pg_db, SPEC, months_ahead=1, now=base)
    expired = SPEC.partition_name(base)
    kept = SPEC.partition_name(p.next_month(base))

    # A cutoff between the two: only the first one's whole range predates it.
    dropped = await p.drop_expired_partitions(pg_db, p.next_month(base), SPEC)

    assert expired in dropped
    assert kept not in dropped
    # Never the DEFAULT: nothing can prove an unbounded range has expired.
    assert SPEC.default_partition not in dropped


async def test_drop_expired_does_not_touch_check_results(pg_db: AsyncSession) -> None:
    """Specs must stay in their lane — a shared implementation makes crossing
    over a one-character mistake."""
    before = {name for name, _ in await p.list_check_result_partitions(pg_db)}
    base = _far_ahead(datetime.now(UTC))
    await p.ensure_partitions(pg_db, SPEC, months_ahead=0, now=base)
    await p.drop_expired_partitions(pg_db, p.next_month(base), SPEC)

    assert {name for name, _ in await p.list_check_result_partitions(pg_db)} == before


async def test_ensure_all_partitions_provisions_both_tables(pg_db: AsyncSession) -> None:
    result = await p.ensure_all_partitions(pg_db)
    assert set(result) == {"check_results", "custom_metrics"}
