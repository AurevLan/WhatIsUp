"""Differentiated retention: raw window vs rollup horizon (plan V2, A-4).

Two properties are worth a test here, and they pull in opposite directions:

* the rollups **outlive** the raw window — that is the whole point of the table,
  and the thing a naive "one retention for everything" would undo;
* the raw purge **never overtakes** the rollup builder — a raw row deleted
  before it was folded is gone from both tables at once, so a short
  ``DATA_RETENTION_DAYS`` set while the backfill is still running would erase
  history permanently rather than compact it.

The second one is the reason the interlock exists at all, and it only shows up
in the case nobody tests by hand: a builder that is behind.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.core.database as db_mod
from tests.test_background_services import _FactoryStub
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.rollup import CheckRollup1h
from whatisup.models.user import User
from whatisup.services.retention import (
    _months_before,
    purge_old_results,
    purge_old_rollups,
)

# ── Calendar arithmetic ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("moment", "months", "expected"),
    [
        (datetime(2026, 8, 7, 3, 0, tzinfo=UTC), 13, datetime(2025, 7, 7, 3, 0, tzinfo=UTC)),
        (datetime(2026, 1, 15, tzinfo=UTC), 1, datetime(2025, 12, 15, tzinfo=UTC)),
        (datetime(2026, 1, 15, tzinfo=UTC), 12, datetime(2025, 1, 15, tzinfo=UTC)),
        # Target month shorter than the source day → clamp to its last day,
        # 2028 being a leap year and 2026 not.
        (datetime(2026, 3, 31, tzinfo=UTC), 1, datetime(2026, 2, 28, tzinfo=UTC)),
        (datetime(2028, 3, 31, tzinfo=UTC), 1, datetime(2028, 2, 29, tzinfo=UTC)),
    ],
)
def test_months_before_shifts_by_calendar_months(
    moment: datetime, months: int, expected: datetime
) -> None:
    assert _months_before(moment, months) == expected


def test_thirteen_months_is_more_than_a_year_whatever_the_month() -> None:
    """13 months must always clear a rolling year, or a YoY chart loses its start."""
    for month in range(1, 13):
        moment = datetime(2027, month, 15, tzinfo=UTC)
        assert moment - _months_before(moment, 13) > timedelta(days=365)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db(service_db: AsyncSession, monkeypatch):
    """Point the retention job's own session factory at the test session."""
    monkeypatch.setattr(db_mod, "_async_session_factory", _FactoryStub(service_db))
    return service_db


@pytest_asyncio.fixture
async def monitor(db: AsyncSession, test_user: User) -> Monitor:
    mon = Monitor(name="m-retention", url="http://x", owner_id=test_user.id)
    db.add(mon)
    await db.flush()
    return mon


def _rollup(monitor_id: uuid.UUID, bucket: datetime) -> CheckRollup1h:
    """A minimal but valid bucket — the counters do not matter to retention."""
    return CheckRollup1h(
        monitor_id=monitor_id,
        bucket=bucket.replace(minute=0, second=0, microsecond=0),
        sample_count=1,
        up_count=1,
        external_windows=1,
        external_up_windows=1,
        rt_count=1,
        rt_sum=10.0,
        rt_min=10.0,
        rt_max=10.0,
        p50_ms=10.0,
        p95_ms=10.0,
        p99_ms=10.0,
        computed_at=bucket,
    )


async def _count_rollups(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(CheckRollup1h))).scalar_one()


async def _count_results(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(CheckResult))).scalar_one()


# ── Rollup purge ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_drops_rollups_past_the_horizon_and_keeps_the_rest(
    db: AsyncSession, monitor: Monitor
):
    now = datetime.now(UTC)
    db.add_all(
        [
            _rollup(monitor.id, _months_before(now, 14)),  # over
            _rollup(monitor.id, _months_before(now, 13) - timedelta(hours=1)),  # just over
            _rollup(monitor.id, _months_before(now, 13) + timedelta(hours=1)),  # just under
            _rollup(monitor.id, now - timedelta(days=1)),
        ]
    )
    await db.flush()

    assert await purge_old_rollups(13) == 2
    assert await _count_rollups(db) == 2


