"""Statistics served from rollups == statistics served from raw (plan V2, A-3).

A-3 makes ``stats.py`` read ``check_rollups_1h`` for the hours it covers. The
only acceptable outcome is that nobody can tell: the same data must produce the
same numbers whether or not the builder has run. Each test here therefore
computes a figure twice — once with an empty rollup table (the pre-A-3 path),
once after building — and compares.

The interesting case is not "all rollups" but the **mixed** window, where the
closed hours come from the rollup table and the hour in progress from the raw
one. That is what production always looks like.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.rollup import CheckRollup1h
from whatisup.models.user import User
from whatisup.services.rollup import build_rollups
from whatisup.services.stats import (
    compute_daily_history,
    compute_daily_history_bulk,
    compute_percentile_timeseries,
    compute_uptime_in_range,
)

pytestmark = pytest.mark.asyncio


async def _seed_history(
    db: AsyncSession,
    monitor: Monitor,
    probes: list[Probe],
    *,
    hours: int,
    now: datetime,
) -> None:
    """``hours`` hours of chequered history ending just before ``now``.

    Deliberately irregular: a down streak, a probe-specific failure the other
    probe covers (consensus), and latencies that vary per hour so percentiles
    and averages are not degenerate.
    """
    for hour_offset in range(hours, 0, -1):
        hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hour_offset)
        for minute in (0, 17, 33, 49):
            for index, probe in enumerate(probes):
                moment = hour_start + timedelta(minutes=minute, seconds=index * 7)
                failing = hour_offset % 11 == 0 or (index == 0 and minute == 33)
                db.add(
                    CheckResult(
                        id=uuid.uuid4(),
                        monitor_id=monitor.id,
                        probe_id=probe.id,
                        checked_at=moment,
                        status=CheckStatus.down if failing else CheckStatus.up,
                        response_time_ms=None if failing else float(40 + hour_offset * 3 + minute),
                    )
                )
    # The hour in progress — served from the raw table on both runs.
    for minute in (0, 20):
        db.add(
            CheckResult(
                id=uuid.uuid4(),
                monitor_id=monitor.id,
                probe_id=probes[0].id,
                checked_at=now.replace(minute=minute, second=0, microsecond=0),
                status=CheckStatus.up,
                response_time_ms=123.0,
            )
        )
    await db.flush()


@pytest.fixture
def now() -> datetime:
    # Mid-hour, mid-day: exercises both a partial trailing hour and a window
    # whose start falls inside an hour (the sliver the rollups cannot serve).
    return datetime.now(UTC).replace(minute=34, second=12, microsecond=0)


@pytest.fixture
async def fleet(service_db: AsyncSession, test_user: User, now: datetime):
    """A monitor watched by one internal and one external probe, plus history."""
    external = Probe(name="probe-ext", location_name="Paris", api_key_hash="x1")
    internal = Probe(name="probe-int", location_name="LAN", api_key_hash="x2")
    internal.network_type = NetworkType.internal
    monitor = Monitor(name="mon-parity", url="http://example.com", owner_id=test_user.id)
    service_db.add_all([external, internal, monitor])
    await service_db.flush()
    await _seed_history(service_db, monitor, [external, internal], hours=50, now=now)
    return monitor


async def _clear_rollups(db: AsyncSession) -> None:
    await db.execute(delete(CheckRollup1h))
    await db.flush()


async def test_daily_history_is_unchanged_by_rollups(
    service_db: AsyncSession, fleet: Monitor, now: datetime
):
    raw_only = await compute_daily_history(service_db, fleet.id, days=5)
    assert raw_only, "fixture must produce history"

    built = await build_rollups(service_db, now=now)
    # Guard against the test comparing the raw path with itself.
    assert built > 24
    mixed = await compute_daily_history(service_db, fleet.id, days=5)

    assert mixed == raw_only


async def test_daily_history_bulk_is_unchanged_by_rollups(
    service_db: AsyncSession, fleet: Monitor, now: datetime
):
    raw_only = await compute_daily_history_bulk(service_db, [fleet.id], days=5)
    await build_rollups(service_db, now=now)
    assert await compute_daily_history_bulk(service_db, [fleet.id], days=5) == raw_only


async def test_percentile_timeseries_is_unchanged_by_rollups(
    service_db: AsyncSession, fleet: Monitor, now: datetime
):
    """Rollup grain == bucket grain here, so this one must match to the digit."""
    raw_only = await compute_percentile_timeseries(service_db, fleet.id, hours=48)
    assert len(raw_only) > 24, "the window must span more than the covered tail"

    await build_rollups(service_db, now=now)
    assert await compute_percentile_timeseries(service_db, fleet.id, hours=48) == raw_only


async def test_uptime_in_range_is_unchanged_except_the_p95_estimate(
    service_db: AsyncSession, fleet: Monitor, now: datetime
):
    # Deliberately starts mid-hour: the leading sliver has to come from raw.
    from_ = now - timedelta(hours=40, minutes=23)
    raw_only = await compute_uptime_in_range(service_db, fleet.id, from_, now)
    assert raw_only["p95_is_estimate"] is False

    await build_rollups(service_db, now=now)
    mixed = await compute_uptime_in_range(service_db, fleet.id, from_, now)

    for key in (
        "total_checks",
        "up_checks",
        "uptime_percent",
        "internal_uptime_percent",
        "external_uptime_percent",
        "avg_response_time_ms",
        "min_response_time_ms",
        "max_response_time_ms",
    ):
        assert mixed[key] == raw_only[key], key
    # p95 is the one figure rollups cannot reconstruct exactly — it is a
    # weighted mean of hourly p95s, and says so.
    assert mixed["p95_is_estimate"] is True
    assert mixed["p95_response_time_ms"] == pytest.approx(
        raw_only["p95_response_time_ms"], rel=0.25
    )


async def test_window_narrower_than_an_hour_stays_on_raw(
    service_db: AsyncSession, fleet: Monitor, now: datetime
):
    """No whole covered hour fits → the rollups must not be consulted at all."""
    await build_rollups(service_db, now=now)
    from_ = now - timedelta(minutes=40)
    out = await compute_uptime_in_range(service_db, fleet.id, from_, now)
    assert out["p95_is_estimate"] is False
    assert out["total_checks"] > 0


async def test_history_is_stable_while_the_builder_lags(
    service_db: AsyncSession, fleet: Monitor, now: datetime
):
    """A builder halfway through its backfill must not truncate the history.

    The split point is derived, not assumed: whatever the builder has folded so
    far, the rest still comes from the raw table. Getting this wrong shows up
    as a status page that silently loses its oldest bars.
    """
    reference = await compute_daily_history(service_db, fleet.id, days=5)
    await _clear_rollups(service_db)

    # One capped run: only the oldest hours get folded, the rest is still raw.
    folded = await build_rollups(service_db, now=now, max_buckets=12, recompute_hours=0)
    assert 0 < folded < 50

    assert await compute_daily_history(service_db, fleet.id, days=5) == reference
