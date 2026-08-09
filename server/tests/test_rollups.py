"""Hourly rollup builder (plan V2, A-2).

The contract these tests hold is not "the numbers look plausible" but "a bucket
says exactly what the raw path would have said" — A-3 will swap ``stats.py``
over to this table, and any divergence would silently change every uptime figure
in the product. Hence :func:`test_daily_uptime_matches_raw_path`, which compares
rollup-derived daily uptime against ``compute_daily_history`` on the same data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.rollup import CheckRollup1h
from whatisup.services.rollup import build_rollups, percentile_cont
from whatisup.services.stats import compute_daily_history

pytestmark = pytest.mark.asyncio

# A fixed instant well inside a closed hour, so "now" never lands on a boundary
# and makes the partial-hour rule ambiguous.
NOW = datetime(2026, 8, 7, 12, 30, tzinfo=UTC)


async def _add_result(
    db: AsyncSession,
    monitor: Monitor,
    checked_at: datetime,
    *,
    status: CheckStatus = CheckStatus.up,
    response_time_ms: float | None = 100.0,
    probe: Probe | None = None,
) -> None:
    db.add(
        CheckResult(
            id=uuid.uuid4(),
            monitor_id=monitor.id,
            probe_id=probe.id if probe else None,
            checked_at=checked_at,
            status=status,
            response_time_ms=response_time_ms,
        )
    )
    await db.flush()


async def _rows(db: AsyncSession) -> list[CheckRollup1h]:
    # The builder writes through Core upserts, which the session's identity map
    # knows nothing about — without ``populate_existing`` a re-read hands back
    # the instance loaded before the rebuild, and every "did it update?"
    # assertion passes for the wrong reason.
    stmt = (
        select(CheckRollup1h)
        .order_by(CheckRollup1h.bucket)
        .execution_options(populate_existing=True)
    )
    return list((await db.execute(stmt)).scalars().all())


async def test_no_results_is_a_noop(service_db: AsyncSession):
    assert await build_rollups(service_db, now=NOW) == 0
    assert await _rows(service_db) == []


async def test_folds_a_closed_hour(service_db: AsyncSession, test_monitor: Monitor):
    hour = NOW.replace(hour=10, minute=0)
    for minute, (status, rt) in enumerate(
        [
            (CheckStatus.up, 100.0),
            (CheckStatus.up, 200.0),
            (CheckStatus.down, None),
            (CheckStatus.timeout, 5000.0),
        ]
    ):
        await _add_result(
            service_db,
            test_monitor,
            hour + timedelta(minutes=minute),
            status=status,
            response_time_ms=rt,
        )

    assert await build_rollups(service_db, now=NOW) == 1
    (row,) = await _rows(service_db)
    assert row.monitor_id == test_monitor.id
    assert row.sample_count == 4
    assert (row.up_count, row.down_count, row.timeout_count, row.error_count) == (2, 1, 1, 0)
    # No probe attached → every window counts as the external view.
    assert (row.external_windows, row.external_up_windows) == (4, 2)
    assert (row.internal_windows, row.internal_up_windows) == (0, 0)
    assert row.rt_count == 3
    assert row.rt_sum == pytest.approx(5300.0)
    assert (row.rt_min, row.rt_max) == (100.0, 5000.0)
    assert row.p50_ms == pytest.approx(200.0)


async def test_partial_hour_is_never_folded(service_db: AsyncSession, test_monitor: Monitor):
    """The in-progress hour keeps changing — consumers read it from the raw table."""
    await _add_result(service_db, test_monitor, NOW.replace(hour=11, minute=59))
    await _add_result(service_db, test_monitor, NOW)  # current hour

    assert await build_rollups(service_db, now=NOW) == 1
    (row,) = await _rows(service_db)
    assert row.bucket.replace(tzinfo=UTC) == NOW.replace(hour=11, minute=0)


async def test_consensus_is_cross_probe_per_minute(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
):
    """Two probes disagreeing in the same minute make one *up* window, not two.

    This is the reason the rollup grain is per monitor and not per probe: a
    per-probe row cannot express that probe B's success covered probe A's
    failure.
    """
    other = Probe(name="probe-lan", location_name="LAN", api_key_hash="x")
    other.network_type = NetworkType.internal
    service_db.add(other)
    await service_db.flush()

    minute = NOW.replace(hour=9, minute=5)
    await _add_result(service_db, test_monitor, minute, status=CheckStatus.down, probe=test_probe)
    await _add_result(
        service_db, test_monitor, minute + timedelta(seconds=20), probe=test_probe
    )  # up, same minute
    await _add_result(service_db, test_monitor, minute, status=CheckStatus.down, probe=other)

    await build_rollups(service_db, now=NOW)
    (row,) = await _rows(service_db)
    assert row.sample_count == 3
    # external view: one minute window, up (any probe up)
    assert (row.external_windows, row.external_up_windows) == (1, 1)
    # internal view: one minute window, down
    assert (row.internal_windows, row.internal_up_windows) == (1, 0)


async def test_rerun_is_idempotent_and_absorbs_late_rows(
    service_db: AsyncSession, test_monitor: Monitor
):
    hour = NOW.replace(hour=11, minute=0)
    await _add_result(service_db, test_monitor, hour)
    await build_rollups(service_db, now=NOW)

    # Same input twice → one row, same numbers.
    assert await build_rollups(service_db, now=NOW) == 1
    (row,) = await _rows(service_db)
    assert row.sample_count == 1

    # A result pushed after its hour closed still lands in the bucket, because
    # each run rewinds a few hours behind the watermark.
    await _add_result(service_db, test_monitor, hour + timedelta(minutes=30))
    await build_rollups(service_db, now=NOW)
    (row,) = await _rows(service_db)
    assert row.sample_count == 2


async def test_max_buckets_caps_a_run_then_catches_up(
    service_db: AsyncSession, test_monitor: Monitor
):
    for offset in range(5):
        await _add_result(service_db, test_monitor, NOW.replace(hour=5) + timedelta(hours=offset))

    assert await build_rollups(service_db, now=NOW, max_buckets=2, recompute_hours=0) == 2
    assert len(await _rows(service_db)) == 2

    for _ in range(5):  # bounded: a builder that cannot converge must fail, not hang
        if not await build_rollups(service_db, now=NOW, max_buckets=2, recompute_hours=0):
            break
    assert await build_rollups(service_db, now=NOW, max_buckets=2, recompute_hours=0) == 0
    assert len(await _rows(service_db)) == 5


async def test_long_gap_does_not_stall_the_loop(service_db: AsyncSession, test_monitor: Monitor):
    """A month with no results at all must be crossed, not re-scanned forever.

    Without snapping the start forward to the first hour that holds data, a
    capped run over an empty span writes nothing, the watermark never moves and
    the builder never reaches the recent rows.
    """
    await _add_result(service_db, test_monitor, NOW - timedelta(days=40))
    await _add_result(service_db, test_monitor, NOW - timedelta(hours=2))

    assert await build_rollups(service_db, now=NOW, max_buckets=24, recompute_hours=0) == 1
    assert await build_rollups(service_db, now=NOW, max_buckets=24, recompute_hours=0) == 1
    assert len(await _rows(service_db)) == 2


async def test_daily_uptime_matches_raw_path(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
):
    """Rollup-derived daily uptime == ``compute_daily_history`` on the same data."""
    # The only test here that cross-checks against a function reading the wall
    # clock: ``compute_daily_history`` windows on ``now - days``. Anchoring on
    # the module's frozen NOW would slide the day out of that window as real
    # time passes, and the comparison would then be against a truncated day.
    now = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    day = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    for hour in range(24):
        for minute in (0, 30):
            moment = day + timedelta(hours=hour, minutes=minute)
            # Two failing hours, so uptime is neither 0 nor 100.
            status = CheckStatus.down if hour in (3, 17) else CheckStatus.up
            await _add_result(
                service_db,
                test_monitor,
                moment,
                status=status,
                response_time_ms=float(50 + hour),
                probe=test_probe,
            )

    await build_rollups(service_db, now=now)
    rows = [r for r in await _rows(service_db) if r.bucket.replace(tzinfo=UTC).date() == day.date()]

    windows = sum(r.external_windows + r.internal_windows for r in rows)
    up_windows = sum(r.external_up_windows + r.internal_up_windows for r in rows)
    rt_count = sum(r.rt_count for r in rows)
    rt_sum = sum(r.rt_sum or 0.0 for r in rows)

    (expected,) = [
        entry
        for entry in await compute_daily_history(service_db, test_monitor.id, days=3)
        if entry["date"] == day.date().isoformat()
    ]
    assert windows == expected["total"]
    assert up_windows == expected["up_count"]
    assert round(up_windows / windows * 100, 2) == expected["uptime_percent"]
    assert round(rt_sum / rt_count, 1) == expected["avg_response_time_ms"]


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [
        ([], 0.5, None),
        ([42.0], 0.95, 42.0),
        ([1.0, 2.0, 3.0, 4.0], 0.5, 2.5),  # interpolated, like percentile_cont
        ([1.0, 2.0, 3.0, 4.0], 0.0, 1.0),
        ([1.0, 2.0, 3.0, 4.0], 1.0, 4.0),
    ],
)
async def test_percentile_cont(values, q, expected):
    assert percentile_cont(values, q) == expected
