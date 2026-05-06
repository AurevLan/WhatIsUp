"""V2 Global Health Engine — M2 SLO quorum_down tests.

Covers the pure decision function in ``services/slo`` (Open/Close/Hold) and
the integration with ``services/health.evaluate_slos`` that translates
decisions into Incident lifecycle events.
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


def _state_with_probes(monitor_id, probes: dict[str, str], now: datetime | None = None):
    """Build an in-memory MonitorHealthState for pure-evaluator tests."""
    now = now or datetime.now(UTC)
    return MonitorHealthState(
        monitor_id=monitor_id,
        updated_at=now,
        probes_state={
            pid: {
                "last_status": status,
                "last_at": now.isoformat(),
                "consecutive_down": 0,
                "response_time_ms": None,
            }
            for pid, status in probes.items()
        },
        probe_health={},
    )


def _rule(monitor_id, **overrides) -> SLORule:
    defaults = {
        "rule_type": SLORuleType.quorum_down,
        "enabled": True,
        "quorum_ratio": 0.6,
        "window_seconds": 300,
        "min_probes": 1,
        "cooldown_seconds": 0,
    }
    defaults.update(overrides)
    return SLORule(monitor_id=monitor_id, **defaults)


# ── Pure evaluator (no DB) ─────────────────────────────────────────────────


def test_evaluate_quorum_down_open_when_majority_down():
    monitor_id = "00000000-0000-0000-0000-000000000001"
    state = _state_with_probes(monitor_id, {"a": "down", "b": "down", "c": "up"})
    rule = _rule(monitor_id, quorum_ratio=0.6)
    decision = slo.evaluate_rule(rule, state, datetime.now(UTC))
    assert isinstance(decision, Open)
    assert decision.scope == IncidentScope.geographic
    assert set(decision.affected_probe_ids) == {"a", "b"}


def test_evaluate_quorum_down_global_scope_when_all_down():
    monitor_id = "00000000-0000-0000-0000-000000000002"
    state = _state_with_probes(monitor_id, {"a": "down", "b": "timeout"})
    rule = _rule(monitor_id, quorum_ratio=0.5)
    decision = slo.evaluate_rule(rule, state, datetime.now(UTC))
    assert isinstance(decision, Open)
    assert decision.scope == IncidentScope.global_


def test_evaluate_quorum_down_close_when_below_threshold():
    monitor_id = "00000000-0000-0000-0000-000000000003"
    state = _state_with_probes(monitor_id, {"a": "down", "b": "up", "c": "up", "d": "up"})
    rule = _rule(monitor_id, quorum_ratio=0.6)
    decision = slo.evaluate_rule(rule, state, datetime.now(UTC))
    assert isinstance(decision, Close)


def test_evaluate_quorum_down_hold_when_not_enough_probes():
    monitor_id = "00000000-0000-0000-0000-000000000004"
    state = _state_with_probes(monitor_id, {"a": "down"})
    rule = _rule(monitor_id, quorum_ratio=0.6, min_probes=3)
    decision = slo.evaluate_rule(rule, state, datetime.now(UTC))
    assert isinstance(decision, Hold)


def test_evaluate_quorum_down_excludes_stale_probes():
    """A probe whose last_at is older than window_seconds must be ignored."""
    monitor_id = "00000000-0000-0000-0000-000000000005"
    now = datetime.now(UTC)
    fresh_iso = now.isoformat()
    stale_iso = (now - timedelta(seconds=600)).isoformat()
    state = MonitorHealthState(
        monitor_id=monitor_id,
        updated_at=now,
        probes_state={
            "fresh-up": {
                "last_status": "up",
                "last_at": fresh_iso,
                "consecutive_down": 0,
                "response_time_ms": None,
            },
            "stale-down": {
                "last_status": "down",
                "last_at": stale_iso,
                "consecutive_down": 5,
                "response_time_ms": None,
            },
        },
        probe_health={},
    )
    rule = _rule(monitor_id, quorum_ratio=0.5, window_seconds=300, min_probes=1)
    decision = slo.evaluate_rule(rule, state, now)
    # stale-down filtered out → only fresh-up remains → quorum not reached
    assert isinstance(decision, Close)


def test_evaluate_disabled_rule_holds():
    monitor_id = "00000000-0000-0000-0000-000000000006"
    state = _state_with_probes(monitor_id, {"a": "down", "b": "down"})
    rule = _rule(monitor_id, enabled=False, quorum_ratio=0.5)
    decision = slo.evaluate_rule(rule, state, datetime.now(UTC))
    assert isinstance(decision, Hold)


# ── Integration: ingest → evaluate_slos → Incident ──────────────────────────


@pytest.mark.asyncio
async def test_ingest_opens_incident_when_quorum_down(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
    test_monitor.health_engine_enabled = True
    rule = SLORule(
        monitor_id=test_monitor.id,
        rule_type=SLORuleType.quorum_down,
        enabled=True,
        quorum_ratio=0.6,
        window_seconds=300,
        min_probes=2,
        cooldown_seconds=0,
    )
    service_db.add(rule)
    await service_db.flush()

    events: list[dict] = []

    async def publish(event):
        events.append(event)

    # 2/3 probes down → 0.67 ≥ 0.6 → open
    await _ingest(
        service_db,
        _make_result(test_monitor, test_probe, CheckStatus.up, 100),
        publish_event=publish,
    )
    await _ingest(
        service_db, _make_result(test_monitor, probe2, CheckStatus.down), publish_event=publish
    )
    await _ingest(
        service_db, _make_result(test_monitor, probe3, CheckStatus.timeout), publish_event=publish
    )

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.slo_rule_id == rule.id
    assert inc.trigger_kind == "quorum_down"
    assert inc.resolved_at is None
    assert set(inc.affected_probe_ids) == {str(probe2.id), str(probe3.id)}
    assert inc.scope == IncidentScope.geographic
    assert any(e.get("type") == "incident_opened" for e in events)


@pytest.mark.asyncio
async def test_ingest_resolves_incident_when_probes_recover(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
    test_monitor.health_engine_enabled = True
    rule = SLORule(
        monitor_id=test_monitor.id,
        rule_type=SLORuleType.quorum_down,
        enabled=True,
        quorum_ratio=0.6,
        window_seconds=300,
        min_probes=2,
        cooldown_seconds=0,
    )
    service_db.add(rule)
    await service_db.flush()

    async def publish(_event):
        return None

    # Open: 2/3 down
    await _ingest(
        service_db,
        _make_result(test_monitor, test_probe, CheckStatus.up, 100),
        publish_event=publish,
    )
    await _ingest(
        service_db, _make_result(test_monitor, probe2, CheckStatus.down), publish_event=publish
    )
    await _ingest(
        service_db, _make_result(test_monitor, probe3, CheckStatus.down), publish_event=publish
    )
    # Close: probes recover
    await _ingest(
        service_db, _make_result(test_monitor, probe2, CheckStatus.up, 110), publish_event=publish
    )
    await _ingest(
        service_db, _make_result(test_monitor, probe3, CheckStatus.up, 90), publish_event=publish
    )

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    assert incidents[0].resolved_at is not None
    assert incidents[0].duration_seconds is not None and incidents[0].duration_seconds >= 0


@pytest.mark.asyncio
async def test_open_is_idempotent(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
) -> None:
    """Repeated 'down' samples on the same probes must not create extra incidents."""
    test_monitor.health_engine_enabled = True
    service_db.add(
        SLORule(
            monitor_id=test_monitor.id,
            rule_type=SLORuleType.quorum_down,
            enabled=True,
            quorum_ratio=0.5,
            window_seconds=300,
            min_probes=2,
            cooldown_seconds=0,
        )
    )
    await service_db.flush()

    async def publish(_e):
        return None

    for _ in range(3):
        await _ingest(
            service_db,
            _make_result(test_monitor, test_probe, CheckStatus.down),
            publish_event=publish,
        )
        await _ingest(
            service_db,
            _make_result(test_monitor, probe2, CheckStatus.timeout),
            publish_event=publish,
        )

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1


@pytest.mark.asyncio
async def test_staggered_probes_yield_single_incident(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
    """Reproduces the original bug: probes report down at different times.

    Legacy pipeline emitted 1 alert per probe. Health engine must emit ONE.
    """
    test_monitor.health_engine_enabled = True
    service_db.add(
        SLORule(
            monitor_id=test_monitor.id,
            rule_type=SLORuleType.quorum_down,
            enabled=True,
            quorum_ratio=0.6,
            window_seconds=300,
            min_probes=2,
            cooldown_seconds=0,
        )
    )
    await service_db.flush()

    events: list[dict] = []

    async def publish(e):
        events.append(e)

    # All probes start up
    now = datetime.now(UTC)
    await _ingest(
        service_db,
        _make_result(test_monitor, test_probe, CheckStatus.up, 100, now),
        publish_event=publish,
    )
    await _ingest(
        service_db,
        _make_result(test_monitor, probe2, CheckStatus.up, 110, now),
        publish_event=publish,
    )
    await _ingest(
        service_db,
        _make_result(test_monitor, probe3, CheckStatus.up, 120, now),
        publish_event=publish,
    )
    # Probes go down one by one over 90s — but quorum is reached on the 2nd
    await _ingest(
        service_db,
        _make_result(test_monitor, test_probe, CheckStatus.down, None, now + timedelta(seconds=30)),
        publish_event=publish,
    )
    await _ingest(
        service_db,
        _make_result(test_monitor, probe2, CheckStatus.down, None, now + timedelta(seconds=60)),
        publish_event=publish,
    )
    await _ingest(
        service_db,
        _make_result(test_monitor, probe3, CheckStatus.down, None, now + timedelta(seconds=90)),
        publish_event=publish,
    )

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    open_events = [e for e in events if e.get("type") == "incident_opened"]
    assert len(incidents) == 1
    assert len(open_events) == 1
