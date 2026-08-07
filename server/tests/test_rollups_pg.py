"""Hourly rollups against a real PostgreSQL (plan V2, A-2).

Skipped unless ``PG_TEST_DATABASE_URL`` points at a database already migrated
to ``head`` — same harness as ``test_rollups_pg``'s sibling for partitions.

The SQLite suite covers the aggregation semantics. What it cannot cover is what
these tests are for:

* the percentiles the builder computes in Python must equal what PostgreSQL's
  ``percentile_cont`` returns on the same rows — otherwise A-3 shifts every
  latency chart the day it switches the endpoint over to the rollups;
* the upsert takes the PostgreSQL ``ON CONFLICT`` path, not the SQLite one;
* the raw read spans a *partitioned* table (A-1), including a bucket whose rows
  live in a partition of their own.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.rollup import CheckRollup1h
from whatisup.models.user import User
from whatisup.services.rollup import build_rollups, rebuild_range

PG_URL = os.environ.get("PG_TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="PG_TEST_DATABASE_URL not set"),
]


@pytest_asyncio.fixture
async def pg_db():
    engine = create_async_engine(PG_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


@pytest_asyncio.fixture
async def seed(pg_db: AsyncSession):
    """A committed owner/monitor/probe triple, removed afterwards.

    Deleting the monitor cascades to both ``check_results`` and
    ``check_rollups_1h``, so the teardown also proves the FK is in place.
    """
    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"roll-{tag}@example.com", username=f"roll-{tag}", hashed_password="x")
    pg_db.add(owner)
    await pg_db.flush()
    monitor = Monitor(name=f"roll-{tag}", url="http://example.com", owner_id=owner.id)
    probe = Probe(name=f"probe-{tag}", location_name="Paris", api_key_hash=f"x-{tag}")
    pg_db.add_all([monitor, probe])
    await pg_db.commit()
    owner_id, probe_id, monitor_id = owner.id, probe.id, monitor.id
    yield monitor, probe
    await pg_db.rollback()
    await pg_db.execute(text("DELETE FROM monitors WHERE id = :i"), {"i": monitor_id})
    await pg_db.execute(text("DELETE FROM users WHERE id = :i"), {"i": owner_id})
    await pg_db.execute(text("DELETE FROM probes WHERE id = :i"), {"i": probe_id})
    await pg_db.commit()


def _closed_hour() -> datetime:
    """An hour that is already over, so the builder is allowed to fold it."""
    return (datetime.now(UTC) - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)


async def _seed_results(
    db: AsyncSession, monitor: Monitor, probe: Probe, hour: datetime, latencies: list[float]
) -> None:
    for index, latency in enumerate(latencies):
        db.add(
            CheckResult(
                id=uuid.uuid4(),
                monitor_id=monitor.id,
                probe_id=probe.id,
                checked_at=hour + timedelta(seconds=index * 30),
                status=CheckStatus.up,
                response_time_ms=latency,
            )
        )
    await db.commit()


async def _bucket(db: AsyncSession, monitor: Monitor, hour: datetime) -> CheckRollup1h:
    stmt = (
        select(CheckRollup1h)
        .where(CheckRollup1h.monitor_id == monitor.id, CheckRollup1h.bucket == hour)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def test_percentiles_match_postgres(pg_db: AsyncSession, seed) -> None:
    monitor, probe = seed
    hour = _closed_hour()
    # Deliberately not round numbers and not sorted: interpolation between two
    # neighbours is exactly where a naive nearest-rank implementation diverges.
    latencies = [float(v) for v in (37, 412, 88, 1290, 155, 61, 903, 244, 19, 507, 77, 3312)]
    await _seed_results(pg_db, monitor, probe, hour, latencies)

    await rebuild_range(pg_db, hour, hour + timedelta(hours=1))
    row = await _bucket(pg_db, monitor, hour)

    expected = (
        await pg_db.execute(
            text(
                "SELECT percentile_cont(0.50) WITHIN GROUP (ORDER BY response_time_ms) AS p50, "
                "       percentile_cont(0.95) WITHIN GROUP (ORDER BY response_time_ms) AS p95, "
                "       percentile_cont(0.99) WITHIN GROUP (ORDER BY response_time_ms) AS p99, "
                "       avg(response_time_ms) AS avg, count(*) AS n "
                "FROM check_results WHERE monitor_id = :m "
                "AND checked_at >= :from AND checked_at < :to"
            ),
            {"m": monitor.id, "from": hour, "to": hour + timedelta(hours=1)},
        )
    ).one()

    assert row.rt_count == expected.n
    assert row.p50_ms == pytest.approx(expected.p50)
    assert row.p95_ms == pytest.approx(expected.p95)
    assert row.p99_ms == pytest.approx(expected.p99)
    assert row.rt_sum / row.rt_count == pytest.approx(float(expected.avg))


async def test_upsert_rebuilds_an_existing_bucket(pg_db: AsyncSession, seed) -> None:
    """Second pass over the same hour updates the row instead of erroring.

    On PostgreSQL this exercises ``INSERT … ON CONFLICT (monitor_id, bucket) DO
    UPDATE``; a missing conflict target would surface here as a unique
    violation, not as a wrong number.
    """
    monitor, probe = seed
    hour = _closed_hour()
    await _seed_results(pg_db, monitor, probe, hour, [100.0, 200.0])
    await rebuild_range(pg_db, hour, hour + timedelta(hours=1))
    assert (await _bucket(pg_db, monitor, hour)).sample_count == 2

    # A result that arrived late, after its hour was already folded.
    await _seed_results(pg_db, monitor, probe, hour + timedelta(minutes=40), [300.0])
    await rebuild_range(pg_db, hour, hour + timedelta(hours=1))

    row = await _bucket(pg_db, monitor, hour)
    assert row.sample_count == 3
    assert row.rt_max == 300.0


async def test_build_rollups_walks_the_resume_path(pg_db: AsyncSession, seed) -> None:
    """End-to-end run of the loop's entry point on PostgreSQL.

    The resume point is derived from ``max(bucket)`` and ``min(checked_at)``,
    which asyncpg returns as *aware* datetimes where SQLite returns naive ones —
    the one piece of the builder the SQLite suite exercises on the wrong type.
    """
    monitor, probe = seed
    hour = _closed_hour()
    await _seed_results(pg_db, monitor, probe, hour, [42.0, 84.0])

    # A wide rewind so the run covers ``hour`` whatever earlier tests left in
    # the shared database, and no cap so it is reached in a single pass.
    await build_rollups(pg_db, max_buckets=24 * 400, recompute_hours=48)

    assert (await _bucket(pg_db, monitor, hour)).sample_count == 2


async def test_reads_across_partitions(pg_db: AsyncSession, seed) -> None:
    """The raw read must span partitions, not just the current month's.

    ``check_results`` is partitioned by month (A-1); an hour near a month
    boundary and an hour in the previous month land in different physical
    tables, and the builder has to fold both.
    """
    monitor, probe = seed
    recent = _closed_hour()
    older = recent - timedelta(days=35)
    await _seed_results(pg_db, monitor, probe, older, [10.0])
    await _seed_results(pg_db, monitor, probe, recent, [20.0])

    await rebuild_range(pg_db, older, older + timedelta(hours=1))
    await rebuild_range(pg_db, recent, recent + timedelta(hours=1))

    assert (await _bucket(pg_db, monitor, older)).sample_count == 1
    assert (await _bucket(pg_db, monitor, recent)).sample_count == 1
