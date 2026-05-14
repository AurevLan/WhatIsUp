"""Coverage for the alert-matrix preview service (replay & counts)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.alert_matrix_preview import compute_preview


def _new_monitor(owner: User, name: str = "m") -> Monitor:
    return Monitor(name=name, url=f"http://{name}.x", owner_id=owner.id)


async def _seed_incidents(
    db: AsyncSession, monitor: Monitor, count: int, *, scope: IncidentScope, duration: int = 600
) -> None:
    now = datetime.now(UTC)
    for i in range(count):
        db.add(
            Incident(
                monitor_id=monitor.id,
                scope=scope,
                affected_probe_ids=[],
                started_at=now - timedelta(days=i + 1),
                resolved_at=now - timedelta(days=i + 1) + timedelta(seconds=duration),
                duration_seconds=duration,
                dependency_suppressed=False,
            )
        )
    await db.flush()


@pytest.mark.asyncio
async def test_any_down_counts_incidents(service_db: AsyncSession, test_user: User) -> None:
    m = _new_monitor(test_user, "any-down")
    service_db.add(m)
    await service_db.flush()
    await _seed_incidents(service_db, m, 3, scope=IncidentScope.global_)

    res = await compute_preview(service_db, m.id, [{"condition": "any_down"}])
    assert res["counts"] == [{"condition": "any_down", "count": 3}]
    assert res["total"] == 3
    assert res["window_days"] == 30


@pytest.mark.asyncio
async def test_any_down_filters_by_min_duration(service_db: AsyncSession, test_user: User) -> None:
    m = _new_monitor(test_user, "min-dur")
    service_db.add(m)
    await service_db.flush()
    # 2 short (60s) + 2 long (600s)
    now = datetime.now(UTC)
    for i, dur in enumerate([60, 60, 600, 600]):
        service_db.add(
            Incident(
                monitor_id=m.id,
                scope=IncidentScope.global_,
                affected_probe_ids=[],
                started_at=now - timedelta(days=i + 1),
                resolved_at=now - timedelta(days=i + 1) + timedelta(seconds=dur),
                duration_seconds=dur,
            )
        )
    await service_db.flush()

    res = await compute_preview(
        service_db, m.id, [{"condition": "any_down", "min_duration_seconds": 120}]
    )
    assert res["counts"][0]["count"] == 2


@pytest.mark.asyncio
async def test_all_down_counts_only_global_incidents(
    service_db: AsyncSession, test_user: User
) -> None:
    m = _new_monitor(test_user, "all-down")
    service_db.add(m)
    await service_db.flush()
    await _seed_incidents(service_db, m, 2, scope=IncidentScope.global_)
    await _seed_incidents(service_db, m, 5, scope=IncidentScope.geographic)

    res = await compute_preview(service_db, m.id, [{"condition": "all_down"}])
    assert res["counts"][0]["count"] == 2


@pytest.mark.asyncio
async def test_response_time_above_threshold(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    m = _new_monitor(test_user, "rt")
    service_db.add(m)
    await service_db.flush()
    now = datetime.now(UTC)
    for ms in [100, 500, 2500, 5000, 10000]:
        service_db.add(
            CheckResult(
                monitor_id=m.id,
                probe_id=test_probe.id,
                checked_at=now - timedelta(hours=1),
                status=CheckStatus.up,
                response_time_ms=ms,
            )
        )
    await service_db.flush()

    res = await compute_preview(
        service_db,
        m.id,
        [{"condition": "response_time_above", "threshold_value": 1000}],
    )
    assert res["counts"][0]["count"] == 3


@pytest.mark.asyncio
async def test_response_time_above_zero_threshold_returns_zero(
    service_db: AsyncSession, test_user: User
) -> None:
    m = _new_monitor(test_user, "rt-zero")
    service_db.add(m)
    await service_db.flush()
    res = await compute_preview(
        service_db, m.id, [{"condition": "response_time_above", "threshold_value": None}]
    )
    assert res["counts"][0]["count"] == 0


@pytest.mark.asyncio
async def test_baseline_factor_uses_average(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    m = _new_monitor(test_user, "baseline")
    service_db.add(m)
    await service_db.flush()
    now = datetime.now(UTC)
    # Avg over [200, 200, 200, 200, 1500] = 460 → 2× = 920ms.
    # Only the 1500 sample exceeds.
    for ms in [200, 200, 200, 200, 1500]:
        service_db.add(
            CheckResult(
                monitor_id=m.id,
                probe_id=test_probe.id,
                checked_at=now - timedelta(hours=1),
                status=CheckStatus.up,
                response_time_ms=ms,
            )
        )
    await service_db.flush()

    res = await compute_preview(
        service_db,
        m.id,
        [{"condition": "response_time_above_baseline", "baseline_factor": 2.0}],
    )
    assert res["counts"][0]["count"] == 1


@pytest.mark.asyncio
async def test_baseline_factor_zero_returns_zero(service_db: AsyncSession, test_user: User) -> None:
    m = _new_monitor(test_user, "baseline-zero")
    service_db.add(m)
    await service_db.flush()
    res = await compute_preview(
        service_db,
        m.id,
        [{"condition": "response_time_above_baseline", "baseline_factor": 0}],
    )
    assert res["counts"][0]["count"] == 0


@pytest.mark.asyncio
async def test_anomaly_detection_scales_with_sample_count(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    """At z=3 the tail fraction ≈ 0.27% → 1000 samples → ~3 hits."""
    m = _new_monitor(test_user, "anomaly")
    service_db.add(m)
    await service_db.flush()
    now = datetime.now(UTC)
    for i in range(1000):
        service_db.add(
            CheckResult(
                monitor_id=m.id,
                probe_id=test_probe.id,
                checked_at=now - timedelta(minutes=i),
                status=CheckStatus.up,
                response_time_ms=100,
            )
        )
    await service_db.flush()

    res = await compute_preview(
        service_db,
        m.id,
        [{"condition": "anomaly_detection", "anomaly_zscore_threshold": 3.0}],
    )
    # 0.5 * erfc(3/sqrt(2)) ≈ 0.00135 → ~1 hit out of 1000.
    assert res["counts"][0]["count"] in {1, 2}


@pytest.mark.asyncio
async def test_schema_drift_returns_zero(service_db: AsyncSession, test_user: User) -> None:
    m = _new_monitor(test_user, "drift")
    service_db.add(m)
    await service_db.flush()
    res = await compute_preview(service_db, m.id, [{"condition": "schema_drift"}])
    assert res["counts"][0] == {"condition": "schema_drift", "count": 0}


@pytest.mark.asyncio
async def test_ssl_expiry_counts_warn_results(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    m = _new_monitor(test_user, "ssl")
    service_db.add(m)
    await service_db.flush()
    now = datetime.now(UTC)
    # 1 invalid, 2 with ≤14d, 1 healthy
    service_db.add_all(
        [
            CheckResult(
                monitor_id=m.id,
                probe_id=test_probe.id,
                checked_at=now,
                status=CheckStatus.up,
                ssl_valid=False,
            ),
            CheckResult(
                monitor_id=m.id,
                probe_id=test_probe.id,
                checked_at=now,
                status=CheckStatus.up,
                ssl_valid=True,
                ssl_days_remaining=5,
            ),
            CheckResult(
                monitor_id=m.id,
                probe_id=test_probe.id,
                checked_at=now,
                status=CheckStatus.up,
                ssl_valid=True,
                ssl_days_remaining=14,
            ),
            CheckResult(
                monitor_id=m.id,
                probe_id=test_probe.id,
                checked_at=now,
                status=CheckStatus.up,
                ssl_valid=True,
                ssl_days_remaining=180,
            ),
        ]
    )
    await service_db.flush()

    res = await compute_preview(service_db, m.id, [{"condition": "ssl_expiry"}])
    assert res["counts"][0]["count"] == 3


@pytest.mark.asyncio
async def test_total_aggregates_all_rows(service_db: AsyncSession, test_user: User) -> None:
    m = _new_monitor(test_user, "agg")
    service_db.add(m)
    await service_db.flush()
    await _seed_incidents(service_db, m, 4, scope=IncidentScope.global_)

    res = await compute_preview(
        service_db,
        m.id,
        [
            {"condition": "any_down"},
            {"condition": "all_down"},
            {"condition": "schema_drift"},
        ],
    )
    assert res["total"] == res["counts"][0]["count"] + res["counts"][1]["count"]
