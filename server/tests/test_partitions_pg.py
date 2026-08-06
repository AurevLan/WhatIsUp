"""check_results partitioning against a real PostgreSQL (plan V2, A-1).

Skipped unless ``PG_TEST_DATABASE_URL`` points at a database already migrated
to ``head`` — the CI job ``Alembic migrations`` sets it after its round-trip.
None of this can be exercised on SQLite: partition routing, the DEFAULT
partition safety net, index adoption and ``DROP TABLE``-based purge are all
PostgreSQL behaviour, and they are exactly the parts where being wrong means
either losing check results or destroying history that must be kept.
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
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User

PG_URL = os.environ.get("PG_TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="PG_TEST_DATABASE_URL not set"),
]

# Far enough ahead that no partition can already cover it, so rows land in the
# DEFAULT partition and the drain path is what creates the month.
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
    """Drop any far-future partition before and after each test.

    Several tests provision months ~18 ahead as a scratch area. A test that
    fails midway leaves one behind and the *next* run then fails somewhere
    unrelated — the kind of cascade that makes a suite look flaky when it is
    merely dirty. Nothing real lives that far ahead, so sweeping is safe.
    """

    async def _sweep() -> None:
        horizon = p.month_start(datetime.now(UTC))
        for _ in range(12):
            horizon = p.next_month(horizon)
        for name, upper in await p.list_check_result_partitions(pg_db):
            if upper is not None and upper > horizon:
                await pg_db.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await pg_db.commit()

    await _sweep()
    yield
    await _sweep()


@pytest_asyncio.fixture
async def seed(pg_db: AsyncSession):
    """A committed owner/monitor/probe triple, removed afterwards."""
    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"part-{tag}@example.com", username=f"part-{tag}", hashed_password="x")
    pg_db.add(owner)
    await pg_db.flush()
    monitor = Monitor(name=f"part-{tag}", url="http://example.com", owner_id=owner.id)
    probe = Probe(name=f"probe-{tag}", location_name="Paris", api_key_hash=f"x-{tag}")
    pg_db.add_all([monitor, probe])
    await pg_db.commit()
    # Read the ids out now: the teardown rolls back, which expires every
    # attribute and would re-query rows this very teardown is deleting.
    owner_id, probe_id = owner.id, probe.id
    yield monitor, probe
    await pg_db.rollback()
    await pg_db.execute(text("DELETE FROM users WHERE id = :i"), {"i": owner_id})
    await pg_db.execute(text("DELETE FROM probes WHERE id = :i"), {"i": probe_id})
    await pg_db.commit()


async def _partition_of(db: AsyncSession, result_id: uuid.UUID) -> str:
    row = await db.execute(
        text("SELECT tableoid::regclass::text FROM check_results WHERE id = :i"),
        {"i": result_id},
    )
    return row.scalar_one()


def _far_ahead(now: datetime) -> datetime:
    start = p.month_start(now)
    for _ in range(_FAR_AHEAD_MONTHS):
        start = p.next_month(start)
    return start


# ── Shape produced by migration e6f7a8b9c0d1 ─────────────────────────────────


async def test_parent_is_range_partitioned(pg_db: AsyncSession) -> None:
    # relkind is a PostgreSQL "char" — asyncpg hands it back as bytes unless
    # cast, and 'p' means "partitioned table".
    relkind = (
        await pg_db.execute(
            text(
                "SELECT relkind::text FROM pg_class "
                "WHERE relname = 'check_results' AND relnamespace = 'public'::regnamespace"
            )
        )
    ).scalar_one()
    assert relkind == "p"


async def test_legacy_and_default_partitions_exist(pg_db: AsyncSession) -> None:
    names = {name for name, _ in await p.list_check_result_partitions(pg_db)}
    assert p.LEGACY_PARTITION in names
    assert p.DEFAULT_PARTITION in names
    # The migration provisions head-room, so the current month is covered and
    # the next months have their own partitions.
    assert sum(1 for n in names if n.startswith("check_results_20")) >= 3


async def test_default_partition_is_never_dated(pg_db: AsyncSession) -> None:
    bounds = dict(await p.list_check_result_partitions(pg_db))
    assert bounds[p.DEFAULT_PARTITION] is None
    assert bounds[p.LEGACY_PARTITION] is not None


async def test_parent_indexes_are_valid_across_every_partition(pg_db: AsyncSession) -> None:
    """An invalid partitioned index means some partition is missing it.

    ``ix_check_results_monitor_checked`` is created ``ON ONLY`` and the legacy
    index attached to it; PostgreSQL only marks the parent index valid once
    every partition contributes one. It is also the index the LATERAL in
    ``fetch_latest_results`` depends on.
    """
    rows = (
        await pg_db.execute(
            text(
                "SELECT c.relname, i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE i.indrelid = 'check_results'::regclass"
            )
        )
    ).all()
    by_name = dict(rows)
    assert by_name["ix_check_results_monitor_checked"] is True
    assert by_name["ix_cr_checked_at_brin"] is True
    assert by_name["check_results_pkey"] is True


async def test_monitor_index_keeps_its_descending_order(pg_db: AsyncSession) -> None:
    """Losing DESC here silently degrades every "latest result" lookup."""
    definition = (
        await pg_db.execute(
            text("SELECT pg_get_indexdef('ix_check_results_monitor_checked'::regclass)")
        )
    ).scalar_one()
    assert "checked_at DESC" in definition


async def test_legacy_index_was_adopted_not_rebuilt(pg_db: AsyncSession) -> None:
    """The 428 MB index must be attached to the parent, not built a second time."""
    attached = (
        await pg_db.execute(
            text(
                "SELECT inhparent::regclass::text FROM pg_inherits "
                "WHERE inhrelid = 'ix_cr_legacy_monitor_checked'::regclass"
            )
        )
    ).scalar_one()
    assert attached == "ix_check_results_monitor_checked"


# ── Routing ──────────────────────────────────────────────────────────────────


async def test_rows_route_to_the_partition_of_their_month(pg_db: AsyncSession, seed) -> None:
    monitor, probe = seed
    # Two months ahead: provisioned by the migration, and past the legacy
    # partition's upper bound, so routing is actually exercised.
    target = p.next_month(p.next_month(p.month_start(datetime.now(UTC))))
    result = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=CheckStatus.up,
        checked_at=target + timedelta(days=3),
    )
    pg_db.add(result)
    await pg_db.flush()
    assert await _partition_of(pg_db, result.id) == p.partition_name(target)
    await pg_db.rollback()


async def test_current_rows_still_land_in_the_legacy_partition(pg_db: AsyncSession, seed) -> None:
    """The cut-over is the *next* month start, so no month is ever split."""
    monitor, probe = seed
    result = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=CheckStatus.up,
        checked_at=datetime.now(UTC),
    )
    pg_db.add(result)
    await pg_db.flush()
    assert await _partition_of(pg_db, result.id) == p.LEGACY_PARTITION
    await pg_db.rollback()


async def test_out_of_range_rows_land_in_default_instead_of_failing(
    pg_db: AsyncSession, seed
) -> None:
    """A probe with a broken clock must not be able to break ingestion."""
    monitor, probe = seed
    result = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=CheckStatus.up,
        checked_at=_far_ahead(datetime.now(UTC)) + timedelta(days=2),
    )
    pg_db.add(result)
    await pg_db.flush()
    assert await _partition_of(pg_db, result.id) == p.DEFAULT_PARTITION
    await pg_db.rollback()


# ── ensure_check_result_partitions ───────────────────────────────────────────


async def test_ensure_creates_missing_months_and_is_idempotent(pg_db: AsyncSession) -> None:
    base = _far_ahead(datetime.now(UTC))
    names = [p.partition_name(base), p.partition_name(p.next_month(base))]
    try:
        created = await p.ensure_check_result_partitions(pg_db, months_ahead=1, now=base)
        assert created == names
        assert await p.ensure_check_result_partitions(pg_db, months_ahead=1, now=base) == []
    finally:
        for name in names:
            await pg_db.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await pg_db.commit()


async def test_ensure_drains_rows_stranded_in_the_default_partition(
    pg_db: AsyncSession, seed
) -> None:
    """The whole point of the DEFAULT partition: rows are rescued, not stuck.

    PostgreSQL refuses to create a partition whose range still has rows sitting
    in the default one, so without the drain the month could never be created
    again — ingestion would keep piling into the default forever.
    """
    monitor, probe = seed
    base = _far_ahead(datetime.now(UTC))
    name = p.partition_name(base)
    result = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=CheckStatus.up,
        checked_at=base + timedelta(days=5),
    )
    pg_db.add(result)
    await pg_db.commit()
    result_id = result.id  # the teardown rollback expires the instance
    try:
        assert await _partition_of(pg_db, result_id) == p.DEFAULT_PARTITION

        created = await p.ensure_check_result_partitions(pg_db, months_ahead=0, now=base)
        assert created == [name]

        # The row moved to the real partition and is still readable through the
        # parent — nothing was lost in the move.
        assert await _partition_of(pg_db, result_id) == name
        stranded = (
            await pg_db.execute(
                text(f"SELECT count(*) FROM {p.DEFAULT_PARTITION} WHERE id = :i"),
                {"i": result_id},
            )
        ).scalar_one()
        assert stranded == 0
    finally:
        await pg_db.rollback()
        await pg_db.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await pg_db.execute(text("DELETE FROM check_results WHERE id = :i"), {"i": result_id})
        await pg_db.commit()


# ── drop_expired_check_result_partitions ─────────────────────────────────────


async def test_drop_expired_drops_exactly_what_it_can_prove_has_expired(
    pg_db: AsyncSession, monkeypatch
) -> None:
    """Real DROP TABLE, on a deliberately narrowed candidate list.

    A cutoff late enough to expire a partition is late enough to expire every
    older one too — including the legacy partition and the whole schema the
    other tests need. So the candidate list is scoped to three hand-made
    entries covering the three branches that matter: expired, still in range,
    and undatable (the DEFAULT partition, which must survive any cutoff).
    """
    base = _far_ahead(datetime.now(UTC))
    expired = p.partition_name(base)
    alive = p.partition_name(p.next_month(base))
    await p.ensure_check_result_partitions(pg_db, months_ahead=1, now=base)
    cutoff = p.next_month(base)

    async def _scoped(_db):
        return [
            (expired, cutoff),  # upper bound == cutoff → fully in the past
            (alive, p.next_month(cutoff)),  # still holds rows within retention
            (p.DEFAULT_PARTITION, None),  # no bound, nothing proves expiry
        ]

    monkeypatch.setattr(p, "list_check_result_partitions", _scoped)
    try:
        assert await p.drop_expired_check_result_partitions(pg_db, cutoff) == [expired]
        monkeypatch.undo()
        surviving = {n for n, _ in await p.list_check_result_partitions(pg_db)}
        assert expired not in surviving
        assert alive in surviving
        assert p.DEFAULT_PARTITION in surviving
        assert p.LEGACY_PARTITION in surviving
    finally:
        for name in (expired, alive):
            await pg_db.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await pg_db.commit()


async def test_drop_expired_is_a_no_op_on_a_freshly_migrated_schema(
    pg_db: AsyncSession,
) -> None:
    """Right after the migration, nothing has expired yet — nothing may go.

    The legacy partition's upper bound is the start of *next* month, so even a
    cutoff of "now" leaves every partition standing. A regression here would
    mean the very first nightly run destroys the whole history.
    """
    before = {n for n, _ in await p.list_check_result_partitions(pg_db)}
    assert await p.drop_expired_check_result_partitions(pg_db, datetime.now(UTC)) == []
    assert {n for n, _ in await p.list_check_result_partitions(pg_db)} == before
