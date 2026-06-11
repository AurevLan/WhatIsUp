"""Tests for the bulk uptime/history helpers used by the public status page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.stats import (
    compute_daily_history,
    compute_daily_history_bulk,
    compute_uptime_bulk,
)


async def _make_monitor(db: AsyncSession, user: User, name: str) -> Monitor:
    m = Monitor(name=name, url="http://example.com", owner_id=user.id)
    db.add(m)
    await db.flush()
    return m


async def _make_probe(db: AsyncSession, name: str) -> Probe:
    p = Probe(
        name=name,
        location_name="Paris",
        api_key_hash="x",
        network_type=NetworkType.external,
    )
    db.add(p)
    await db.flush()
    return p


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
                response_time_ms=100.0 if status == CheckStatus.up else None,
            )
        )


@pytest.mark.asyncio
async def test_compute_uptime_bulk_includes_avg_response_time(
    service_db: AsyncSession, test_user: User
) -> None:
    monitor = await _make_monitor(service_db, test_user, "bulk-avg")
    probe = await _make_probe(service_db, "p-bulk-avg")
    start = datetime.now(UTC) - timedelta(hours=1)
    _add_results(service_db, monitor, probe, start=start, count=10, status=CheckStatus.up)
    await service_db.flush()

    out = await compute_uptime_bulk(service_db, [monitor.id], period_hours=24)

    stats = out[str(monitor.id)]
    assert stats["uptime_percent"] == 100.0
    assert stats["avg_response_time_ms"] == 100.0


@pytest.mark.asyncio
async def test_compute_daily_history_bulk_matches_single(
    service_db: AsyncSession, test_user: User
) -> None:
    """The bulk variant must return the same entries as the per-monitor one."""
    mon_a = await _make_monitor(service_db, test_user, "bulk-hist-a")
    mon_b = await _make_monitor(service_db, test_user, "bulk-hist-b")
    probe = await _make_probe(service_db, "p-bulk-hist")

    now = datetime.now(UTC)
    _add_results(
        service_db, mon_a, probe, start=now - timedelta(days=2), count=20, status=CheckStatus.up
    )
    _add_results(
        service_db, mon_a, probe, start=now - timedelta(hours=2), count=10, status=CheckStatus.down
    )
    _add_results(
        service_db, mon_b, probe, start=now - timedelta(hours=3), count=15, status=CheckStatus.up
    )
    await service_db.flush()

    bulk = await compute_daily_history_bulk(service_db, [mon_a.id, mon_b.id], days=90)
    single_a = await compute_daily_history(service_db, mon_a.id, days=90)
    single_b = await compute_daily_history(service_db, mon_b.id, days=90)

    def _key_fields(entries: list[dict]) -> list[tuple]:
        return [(e["date"], e["total"], e["up_count"], e["uptime_percent"]) for e in entries]

    assert _key_fields(bulk[str(mon_a.id)]) == _key_fields(single_a)
    assert _key_fields(bulk[str(mon_b.id)]) == _key_fields(single_b)


@pytest.mark.asyncio
async def test_compute_daily_history_bulk_empty_ids(service_db: AsyncSession) -> None:
    assert await compute_daily_history_bulk(service_db, [], days=90) == {}
