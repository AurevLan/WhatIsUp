"""V2 Global Health Engine — M0 model + ingest skeleton tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import MonitorHealthState, SLORule, SLORuleType
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services import health


@pytest.mark.asyncio
async def test_monitor_health_engine_enabled_by_default(
    service_db: AsyncSession, test_monitor: Monitor
) -> None:
    """Plan Cap v2 4b: the column default flipped to True — there is no
    other detection path for a Monitor built without going through
    MonitorCreate (or this test fixture) to fall back to."""
    fresh = await service_db.get(Monitor, test_monitor.id)
    assert fresh is not None
    assert fresh.health_engine_enabled is True


@pytest.mark.asyncio
async def test_ensure_state_is_idempotent(service_db: AsyncSession, test_monitor: Monitor) -> None:
    s1 = await health.ensure_state(service_db, test_monitor.id)
    s2 = await health.ensure_state(service_db, test_monitor.id)
    assert s1.monitor_id == s2.monitor_id == test_monitor.id
    rows = (
        (
            await service_db.execute(
                select(MonitorHealthState).where(MonitorHealthState.monitor_id == test_monitor.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].probes_state == {}
    assert rows[0].probe_health == {}
    assert rows[0].sample_count_5m == 0
    assert rows[0].quorum_down_ratio == 0.0


@pytest.mark.asyncio
async def test_ingest_bumps_updated_at(
    service_db: AsyncSession, test_monitor: Monitor, test_probe
) -> None:
    cr = CheckResult(
        monitor_id=test_monitor.id,
        probe_id=test_probe.id,
        status=CheckStatus.up,
        checked_at=datetime.now(UTC),
        response_time_ms=42.0,
    )
    service_db.add(cr)
    await service_db.flush()

    await health.ingest(service_db, cr)

    state = (
        await service_db.execute(
            select(MonitorHealthState).where(MonitorHealthState.monitor_id == test_monitor.id)
        )
    ).scalar_one()
    assert state.updated_at is not None


@pytest.mark.asyncio
async def test_slo_rule_crud(service_db: AsyncSession, test_monitor: Monitor) -> None:
    rule = SLORule(
        monitor_id=test_monitor.id,
        rule_type=SLORuleType.quorum_down,
        quorum_ratio=0.6,
        window_seconds=90,
        min_probes=3,
    )
    service_db.add(rule)
    await service_db.flush()

    fetched = (
        await service_db.execute(select(SLORule).where(SLORule.monitor_id == test_monitor.id))
    ).scalar_one()
    assert fetched.rule_type == SLORuleType.quorum_down
    assert fetched.quorum_ratio == 0.6
    assert fetched.enabled is True
    assert fetched.cooldown_seconds == 60


@pytest.mark.asyncio
async def test_incident_default_trigger_kind_is_legacy(
    service_db: AsyncSession, test_monitor: Monitor
) -> None:
    """Pre-existing incident-creation paths must default trigger_kind='legacy'."""
    from whatisup.models.incident import Incident, IncidentScope

    inc = Incident(
        monitor_id=test_monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(inc)
    await service_db.flush()
    await service_db.refresh(inc)
    assert inc.trigger_kind == "legacy"
    assert inc.slo_rule_id is None
