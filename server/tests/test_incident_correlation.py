"""Tests for incident correlation functions (_correlate_by_group, process_check_result)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentGroup, IncidentScope
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.incident import _correlate_by_group, _is_flapping, process_check_result

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


# ── _correlate_by_group ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correlate_by_group(
    service_db: AsyncSession,
    test_user: User,
    test_probe: Probe,
) -> None:
    """When ≥50% of monitors in a group go down within 2 minutes, an IncidentGroup is created."""
    # Create a group and two monitors belonging to it
    group = MonitorGroup(name="test-group", owner_id=test_user.id)
    service_db.add(group)
    await service_db.flush()

    mon_a = Monitor(
        name="mon-a",
        url="http://a.example.com",
        owner_id=test_user.id,
        group_id=group.id,
    )
    mon_b = Monitor(
        name="mon-b",
        url="http://b.example.com",
        owner_id=test_user.id,
        group_id=group.id,
    )
    service_db.add(mon_a)
    service_db.add(mon_b)
    await service_db.flush()

    now = datetime.now(UTC)

    # Open incident for mon_a (sibling already down)
    sibling_incident = Incident(
        monitor_id=mon_a.id,
        started_at=now - timedelta(seconds=30),
        scope=IncidentScope.global_,
        affected_probe_ids=[str(test_probe.id)],
    )
    service_db.add(sibling_incident)
    await service_db.flush()

    # Open incident for mon_b (the new one being processed)
    new_incident = Incident(
        monitor_id=mon_b.id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[str(test_probe.id)],
    )
    service_db.add(new_incident)
    await service_db.flush()

    collector = _EventCollector()
    await _correlate_by_group(service_db, new_incident, mon_b, collector)

    # Both incidents should now be in the same IncidentGroup
    await service_db.refresh(new_incident)
    assert new_incident.group_id is not None

    await service_db.refresh(sibling_incident)
    assert sibling_incident.group_id == new_incident.group_id

    # An IncidentGroup row with correlation_type="group" must exist
    ig = (
        await service_db.execute(
            select(IncidentGroup).where(IncidentGroup.id == new_incident.group_id)
        )
    ).scalar_one_or_none()
    assert ig is not None
    assert ig.correlation_type == "group"
    assert ig.status == "open"

    # A WebSocket event should have been emitted
    assert any(e["type"] == "common_cause_detected" for e in collector.events)


@pytest.mark.asyncio
async def test_correlate_by_group_no_group_id(
    service_db: AsyncSession,
    test_user: User,
    test_probe: Probe,
    test_monitor: Monitor,
) -> None:
    """_correlate_by_group is a no-op when the monitor has no group."""
    incident = Incident(
        monitor_id=test_monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(incident)
    await service_db.flush()

    collector = _EventCollector()
    # test_monitor has no group_id — function must return immediately
    await _correlate_by_group(service_db, incident, test_monitor, collector)

    assert incident.group_id is None
    assert collector.events == []


# ── process_check_result — creates incident ───────────────────────────────────


@pytest.mark.asyncio
async def test_process_check_result_creates_incident(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
) -> None:
    """A 'down' CheckResult processed through process_check_result opens an Incident."""
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
    opened_evt = next(e for e in collector.events if e["type"] == "incident_opened")
    assert opened_evt["monitor_id"] == str(test_monitor.id)


@pytest.mark.asyncio
async def test_process_check_result_no_duplicate_incident(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
) -> None:
    """Submitting a second 'down' result when an incident is already open does not
    create a second incident."""
    # Pre-existing open incident
    existing = Incident(
        monitor_id=test_monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=2),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(existing)
    await service_db.flush()

    result = await _add_result(service_db, test_monitor, test_probe, CheckStatus.down)
    collector = _EventCollector()

    await process_check_result(service_db, result, collector)

    # Still exactly one open incident
    incidents = (
        await service_db.execute(
            select(Incident).where(
                Incident.monitor_id == test_monitor.id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(incidents) == 1
    # No new "incident_opened" event
    assert not any(e["type"] == "incident_opened" for e in collector.events)


# ── flapping detection via process_check_result ───────────────────────────────


@pytest.mark.asyncio
async def test_flapping_detection(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
) -> None:
    """Alternating up/down results exceeding the flap threshold suppress incident creation."""
    # Build oscillating history: up/down/up/down/up — 4 transitions → below threshold (5)
    # Add one more cycle to reach 5 transitions total
    statuses = [
        CheckStatus.up,
        CheckStatus.down,
        CheckStatus.up,
        CheckStatus.down,
        CheckStatus.up,
        CheckStatus.down,
    ]
    base_time = datetime.now(UTC) - timedelta(minutes=len(statuses))
    for i, st in enumerate(statuses):
        await _add_result(
            service_db,
            test_monitor,
            test_probe,
            st,
            base_time + timedelta(minutes=i),
        )

    # Verify that _is_flapping considers the monitor flapping (5 transitions >= threshold 5)
    assert await _is_flapping(service_db, test_monitor) is True

    # Now submit a new "down" result — process_check_result should emit flapping_detected
    # and NOT open an incident
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
    flap_evt = next(e for e in collector.events if e["type"] == "flapping_detected")
    assert flap_evt["monitor_id"] == str(test_monitor.id)


@pytest.mark.asyncio
async def test_no_flapping_with_stable_results(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
) -> None:
    """Stable consecutive 'down' results are not detected as flapping."""
    now = datetime.now(UTC)
    for i in range(6):
        await _add_result(
            service_db,
            test_monitor,
            test_probe,
            CheckStatus.down,
            now - timedelta(minutes=6 - i),
        )

    assert await _is_flapping(service_db, test_monitor) is False

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
    assert not any(e["type"] == "flapping_detected" for e in collector.events)