@pytest.mark.asyncio
async def test_rollup_retention_zero_keeps_forever(db: AsyncSession, monitor: Monitor):
    db.add(_rollup(monitor.id, _months_before(datetime.now(UTC), 60)))
    await db.flush()

    assert await purge_old_rollups(0) == 0
    assert await _count_rollups(db) == 1


@pytest.mark.asyncio
async def test_rollups_outlive_the_raw_window(
    db: AsyncSession, monitor: Monitor, test_probe: Probe
):
    """The point of A-4: a 7-day raw window still leaves a year of history."""
    now = datetime.now(UTC)
    old = now - timedelta(days=200)
    db.add(_rollup(monitor.id, old))
    db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            status=CheckStatus.up,
            checked_at=old,
        )
    )
    # Builder is up to date, so the interlock does not hold the purge back.
    db.add(_rollup(monitor.id, now - timedelta(hours=1)))
    await db.flush()

    await purge_old_results(7)
    await purge_old_rollups(13)

    assert await _count_results(db) == 0
    assert await _count_rollups(db) == 2


# ── The interlock ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raw_purge_stops_at_the_builder_frontier(
    db: AsyncSession, monitor: Monitor, test_probe: Probe
):
    """A builder mid-backfill must not have the ground cut from under it.

    Rows older than the retention but *not yet folded* are exactly the ones a
    naive purge would delete first — and they would be gone from both tables.
    """
    now = datetime.now(UTC)
    # Folded up to 100 days ago; everything more recent is still raw-only.
    db.add(_rollup(monitor.id, now - timedelta(days=100)))
    for days in (150, 120, 90, 60):
        db.add(
            CheckResult(
                monitor_id=monitor.id,
                probe_id=test_probe.id,
                status=CheckStatus.up,
                checked_at=now - timedelta(days=days),
            )
        )
    await db.flush()

    # Asks for a 30-day window; only what predates the frontier may go.
    deleted = await purge_old_results(30)

    assert deleted == 2  # the 150 d and 120 d rows
    remaining = (await db.execute(select(CheckResult.checked_at))).scalars().all()
    ages = sorted(round((now - _aware(ts)).days) for ts in remaining)
    assert ages == [60, 90]


@pytest.mark.asyncio
async def test_interlock_applies_to_per_monitor_retention_too(
    db: AsyncSession, test_user: User, test_probe: Probe
):
    """Otherwise the guard is decorative: this path deletes rows as well."""
    now = datetime.now(UTC)
    short = Monitor(name="m-short", url="http://y", owner_id=test_user.id, data_retention_days=2)
    db.add(short)
    await db.flush()
    db.add(_rollup(short.id, now - timedelta(days=10)))
    for days in (20, 5):
        db.add(
            CheckResult(
                monitor_id=short.id,
                probe_id=test_probe.id,
                status=CheckStatus.up,
                checked_at=now - timedelta(days=days),
            )
        )
    await db.flush()

    assert await purge_old_results(90) == 1  # the 20 d row; the 5 d one is unfolded
    assert await _count_results(db) == 1


@pytest.mark.asyncio
async def test_no_interlock_when_rollups_are_disabled(
    db: AsyncSession, monitor: Monitor, test_probe: Probe, monkeypatch
):
    """With the builder switched off its watermark means nothing — and a frozen
    watermark would otherwise stop the purge forever, filling the disk."""
    from whatisup.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "rollup_enabled", False)

    now = datetime.now(UTC)
    db.add(_rollup(monitor.id, now - timedelta(days=300)))
    db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            status=CheckStatus.up,
            checked_at=now - timedelta(days=100),
        )
    )
    await db.flush()

    assert await purge_old_results(30) == 1


@pytest.mark.asyncio
async def test_empty_rollup_table_does_not_freeze_the_purge(
    db: AsyncSession, monitor: Monitor, test_probe: Probe
):
    """A builder that has not written its first bucket is not a reason to stop.

    It writes one within an interval of boot, long before the nightly job; a
    table still empty means the builder is broken, and blocking the purge on a
    broken builder trades data loss for disk exhaustion.
    """
    db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            status=CheckStatus.up,
            checked_at=datetime.now(UTC) - timedelta(days=100),
        )
    )
    await db.flush()

    assert await purge_old_results(30) == 1


def _aware(moment: datetime) -> datetime:
    """SQLite hands datetimes back naive."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
