"""Tests for incident improvements: ack, atomic creation, SLA, renotify, digest persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.incident import process_check_result

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


# ── SLA: first_failure_at is set on incident creation ────────────────────────


@pytest.mark.asyncio
async def test_incident_has_first_failure_at(
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
    ).scalar_one()
    assert incident.first_failure_at is not None
    # SQLite strips timezone info, so compare without tz
    assert incident.first_failure_at.replace(tzinfo=None) == result.checked_at.replace(tzinfo=None)


# ── Ack clears on resolve ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ack_cleared_on_resolve(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    test_user: User,
) -> None:
    incident = Incident(
        monitor_id=test_monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
        acked_at=datetime.now(UTC),
        acked_by_id=test_user.id,
    )
    service_db.add(incident)
    await service_db.flush()

    # Submit an up result to resolve
    result = await _add_result(service_db, test_monitor, test_probe, CheckStatus.up)
    collector = _EventCollector()
    await process_check_result(service_db, result, collector)

    await service_db.refresh(incident)
    assert incident.resolved_at is not None
    assert incident.acked_at is None
    assert incident.acked_by_id is None


# ── Atomic incident creation (dedup) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_duplicate_open_incidents(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    # Create first incident via process_check_result
    result1 = await _add_result(service_db, test_monitor, test_probe, CheckStatus.down)
    await process_check_result(service_db, result1, _EventCollector())

    # Manually insert a second down result — should not create a second incident
    result2 = await _add_result(service_db, test_monitor, test_probe, CheckStatus.down)
    await process_check_result(service_db, result2, _EventCollector())

    open_incidents = (
        await service_db.execute(
            select(Incident).where(
                Incident.monitor_id == test_monitor.id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(open_incidents) == 1


# ── Ack endpoints (via API) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ack_endpoint(
    client,
    admin_token: str,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    from whatisup.models.monitor import Monitor

    monitor = Monitor(name="ack-test", url="http://ack.example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    db_session.add(incident)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}

    # Ack
    resp = await client.post(f"/api/v1/incidents/{incident.id}/ack", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["acked_at"] is not None
    assert data["acked_by_id"] == str(admin_user.id)

    # Unack
    resp = await client.post(f"/api/v1/incidents/{incident.id}/unack", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["acked_at"] is None
    assert data["acked_by_id"] is None


@pytest.mark.asyncio
async def test_ack_resolved_incident_fails(
    client,
    admin_token: str,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    monitor = Monitor(name="ack-resolved", url="http://x.example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    now = datetime.now(UTC)
    incident = Incident(
        monitor_id=monitor.id,
        started_at=now - timedelta(hours=1),
        resolved_at=now,
        duration_seconds=3600,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    db_session.add(incident)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(f"/api/v1/incidents/{incident.id}/ack", headers=headers)
    assert resp.status_code == 400


# ── SLA metrics in incident list ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_incidents_list_includes_sla(
    client,
    admin_token: str,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    monitor = Monitor(name="sla-test", url="http://sla.example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    now = datetime.now(UTC)
    incident = Incident(
        monitor_id=monitor.id,
        started_at=now - timedelta(minutes=10),
        resolved_at=now,
        duration_seconds=600,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
        first_failure_at=now - timedelta(minutes=11),
    )
    db_session.add(incident)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get("/api/v1/incidents/", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    inc_data = next(i for i in data if i["monitor_id"] == str(monitor.id))
    assert inc_data["mttd_seconds"] == 60
    assert inc_data["mttr_seconds"] == 600
