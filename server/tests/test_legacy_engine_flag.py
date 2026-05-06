"""V2 Global Health Engine — M5 emergency rollback flag.

When ``LEGACY_INCIDENT_ENGINE=true`` is set, the per-probe legacy decider runs
even on monitors with ``health_engine_enabled=True``. No code change, no
migration — flip the env var and restart.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import SLORule, SLORuleType
from whatisup.models.probe import Probe
from whatisup.models.user import User


@pytest_asyncio.fixture
async def health_monitor(service_db: AsyncSession, test_user: User) -> Monitor:
    m = Monitor(
        name="legacy-flag-test",
        url="http://flag.test",
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
            min_probes=1,
            cooldown_seconds=0,
        )
    )
    await service_db.flush()
    return m


@pytest.mark.asyncio
async def test_legacy_engine_flag_short_circuits_health_engine(
    service_db: AsyncSession,
    health_monitor: Monitor,
    test_probe: Probe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the rollback flag on, ``process_check_result`` runs the legacy
    pipeline even though the monitor has ``health_engine_enabled=True``."""
    from datetime import UTC, datetime

    from whatisup.models.result import CheckResult, CheckStatus
    from whatisup.services.incident import process_check_result

    settings = get_settings()
    monkeypatch.setattr(settings, "legacy_incident_engine", True)

    async def publish(_event):
        return None

    cr = CheckResult(
        monitor_id=health_monitor.id,
        probe_id=test_probe.id,
        status=CheckStatus.down,
        response_time_ms=None,
        checked_at=datetime.now(UTC),
    )
    service_db.add(cr)
    await service_db.flush()
    await process_check_result(service_db, cr, publish)

    # Legacy decider may or may not open an incident depending on flapping
    # heuristics — what matters is that the SLO bridge did NOT (no slo_rule_id).
    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == health_monitor.id)))
        .scalars()
        .all()
    )
    for inc in incidents:
        assert inc.slo_rule_id is None, "legacy flag must bypass the SLO incident path"
        assert inc.trigger_kind == "legacy"
