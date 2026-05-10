"""V2 Global Health Engine — M3 SLO quorum_slow tests.

Mirrors ``test_slo_quorum_down``: pure evaluator coverage + integration via
``services/health.evaluate_slos``. The integration scenario reproduces the
staggered-probes user complaint for performance: 8 probes with shifted
slow samples that converge on a degraded fleet p95 → exactly 1 incident.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import MonitorHealthState, SLORule, SLORuleType
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services import health, slo
from whatisup.services.slo import Close, Hold, Open


@pytest_asyncio.fixture
async def probe2(service_db: AsyncSession) -> Probe:
    p = Probe(name="probe-2", location_name="NYC", api_key_hash="x")
    service_db.add(p)
    await service_db.flush()
    return p


@pytest_asyncio.fixture
async def probe3(service_db: AsyncSession) -> Probe:
    p = Probe(name="probe-3", location_name="Tokyo", api_key_hash="x")
    service_db.add(p)
    await service_db.flush()
    return p


def _make_result(
    monitor: Monitor,
    probe: Probe,
    status: CheckStatus,
    rt_ms: float | None = None,
    at: datetime | None = None,
) -> CheckResult:
    return CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=status,
        response_time_ms=rt_ms,
        checked_at=at or datetime.now(UTC),
    )


async def _ingest(db: AsyncSession, cr: CheckResult, *, publish_event=None) -> None:
    db.add(cr)
    await db.flush()
    await health.ingest(db, cr, publish_event=publish_event)


def _state_with_p95(
    monitor_id, *, p95: float, sample_count: int, fresh_probes: int, now: datetime | None = None
):
    """Build an in-memory state with a synthetic fleet p95 + N fresh probes."""
    now = now or datetime.now(UTC)
    return MonitorHealthState(
        monitor_id=monitor_id,
        updated_at=now,
        probes_state={
            f"probe-{i}": {
                "last_status": "up",
                "last_at": now.isoformat(),
                "consecutive_down": 0,
                "response_time_ms": p95,
            }
            for i in range(fresh_probes)
        },
        p50_5m=p95 * 0.5,
        p95_5m=p95,
        p99_5m=p95 * 1.1,
        sample_count_5m=sample_count,
        probe_health={},
    )


def _rule(monitor_id, **overrides) -> SLORule:
    defaults = {
        "rule_type": SLORuleType.quorum_slow,
        "enabled": True,
        "p95_threshold_ms": 500,
        "window_seconds": 300,
        "min_probes": 2,
        "cooldown_seconds": 0,
    }
    defaults.update(overrides)
    return SLORule(monitor_id=monitor_id, **defaults)


# ── Pure evaluator (no DB) ─────────────────────────────────────────────────


def test_evaluate_quorum_slow_open_when_p95_above_threshold():
    monitor_id = "00000000-0000-0000-0000-000000000001"
    state = _state_with_p95(monitor_id, p95=900.0, sample_count=20, fresh_probes=4)
    decision = slo.evaluate_rule(_rule(monitor_id), state, datetime.now(UTC))
    assert isinstance(decision, Open)
    assert decision.scope == IncidentScope.global_
    assert len(decision.affected_probe_ids) == 4
    assert "p95_5m=900" in decision.reason


def test_evaluate_quorum_slow_close_when_p95_below_threshold():
    monitor_id = "00000000-0000-0000-0000-000000000001"
    state = _state_with_p95(monitor_id, p95=200.0, sample_count=20, fresh_probes=4)
    decision = slo.evaluate_rule(_rule(monitor_id), state, datetime.now(UTC))
    assert isinstance(decision, Close)


def test_evaluate_quorum_slow_hold_when_no_signal():
    monitor_id = "00000000-0000-0000-0000-000000000001"
    state = _state_with_p95(monitor_id, p95=900.0, sample_count=0, fresh_probes=4)
    state.p95_5m = None
    decision = slo.evaluate_rule(_rule(monitor_id), state, datetime.now(UTC))
    assert isinstance(decision, Hold)
    assert "no_p95_signal" in decision.reason


def test_evaluate_quorum_slow_hold_when_not_enough_probes():
    monitor_id = "00000000-0000-0000-0000-000000000001"
    state = _state_with_p95(monitor_id, p95=900.0, sample_count=5, fresh_probes=1)
    decision = slo.evaluate_rule(_rule(monitor_id, min_probes=3), state, datetime.now(UTC))
    assert isinstance(decision, Hold)
    assert "not_enough_probes" in decision.reason


def test_evaluate_quorum_slow_hold_without_threshold():
    monitor_id = "00000000-0000-0000-0000-000000000001"
    state = _state_with_p95(monitor_id, p95=900.0, sample_count=20, fresh_probes=4)
    decision = slo.evaluate_rule(_rule(monitor_id, p95_threshold_ms=None), state, datetime.now(UTC))
    assert isinstance(decision, Hold)
    assert "no_threshold_configured" in decision.reason


def test_evaluate_quorum_slow_excludes_stale_probes():
    """Probes whose last_at is older than window_seconds shouldn't count."""
    monitor_id = "00000000-0000-0000-0000-000000000001"
    now = datetime.now(UTC)
    stale = (now - timedelta(seconds=600)).isoformat()
    fresh = now.isoformat()
    state = MonitorHealthState(
        monitor_id=monitor_id,
        updated_at=now,
        probes_state={
            "stale-1": {"last_status": "up", "last_at": stale, "consecutive_down": 0},
            "stale-2": {"last_status": "up", "last_at": stale, "consecutive_down": 0},
            "fresh-1": {"last_status": "up", "last_at": fresh, "consecutive_down": 0},
        },
        p50_5m=400.0,
        p95_5m=900.0,
        p99_5m=1100.0,
        sample_count_5m=10,
        probe_health={},
    )
    decision = slo.evaluate_rule(_rule(monitor_id, min_probes=2), state, now)
    assert isinstance(decision, Hold)
    assert "1<2" in decision.reason


