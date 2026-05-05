"""V2 Global Health Engine — M1 ingest aggregator tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import MonitorHealthState
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services import health


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


def _make_result(monitor: Monitor, probe: Probe, status: CheckStatus, rt_ms: float | None,
                 at: datetime | None = None) -> CheckResult:
    return CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=status,
        response_time_ms=rt_ms,
        checked_at=at or datetime.now(UTC),
    )


async def _ingest_one(db: AsyncSession, cr: CheckResult) -> None:
    db.add(cr)
    await db.flush()
    await health.ingest(db, cr)


# ── probes_state ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_records_per_probe_status(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe, probe2: Probe
) -> None:
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.up, 100))
    await _ingest_one(service_db, _make_result(test_monitor, probe2, CheckStatus.down, None))

    state = await health.ensure_state(service_db, test_monitor.id)
    assert set(state.probes_state.keys()) == {str(test_probe.id), str(probe2.id)}
    assert state.probes_state[str(test_probe.id)]["last_status"] == "up"
    assert state.probes_state[str(probe2.id)]["last_status"] == "down"


@pytest.mark.asyncio
async def test_consecutive_down_increments_then_resets(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.down, None))
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.timeout, None))
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.down, None))

    state = await health.ensure_state(service_db, test_monitor.id)
    assert state.probes_state[str(test_probe.id)]["consecutive_down"] == 3

    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.up, 50))
    state = await health.ensure_state(service_db, test_monitor.id)
    assert state.probes_state[str(test_probe.id)]["consecutive_down"] == 0


# ── quorum + scope ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quorum_zero_when_all_up(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe, probe2: Probe
) -> None:
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.up, 100))
    await _ingest_one(service_db, _make_result(test_monitor, probe2, CheckStatus.up, 120))

    state = await health.ensure_state(service_db, test_monitor.id)
    assert state.quorum_down_ratio == 0.0
    assert state.current_scope is None


@pytest.mark.asyncio
async def test_quorum_partial_marks_geographic(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe,
    probe2: Probe, probe3: Probe
) -> None:
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.up, 100))
    await _ingest_one(service_db, _make_result(test_monitor, probe2, CheckStatus.down, None))
    await _ingest_one(service_db, _make_result(test_monitor, probe3, CheckStatus.up, 150))

    state = await health.ensure_state(service_db, test_monitor.id)
    assert abs(state.quorum_down_ratio - 1 / 3) < 1e-6
    assert state.current_scope == "geographic"


@pytest.mark.asyncio
async def test_quorum_full_marks_global(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe, probe2: Probe
) -> None:
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.down, None))
    await _ingest_one(service_db, _make_result(test_monitor, probe2, CheckStatus.timeout, None))

    state = await health.ensure_state(service_db, test_monitor.id)
    assert state.quorum_down_ratio == 1.0
    assert state.current_scope == "global"


# ── 5-minute percentiles ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_percentiles_match_inputs(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    """Inject 100 samples [1..100], verify p50≈50.5, p95≈95.05, p99≈99.01."""
    now = datetime.now(UTC)
    for ms in range(1, 101):
        await _ingest_one(
            service_db,
            _make_result(test_monitor, test_probe, CheckStatus.up, float(ms), now),
        )

    state = await health.ensure_state(service_db, test_monitor.id)
    assert state.sample_count_5m == 100
    assert 50 <= state.p50_5m <= 51
    assert 94 <= state.p95_5m <= 96
    assert 98 <= state.p99_5m <= 100


@pytest.mark.asyncio
async def test_percentiles_drop_old_samples(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    """A 6-minute-old sample must NOT be counted in the 5-min window."""
    old = datetime.now(UTC) - timedelta(minutes=6)
    fresh = datetime.now(UTC)
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.up, 9999, old))
    await _ingest_one(service_db, _make_result(test_monitor, test_probe, CheckStatus.up, 50, fresh))

    state = await health.ensure_state(service_db, test_monitor.id)
    assert state.sample_count_5m == 1
    assert state.p50_5m == 50


# ── failure isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_with_no_probe_id_is_safe(
    service_db: AsyncSession, test_monitor: Monitor
) -> None:
    """A heartbeat-source CheckResult has probe_id=None and must not crash ingest."""
    cr = CheckResult(
        monitor_id=test_monitor.id,
        probe_id=None,
        status=CheckStatus.up,
        response_time_ms=1.0,
        checked_at=datetime.now(UTC),
    )
    service_db.add(cr)
    await service_db.flush()
    await health.ingest(service_db, cr)

    state = (
        await service_db.execute(
            select(MonitorHealthState).where(MonitorHealthState.monitor_id == test_monitor.id)
        )
    ).scalar_one()
    # No probe_id → no probe view, but state row exists with valid scope
    assert state.probes_state == {}
    assert state.current_scope is None
