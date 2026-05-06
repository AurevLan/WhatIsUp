"""V2 Global Health Engine — coexistence with legacy pipeline (M2).

Verifies that two monitors processed in the same DB session — one with
``health_engine_enabled=True``, one without — produce incidents through
their respective deciders, with no cross-contamination.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import SLORule, SLORuleType
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services import health
from whatisup.services.incident import process_check_result


@pytest_asyncio.fixture
async def probe2(service_db: AsyncSession) -> Probe:
    p = Probe(name="probe-coex-2", location_name="NYC", api_key_hash="x")
    service_db.add(p)
    await service_db.flush()
    return p


@pytest_asyncio.fixture
async def legacy_monitor(service_db: AsyncSession, test_user: User) -> Monitor:
    m = Monitor(
        name="mon-legacy",
        url="http://legacy.test",
        owner_id=test_user.id,
        health_engine_enabled=False,
    )
    service_db.add(m)
    await service_db.flush()
    return m


@pytest_asyncio.fixture
async def health_monitor(service_db: AsyncSession, test_user: User) -> Monitor:
    m = Monitor(
        name="mon-health",
        url="http://health.test",
        owner_id=test_user.id,
        health_engine_enabled=True,
    )
    service_db.add(m)
    await service_db.flush()
    service_db.add(
        SLORule(
            monitor_id=m.id,
            rule_type=SLORuleType.quorum_down,
            enabled=True,
            quorum_ratio=0.5,
            window_seconds=300,
            min_probes=2,
            cooldown_seconds=0,
        )
    )
    await service_db.flush()
    return m


def _result(monitor: Monitor, probe: Probe, status: CheckStatus) -> CheckResult:
    return CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=status,
        response_time_ms=None,
        checked_at=datetime.now(UTC),
    )


async def _push_legacy(db: AsyncSession, cr: CheckResult, publish) -> None:
    """Replay the probes.py background flow without the health-engine call."""
    db.add(cr)
    await db.flush()
    await process_check_result(db, cr, publish)


async def _push_health(db: AsyncSession, cr: CheckResult, publish) -> None:
    db.add(cr)
    await db.flush()
    await process_check_result(db, cr, publish)
    await health.ingest(db, cr, publish_event=publish)


@pytest.mark.asyncio
async def test_legacy_monitor_uses_per_probe_decider(
    service_db: AsyncSession,
    legacy_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
) -> None:
    async def publish(_):
        return None

    # Legacy pipeline opens an incident as soon as any probe is down (scope=geographic)
    await _push_legacy(service_db, _result(legacy_monitor, test_probe, CheckStatus.down), publish)
    await _push_legacy(service_db, _result(legacy_monitor, probe2, CheckStatus.up), publish)

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == legacy_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    assert incidents[0].slo_rule_id is None
    assert incidents[0].trigger_kind == "legacy"


@pytest.mark.asyncio
async def test_health_monitor_uses_slo_decider(
    service_db: AsyncSession,
    health_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
) -> None:
    async def publish(_):
        return None

    # 1/2 probes down → below 0.5 threshold (strict ≥) — well actually 1/2=0.5 ≥ 0.5
    # Use 0/2 then 2/2 to have a clean test:
    await _push_health(service_db, _result(health_monitor, test_probe, CheckStatus.up), publish)
    await _push_health(service_db, _result(health_monitor, probe2, CheckStatus.up), publish)
    incidents_before = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == health_monitor.id)))
        .scalars()
        .all()
    )
    assert incidents_before == []

    # Both down → quorum 1.0 ≥ 0.5 → open via SLO
    await _push_health(service_db, _result(health_monitor, test_probe, CheckStatus.down), publish)
    await _push_health(service_db, _result(health_monitor, probe2, CheckStatus.timeout), publish)

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == health_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    assert incidents[0].slo_rule_id is not None
    assert incidents[0].trigger_kind == "quorum_down"


@pytest.mark.asyncio
async def test_no_cross_contamination_between_monitors(
    service_db: AsyncSession,
    legacy_monitor: Monitor,
    health_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
) -> None:
    """A health-engine monitor going down must NOT open an incident on the legacy monitor."""

    async def publish(_):
        return None

    await _push_health(service_db, _result(health_monitor, test_probe, CheckStatus.down), publish)
    await _push_health(service_db, _result(health_monitor, probe2, CheckStatus.down), publish)

    legacy_incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == legacy_monitor.id)))
        .scalars()
        .all()
    )
    assert legacy_incidents == []