# ── Integration via health.ingest ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_opens_perf_incident_when_p95_degraded(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
    test_monitor.health_engine_enabled = True
    rule = SLORule(
        monitor_id=test_monitor.id,
        rule_type=SLORuleType.quorum_slow,
        enabled=True,
        p95_threshold_ms=500,
        window_seconds=300,
        min_probes=2,
        cooldown_seconds=0,
    )
    service_db.add(rule)
    await service_db.flush()

    events: list[dict] = []

    async def publish(event):
        events.append(event)

    # All up but slow — fleet p95 well above 500 ms
    for probe, rt in [(test_probe, 1200), (probe2, 1500), (probe3, 1000)]:
        await _ingest(
            service_db,
            _make_result(test_monitor, probe, CheckStatus.up, rt_ms=rt),
            publish_event=publish,
        )

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.slo_rule_id == rule.id
    assert inc.trigger_kind == "quorum_slow"
    assert inc.scope == IncidentScope.global_
    assert inc.resolved_at is None
    assert any(e.get("type") == "incident_opened" for e in events)


@pytest.mark.asyncio
async def test_ingest_resolves_perf_incident_when_p95_recovers(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
) -> None:
    test_monitor.health_engine_enabled = True
    rule = SLORule(
        monitor_id=test_monitor.id,
        rule_type=SLORuleType.quorum_slow,
        enabled=True,
        p95_threshold_ms=500,
        window_seconds=300,
        min_probes=2,
        cooldown_seconds=0,
    )
    service_db.add(rule)
    await service_db.flush()

    async def publish(_event):
        return None

    # Degraded — push slow samples timestamped 6 min ago so they age out of
    # the 5-min p95 window once the recovery samples land.
    long_ago = datetime.now(UTC) - timedelta(minutes=6)
    for probe, rt in [(test_probe, 1500), (probe2, 1800), (test_probe, 1600), (probe2, 1200)]:
        await _ingest(
            service_db,
            _make_result(test_monitor, probe, CheckStatus.up, rt_ms=rt, at=long_ago),
            publish_event=publish,
        )
    # The legacy slow samples won't open the incident (already aged out at
    # ingest time). Force-open via an explicit recent slow burst, then recover.
    recent = datetime.now(UTC) - timedelta(seconds=30)
    for probe in (test_probe, probe2):
        await _ingest(
            service_db,
            _make_result(test_monitor, probe, CheckStatus.up, rt_ms=1500, at=recent),
            publish_event=publish,
        )
    # Recovery — push enough fast samples that p95 drops below threshold.
    # With 2 lingering slow samples in the 5-min window, we need >40 total
    # so the 95th percentile lands on a fast sample (rank > 39 in 42).
    now = datetime.now(UTC)
    for i in range(20):
        for probe in (test_probe, probe2):
            await _ingest(
                service_db,
                _make_result(
                    test_monitor,
                    probe,
                    CheckStatus.up,
                    rt_ms=80,
                    at=now + timedelta(seconds=i),
                ),
                publish_event=publish,
            )

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    assert incidents[0].resolved_at is not None


@pytest.mark.asyncio
async def test_staggered_slow_probes_yield_single_incident(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
    """Reproduces the user-reported bug for perf: probes report slow checks
    in a staggered cadence but converge on a globally-degraded fleet p95.

    Legacy per-probe ``response_time_above`` would have fired N alerts in
    sequence. The Health Engine emits exactly one ``quorum_slow`` incident.
    """
    test_monitor.health_engine_enabled = True
    rule = SLORule(
        monitor_id=test_monitor.id,
        rule_type=SLORuleType.quorum_slow,
        enabled=True,
        p95_threshold_ms=500,
        window_seconds=300,
        min_probes=2,
        cooldown_seconds=0,
    )
    service_db.add(rule)
    await service_db.flush()

    events: list[dict] = []

    async def publish(event):
        events.append(event)

    base = datetime.now(UTC) - timedelta(seconds=60)
    # 12 staggered slow samples spread across 3 probes — none alone would have
    # triggered a per-probe perf alert (response_time_above_baseline needs
    # consecutive samples), but the aggregated fleet p95 is clearly degraded.
    rotation = [test_probe, probe2, probe3]
    for i in range(12):
        probe = rotation[i % 3]
        await _ingest(
            service_db,
            _make_result(
                test_monitor,
                probe,
                CheckStatus.up,
                rt_ms=900 + (i * 30),
                at=base + timedelta(seconds=i * 4),
            ),
            publish_event=publish,
        )

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1, "staggered slow samples must collapse into a single incident"
    opened = [e for e in events if e.get("type") == "incident_opened"]
    assert len(opened) == 1
