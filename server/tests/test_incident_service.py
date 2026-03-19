"""Tests for the incident detection service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor, MonitorDependency
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.incident import (
    _is_flapping,
    _is_suppressed_by_dependency,
    process_check_result,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _add_result(
    db: AsyncSession,
    monitor: Monitor,
    probe: Probe,
    status: CheckStatus,
    dt: datetime | None = None,
) -> CheckResult:
    r = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        checked_at=dt or datetime.now(UTC),
        status=status,
    )
    db.add(r)
    await db.flush()
    return r


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


# ── _is_flapping ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flapping_no_data(service_db: AsyncSession, test_monitor: Monitor) -> None:
    assert await _is_flapping(service_db, test_monitor) is False


@pytest.mark.asyncio
async def test_flapping_stable_down(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    for i in range(8):
        await _add_result(
            service_db, test_monitor, test_probe, CheckStatus.down,
            datetime.now(UTC) - timedelta(minutes=i),
        )
    assert await _is_flapping(service_db, test_monitor) is False


@pytest.mark.asyncio
async def test_flapping_detects_oscillation(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    statuses = [
        CheckStatus.up, CheckStatus.down, CheckStatus.up,
        CheckStatus.down, CheckStatus.up, CheckStatus.down,
    ]
    for i, st in enumerate(statuses):
        await _add_result(
            service_db, test_monitor, test_probe, st,
            datetime.now(UTC) - timedelta(minutes=i),
        )
    # 5 transitions >= default threshold (5) → flapping
    assert await _is_flapping(service_db, test_monitor) is True


# ── _is_suppressed_by_dependency ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suppressed_no_deps(service_db: AsyncSession, test_monitor: Monitor) -> None:
    assert await _is_suppressed_by_dependency(service_db, test_monitor.id) is False


@pytest.mark.asyncio
async def test_suppressed_parent_incident_open(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor
) -> None:
    parent = Monitor(name="parent", url="http://parent.example.com", owner_id=test_user.id)
    service_db.add(parent)
    await service_db.flush()

    service_db.add(MonitorDependency(
        parent_id=parent.id, child_id=test_monitor.id, suppress_on_parent_down=True
    ))
    service_db.add(Incident(
        monitor_id=parent.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    ))
    await service_db.flush()

    assert await _is_suppressed_by_dependency(service_db, test_monitor.id) is True


@pytest.mark.asyncio
async def test_suppressed_parent_incident_resolved(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor
) -> None:
    parent = Monitor(name="parent2", url="http://parent2.example.com", owner_id=test_user.id)
    service_db.add(parent)
    await service_db.flush()

    service_db.add(MonitorDependency(
        parent_id=parent.id, child_id=test_monitor.id, suppress_on_parent_down=True
    ))
    now = datetime.now(UTC)
    service_db.add(Incident(
        monitor_id=parent.id,
        started_at=now - timedelta(hours=1),
        resolved_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    ))
    await service_db.flush()

    assert await _is_suppressed_by_dependency(service_db, test_monitor.id) is False


# ── process_check_result ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_opens_incident_when_down(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    result = await _add_result(service_db, test_monitor, test_probe, CheckStatus.down)
    collector = _EventCollector()

    await process_check_result(service_db, result, collector)

    incident = (
        await service_db.execute(
            select(Incident).where(
                Incident.monitor_id == test_monitor.id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    assert incident is not None
    assert incident.scope == IncidentScope.global_
    assert any(e["type"] == "incident_opened" for e in collector.events)


@pytest.mark.asyncio
async def test_process_resolves_incident_when_up(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    # Pre-existing open incident
    incident = Incident(
        monitor_id=test_monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(incident)
    await service_db.flush()

    result = await _add_result(service_db, test_monitor, test_probe, CheckStatus.up)
    collector = _EventCollector()

    await process_check_result(service_db, result, collector)

    await service_db.refresh(incident)
    assert incident.resolved_at is not None
    assert any(e["type"] == "incident_resolved" for e in collector.events)


@pytest.mark.asyncio
async def test_process_no_incident_when_flapping(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    # Create oscillating history to trigger flap detection
    statuses = [
        CheckStatus.up, CheckStatus.down, CheckStatus.up,
        CheckStatus.down, CheckStatus.up,
    ]
    for i, st in enumerate(statuses):
        await _add_result(
            service_db, test_monitor, test_probe, st,
            datetime.now(UTC) - timedelta(minutes=5 - i),
        )

    # Now submit a down result — should be suppressed by flapping
    result = await _add_result(service_db, test_monitor, test_probe, CheckStatus.down)
    collector = _EventCollector()

    await process_check_result(service_db, result, collector)

    incident = (
        await service_db.execute(
            select(Incident).where(Incident.monitor_id == test_monitor.id)
        )
    ).scalar_one_or_none()
    assert incident is None
    assert any(e["type"] == "flapping_detected" for e in collector.events)
