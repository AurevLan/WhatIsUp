"""Plan cap v2, étape 1 — the network verdict must be computed on the Health
Engine incident-open path (``services/incident_slo.open_incident_from_health``),
not just on the legacy pipeline in ``services/incident.py``.
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
from whatisup.services import health
from whatisup.services.network_verdict import NetworkVerdict, classify_network_verdict


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


def _make_result(monitor: Monitor, probe: Probe, status: CheckStatus) -> CheckResult:
    return CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=status,
        checked_at=datetime.now(UTC),
    )


async def _ingest(db: AsyncSession, cr: CheckResult, *, publish_event=None) -> None:
    db.add(cr)
    await db.flush()
    await health.ingest(db, cr, publish_event=publish_event)


async def _open_quorum_down_incident(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
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

    async def publish(_event):
        return None

    # All 3 probes down -> quorum_down opens, and _classify sees a clean
    # 3/3 down with up_total == 0 -> SERVICE_DOWN (not INCONCLUSIVE).
    await _ingest(
        service_db, _make_result(test_monitor, test_probe, CheckStatus.down), publish_event=publish
    )
    await _ingest(
        service_db, _make_result(test_monitor, probe2, CheckStatus.down), publish_event=publish
    )
    await _ingest(
        service_db, _make_result(test_monitor, probe3, CheckStatus.timeout), publish_event=publish
    )


@pytest.mark.asyncio
async def test_health_path_incident_has_network_verdict(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
) -> None:
    """An incident opened through the Health Engine bridge must come out with
    a computed network_verdict — this is the bug fixed in plan_cap_v2 étape 1:
    ``open_incident_from_health`` used to enqueue diagnostics but never call
    ``classify_network_verdict``, leaving 355/459 incidents unclassified."""
    await _open_quorum_down_incident(service_db, test_monitor, test_probe, probe2, probe3)

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    incident = incidents[0]

    # The contract of this lot: an incident born on the Health Engine path
    # carries a verdict, where it used to carry NULL forever.
    assert incident.network_verdict is not None
    assert incident.network_verdict_computed_at is not None

    # It is `inconclusive` at this point, and that is correct rather than a
    # shortcoming: quorum_down fires on the 2nd probe (min_probes=2), so the
    # classifier only ever sees the probes that have reported *so far* — two,
    # below _MIN_TOTAL_PROBES. The verdict at open is a first answer, refined
    # by `recompute_open_incidents_verdicts` while the incident stays open.
    assert incident.network_verdict == NetworkVerdict.INCONCLUSIVE.value

    # Once the third probe has reported, the same classifier resolves it.
    verdict = await classify_network_verdict(service_db, incident, persist=True)
    assert verdict == NetworkVerdict.SERVICE_DOWN
    assert incident.network_verdict == NetworkVerdict.SERVICE_DOWN.value


@pytest.mark.asyncio
async def test_health_path_incident_opens_even_if_verdict_computation_fails(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
    probe2: Probe,
    probe3: Probe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single most important test of this lot: a broken verdict computation
    must never prevent the incident from opening. An unclassified incident is
    far better than a swallowed one.

    Raises a plain ``RuntimeError`` on purpose. Asserting against an exception
    type the guard explicitly lists would only prove the guard catches what
    this test throws; the real risk is the *unforeseen* failure — an
    AttributeError on an unexpected shape, a bug in the classifier — reaching
    the caller and taking the incident down with it.
    """

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated verdict computation failure")

    monkeypatch.setattr(
        "whatisup.services.network_verdict.classify_network_verdict",
        _boom,
    )

    await _open_quorum_down_incident(service_db, test_monitor, test_probe, probe2, probe3)

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == test_monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    incident = incidents[0]
    # The incident opened despite the verdict computation blowing up.
    assert incident.resolved_at is None
    assert incident.network_verdict is None
