"""Retention for pushed metrics (plan V2, C-2).

``custom_metrics`` was, until C-2, the one time-series table nothing ever
purged: it grew for the lifetime of the deployment. What matters here is not
just that a purge exists but that it obeys the same rules as the raw results —
per-monitor override included — and that it stays in its own lane: purging
metrics must never touch check results, and vice versa.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.core.database as db_mod
from tests.test_background_services import _FactoryStub
from whatisup.models.custom_metric import CustomMetric
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.retention import purge_old_metrics, purge_old_results


@pytest_asyncio.fixture
async def db(service_db: AsyncSession, monkeypatch):
    monkeypatch.setattr(db_mod, "_async_session_factory", _FactoryStub(service_db))
    return service_db


@pytest_asyncio.fixture
async def monitor(db: AsyncSession, test_user: User) -> Monitor:
    mon = Monitor(name="m-metrics", url="http://x", owner_id=test_user.id)
    db.add(mon)
    await db.flush()
    return mon


def _metric(monitor_id, age_days: float, name: str = "queue_depth") -> CustomMetric:
    return CustomMetric(
        monitor_id=monitor_id,
        metric_name=name,
        value=42.0,
        unit="items",
        pushed_at=datetime.now(UTC) - timedelta(days=age_days),
    )


async def _count(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


@pytest.mark.asyncio
async def test_purge_deletes_metrics_past_the_window(db: AsyncSession, monitor: Monitor):
    db.add_all([_metric(monitor.id, 100), _metric(monitor.id, 95), _metric(monitor.id, 3)])
    await db.flush()

    assert await purge_old_metrics(90) == 2
    assert await _count(db, CustomMetric) == 1


@pytest.mark.asyncio
async def test_retention_zero_keeps_metrics_forever(db: AsyncSession, monitor: Monitor):
    """The escape hatch for the pre-C-2 behaviour: nothing was ever purged."""
    db.add(_metric(monitor.id, 3650))
    await db.flush()

    assert await purge_old_metrics(0) == 0
    assert await _count(db, CustomMetric) == 1


@pytest.mark.asyncio
async def test_per_monitor_retention_applies_to_metrics(
    db: AsyncSession, test_user: User, monitor: Monitor
):
    """A short per-monitor window means "no raw detail for this one" — and a
    pushed metric is raw detail of exactly that kind."""
    short = Monitor(name="m-short", url="http://y", owner_id=test_user.id, data_retention_days=2)
    db.add(short)
    await db.flush()
    db.add_all([_metric(short.id, 5), _metric(monitor.id, 5)])
    await db.flush()

    assert await purge_old_metrics(90) == 1
    remaining = (await db.execute(select(CustomMetric.monitor_id))).scalars().all()
    assert remaining == [monitor.id]


@pytest.mark.asyncio
async def test_metric_purge_leaves_check_results_alone(
    db: AsyncSession, monitor: Monitor, test_probe: Probe
):
    """Separate horizons, separate tables — a shared helper drives both, so the
    one thing worth pinning is that neither reaches into the other."""
    db.add(_metric(monitor.id, 100))
    db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            status=CheckStatus.up,
            checked_at=datetime.now(UTC) - timedelta(days=100),
        )
    )
    await db.flush()

    assert await purge_old_metrics(90) == 1
    assert await _count(db, CheckResult) == 1


@pytest.mark.asyncio
async def test_result_purge_leaves_metrics_alone(
    db: AsyncSession, monitor: Monitor, test_probe: Probe
):
    now = datetime.now(UTC)
    db.add(_metric(monitor.id, 100))
    db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            status=CheckStatus.up,
            checked_at=now - timedelta(days=100),
        )
    )
    await db.flush()

    assert await purge_old_results(90) == 1
    assert await _count(db, CustomMetric) == 1
