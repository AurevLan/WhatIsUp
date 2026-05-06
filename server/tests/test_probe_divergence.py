"""V2 Global Health Engine — M5 probe divergence tests.

A probe systematically out of sync with the fleet (e.g. flaky local network
on the probe host) accumulates a divergence score. Once it crosses the 0.5
threshold, ``services.slo`` excludes it from quorum counts so a single bad
probe can't fabricate or mask incidents on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import MonitorHealthState, SLORule, SLORuleType
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services import health, slo


@pytest_asyncio.fixture
async def probe2(service_db: AsyncSession) -> Probe:
    p = Probe(name="probe-fleet-2", location_name="NYC", api_key_hash="x")
    service_db.add(p)
    await service_db.flush()
    return p


@pytest_asyncio.fixture
async def probe3(service_db: AsyncSession) -> Probe:
    p = Probe(name="probe-fleet-3", location_name="Tokyo", api_key_hash="x")
    service_db.add(p)
    await service_db.flush()
    return p


def _result(
    monitor: Monitor, probe: Probe, status: CheckStatus, at: datetime | None = None
) -> CheckResult:
    return CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=status,
        response_time_ms=120.0 if status == CheckStatus.up else None,
        checked_at=at or datetime.now(UTC),
    )


async def _ingest(db: AsyncSession, cr: CheckResult, *, publish_event=None) -> None:
    db.add(cr)
    await db.flush()
    await health.ingest(db, cr, publish_event=publish_event)


@pytest.mark.asyncio
async def test_divergent_probe_score_climbs_above_exclusion_threshold(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
    """A probe consistently reporting down while the fleet sees up should
    accumulate a divergence_score > 0.5 within a few ingests."""
    test_monitor.health_engine_enabled = False  # divergence is computed regardless
    base = datetime.now(UTC) - timedelta(seconds=120)

    # Establish fleet baseline: probe2 and probe3 both up
    await _ingest(service_db, _result(test_monitor, probe2, CheckStatus.up, at=base))
    await _ingest(
        service_db,
        _result(test_monitor, probe3, CheckStatus.up, at=base + timedelta(seconds=1)),
    )

    # The lonely-down probe gets repeatedly contradicted
    for i in range(8):
        down_at = base + timedelta(seconds=10 + i)
        up_at = base + timedelta(seconds=11 + i)
        await _ingest(service_db, _result(test_monitor, test_probe, CheckStatus.down, at=down_at))
        await _ingest(service_db, _result(test_monitor, probe2, CheckStatus.up, at=up_at))

    state = (
        await service_db.execute(
            select(MonitorHealthState).where(MonitorHealthState.monitor_id == test_monitor.id)
        )
    ).scalar_one()
    score = state.probe_health.get(str(test_probe.id), {}).get("divergence_score", 0.0)
    assert score > 0.5, f"divergent probe should exceed threshold, got {score}"


@pytest.mark.asyncio
async def test_divergent_probe_excluded_from_quorum_evaluation(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
    """Once flagged, the divergent probe doesn't count toward the down ratio:
    its sole 'down' verdict on a healthy fleet must not open an incident."""
    test_monitor.health_engine_enabled = True
    rule = SLORule(
        monitor_id=test_monitor.id,
        rule_type=SLORuleType.quorum_down,
        enabled=True,
        quorum_ratio=0.5,
        window_seconds=300,
        min_probes=2,
        cooldown_seconds=0,
    )
    service_db.add(rule)
    await service_db.flush()

    events: list[dict] = []

    async def publish(event):
        events.append(event)

    base = datetime.now(UTC) - timedelta(seconds=120)
    # Bake in test_probe's high divergence score directly
    state = await health.ensure_state(service_db, test_monitor.id)
    state.probe_health = {
        str(test_probe.id): {
            "divergence_score": 0.8,
            "samples": 10,
            "last_eval_at": base.isoformat(),
        }
    }
    await service_db.flush()

    # Bring fleet up first
    await _ingest(
        service_db, _result(test_monitor, probe2, CheckStatus.up, at=base), publish_event=publish
    )
    await _ingest(
        service_db,
        _result(test_monitor, probe3, CheckStatus.up, at=base + timedelta(seconds=2)),
        publish_event=publish,
    )

    # Divergent probe alone reports down — must NOT open an incident
    await _ingest(
        service_db,
        _result(test_monitor, test_probe, CheckStatus.down, at=base + timedelta(seconds=5)),
        publish_event=publish,
    )

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 0, "divergent probe alone must not trigger quorum_down"


def test_evaluate_quorum_down_skips_divergent_probe_in_count() -> None:
    """Pure-evaluator check: a divergent probe is not counted in fresh probes,
    so a 1/2-down ratio across non-divergent probes wins over total = 3."""
    monitor_id = "00000000-0000-0000-0000-000000000001"
    now = datetime.now(UTC)
    state = MonitorHealthState(
        monitor_id=monitor_id,
        updated_at=now,
        probes_state={
            "good-1": {"last_status": "down", "last_at": now.isoformat()},
            "good-2": {"last_status": "down", "last_at": now.isoformat()},
            "noisy": {"last_status": "up", "last_at": now.isoformat()},
        },
        probe_health={"noisy": {"divergence_score": 0.9, "samples": 12}},
    )
    rule = SLORule(
        monitor_id=monitor_id,
        rule_type=SLORuleType.quorum_down,
        enabled=True,
        quorum_ratio=0.6,
        window_seconds=300,
        min_probes=2,
        cooldown_seconds=0,
    )
    decision = slo.evaluate_rule(rule, state, now)
    # 2/2 down (noisy excluded) → quorum reached, scope global
    assert isinstance(decision, slo.Open)
    assert "2/2" in decision.reason
    assert "noisy" not in decision.affected_probe_ids
