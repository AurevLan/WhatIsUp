"""Multi-probe consensus uptime computation.

These tests pin the rule that a monitor is "down" for a time window only when
**all** probes in the same network view see it down. A single broken probe
should not drag the displayed uptime below 100%.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.stats import compute_uptime, compute_uptime_in_range


def _add_results(
    db: AsyncSession,
    monitor: Monitor,
    probe: Probe,
    *,
    start: datetime,
    count: int,
    status: CheckStatus,
    interval_seconds: int = 60,
) -> None:
    for i in range(count):
        db.add(
            CheckResult(
                monitor_id=monitor.id,
                probe_id=probe.id,
                checked_at=start + timedelta(seconds=interval_seconds * i),
                status=status,
                response_time_ms=120.0 if status == CheckStatus.up else None,
            )
        )


@pytest.mark.asyncio
async def test_one_broken_probe_does_not_lower_uptime(
    service_db: AsyncSession, test_user: User
) -> None:
    """A probe that always reports down while others report up must not pull
    the consensus uptime below 100%."""
    monitor = Monitor(name="mon-broken-probe", url="http://example.com", owner_id=test_user.id)
    service_db.add(monitor)
    await service_db.flush()

    healthy = Probe(
        name="p-healthy", location_name="Paris", api_key_hash="x",
        network_type=NetworkType.external,
    )
    broken = Probe(
        name="p-broken", location_name="NYC", api_key_hash="y",
        network_type=NetworkType.external,
    )
    service_db.add_all([healthy, broken])
    await service_db.flush()

    start = datetime.now(UTC) - timedelta(hours=1)
    _add_results(service_db, monitor, healthy, start=start, count=30, status=CheckStatus.up)
    _add_results(service_db, monitor, broken, start=start, count=30, status=CheckStatus.down)
    await service_db.flush()

    stats = await compute_uptime(service_db, monitor.id, period_hours=24)

    assert stats.uptime_percent == 100.0
    assert stats.external_uptime_percent == 100.0
    assert stats.internal_uptime_percent is None
    assert stats.up_checks == stats.total_checks


@pytest.mark.asyncio
async def test_all_probes_down_yields_zero_uptime(
    service_db: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(name="mon-all-down", url="http://example.com", owner_id=test_user.id)
    service_db.add(monitor)
    await service_db.flush()

    p1 = Probe(name="p1", location_name="A", api_key_hash="x", network_type=NetworkType.external)
    p2 = Probe(name="p2", location_name="B", api_key_hash="y", network_type=NetworkType.external)
    service_db.add_all([p1, p2])
    await service_db.flush()

    start = datetime.now(UTC) - timedelta(hours=1)
    _add_results(service_db, monitor, p1, start=start, count=10, status=CheckStatus.down)
    _add_results(service_db, monitor, p2, start=start, count=10, status=CheckStatus.down)
    await service_db.flush()

    stats = await compute_uptime(service_db, monitor.id, period_hours=24)
    assert stats.uptime_percent == 0.0
    assert stats.external_uptime_percent == 0.0


@pytest.mark.asyncio
async def test_internal_view_down_external_view_up(
    service_db: AsyncSession, test_user: User
) -> None:
    """A regional outage where the internal view is down but external is up
    must surface as 0% on internal_uptime_percent and 100% on external,
    and the global uptime must take the worst of the two views."""
    monitor = Monitor(name="mon-split-view", url="http://example.com", owner_id=test_user.id)
    service_db.add(monitor)
    await service_db.flush()

    internal = Probe(
        name="p-int", location_name="HQ", api_key_hash="x", network_type=NetworkType.internal,
    )
    external = Probe(
        name="p-ext", location_name="Cloud", api_key_hash="y", network_type=NetworkType.external,
    )
    service_db.add_all([internal, external])
    await service_db.flush()

    start = datetime.now(UTC) - timedelta(hours=1)
    _add_results(service_db, monitor, internal, start=start, count=20, status=CheckStatus.down)
    _add_results(service_db, monitor, external, start=start, count=20, status=CheckStatus.up)
    await service_db.flush()

    stats = await compute_uptime(service_db, monitor.id, period_hours=24)
    assert stats.internal_uptime_percent == 0.0
    assert stats.external_uptime_percent == 100.0
    # Global uptime takes the worst view so the regional outage stays visible.
    assert stats.uptime_percent == 0.0


@pytest.mark.asyncio
async def test_compute_uptime_in_range_uses_consensus(
    service_db: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(name="mon-range", url="http://example.com", owner_id=test_user.id)
    service_db.add(monitor)
    await service_db.flush()

    healthy = Probe(
        name="ph", location_name="Paris", api_key_hash="x",
        network_type=NetworkType.external,
    )
    broken = Probe(
        name="pb", location_name="NYC", api_key_hash="y",
        network_type=NetworkType.external,
    )
    service_db.add_all([healthy, broken])
    await service_db.flush()

    start = datetime.now(UTC) - timedelta(hours=2)
    _add_results(service_db, monitor, healthy, start=start, count=20, status=CheckStatus.up)
    _add_results(service_db, monitor, broken, start=start, count=20, status=CheckStatus.down)
    await service_db.flush()

    out = await compute_uptime_in_range(
        service_db,
        monitor.id,
        from_=start - timedelta(minutes=1),
        to=datetime.now(UTC),
    )
    assert out["uptime_percent"] == 100.0
    assert out["external_uptime_percent"] == 100.0


@pytest.mark.asyncio
async def test_no_results_returns_full_uptime(
    service_db: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(name="mon-empty", url="http://example.com", owner_id=test_user.id)
    service_db.add(monitor)
    await service_db.flush()

    stats = await compute_uptime(service_db, monitor.id, period_hours=24)
    assert stats.uptime_percent == 100.0
    assert stats.total_checks == 0
    assert stats.internal_uptime_percent is None
    assert stats.external_uptime_percent is None
