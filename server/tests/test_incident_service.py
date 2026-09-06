"""Tests for the incident detection service.

Flapping detection (``_is_flapping``) and direct incident open/resolve via
``process_check_result`` were removed/moved in plan Cap v2 4b: the legacy
per-probe decider retired, and availability incidents are now opened/resolved
exclusively through the Health Engine (``services.health.evaluate_slos`` /
``services.incident_slo``). The tests below exercise that path directly —
mirroring the real background flow in ``api/v1/probes.py``: ``process_check_result``
then ``health.ingest(..., publish_event=...)``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor, MonitorDependency
from whatisup.models.monitor_health import SLORule, SLORuleType
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services import health
from whatisup.services.incident import _is_suppressed_by_dependency, process_check_result

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


async def _add_default_slo_rule(db: AsyncSession, monitor: Monitor) -> SLORule:
    """Mirrors the rule crud.py auto-provisions on creation (plan Cap v2 4a):
    quorum_down, min_probes=1 — behaves like the legacy per-probe decider at
    a single probe."""
    rule = SLORule(
        monitor_id=monitor.id,
        rule_type=SLORuleType.quorum_down,
        enabled=True,
        quorum_ratio=0.6,
        window_seconds=300,
        min_probes=1,
        cooldown_seconds=60,
    )
    db.add(rule)
    await db.flush()
    return rule


async def _run_pipeline(db: AsyncSession, result: CheckResult, publish_event) -> None:
    await process_check_result(db, result, publish_event)
    await health.ingest(db, result, publish_event=publish_event)


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


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

    service_db.add(
        MonitorDependency(
            parent_id=parent.id, child_id=test_monitor.id, suppress_on_parent_down=True
        )
    )
    service_db.add(
        Incident(
            monitor_id=parent.id,
            started_at=datetime.now(UTC),
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
    )
    await service_db.flush()

    assert await _is_suppressed_by_dependency(service_db, test_monitor.id) is True


@pytest.mark.asyncio
async def test_suppressed_parent_incident_resolved(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor
) -> None:
    parent = Monitor(name="parent2", url="http://parent2.example.com", owner_id=test_user.id)
    service_db.add(parent)
    await service_db.flush()

    service_db.add(
        MonitorDependency(
            parent_id=parent.id, child_id=test_monitor.id, suppress_on_parent_down=True
        )
    )
    now = datetime.now(UTC)
    service_db.add(
        Incident(
            monitor_id=parent.id,
            started_at=now - timedelta(hours=1),
            resolved_at=now,
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
    )
    await service_db.flush()

    assert await _is_suppressed_by_dependency(service_db, test_monitor.id) is False


# ── process_check_result + health.ingest (Health Engine, plan Cap v2 4b) ──────


@pytest.mark.asyncio
async def test_process_opens_incident_when_down(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    await _add_default_slo_rule(service_db, test_monitor)
    result = await _add_result(service_db, test_monitor, test_probe, CheckStatus.down)
    collector = _EventCollector()

    await _run_pipeline(service_db, result, collector)

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
    assert incident.slo_rule_id is not None
    assert incident.trigger_kind == "quorum_down"
    assert any(e["type"] == "incident_opened" for e in collector.events)


@pytest.mark.asyncio
async def test_process_resolves_incident_when_up(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    rule = await _add_default_slo_rule(service_db, test_monitor)
    # Pre-existing open incident, tied to the active rule like open_incident_from_health
    # would have created it — resolution is keyed on (monitor_id, slo_rule_id).
    incident = Incident(
        monitor_id=test_monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
        slo_rule_id=rule.id,
        trigger_kind="quorum_down",
    )
    service_db.add(incident)
    await service_db.flush()

    result = await _add_result(service_db, test_monitor, test_probe, CheckStatus.up)
    collector = _EventCollector()

    await _run_pipeline(service_db, result, collector)

    await service_db.refresh(incident)
    assert incident.resolved_at is not None
    assert any(e["type"] == "incident_resolved" for e in collector.events)
