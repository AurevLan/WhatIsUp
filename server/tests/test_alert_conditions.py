"""R-1 — shared alert-condition predicates + full-coverage preview.

``fire_alerts`` and ``simulate_rule`` used to reimplement condition matching
independently and silently diverged (the preview knew 4 of the value-based
conditions the dispatch handles). Both now share the pure predicates in
``services/alert_conditions.py``; the guard test at the bottom fails if a new
``AlertCondition`` member ships without preview support.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertCondition, AlertRule
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.alert import simulate_rule
from whatisup.services.alert_conditions import (
    above_baseline_matches,
    anomaly_matches,
    response_time_above_matches,
    schema_drift_matches,
    ssl_expiry_matches,
)

# ── Pure predicates ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ssl_valid", "days", "warn", "expected"),
    [
        (False, None, None, True),  # invalid cert always matches
        (True, 10, 30, True),  # within warn window
        (True, 30, 30, True),  # boundary: <= warn_days
        (True, 31, 30, False),  # outside window
        (True, None, 30, False),  # no expiry info
        (True, 10, None, False),  # no warn window configured
        (None, 10, 30, True),  # unknown validity, expiring soon
    ],
)
def test_ssl_expiry_matches(ssl_valid, days, warn, expected):
    assert ssl_expiry_matches(ssl_valid, days, warn) is expected


@pytest.mark.parametrize(
    ("rt", "threshold", "expected"),
    [
        (500.0, 300.0, True),
        (300.0, 300.0, False),  # strictly above
        (None, 300.0, False),
        (500.0, None, False),  # unset threshold never fires
    ],
)
def test_response_time_above_matches(rt, threshold, expected):
    assert response_time_above_matches(rt, threshold) is expected


@pytest.mark.parametrize(
    ("rt", "avg", "factor", "expected"),
    [
        (500.0, 100.0, 2.0, True),  # 500 > 200
        (150.0, 100.0, 2.0, False),
        (200.0, 100.0, 2.0, False),  # strictly above
        (500.0, None, 2.0, False),  # no history
        (500.0, 0.0, 2.0, False),  # degenerate baseline
        (500.0, 100.0, None, False),  # unset factor
        (None, 100.0, 2.0, False),
    ],
)
def test_above_baseline_matches(rt, avg, factor, expected):
    assert above_baseline_matches(rt, avg, factor) is expected


@pytest.mark.parametrize(
    ("zscore", "threshold", "expected"),
    [
        (4.0, 3.0, True),
        (2.0, 3.0, False),
        (3.0, 3.0, False),  # strictly above
        (3.5, None, True),  # default threshold 3.0
        (None, 3.0, False),  # no history never fires
    ],
)
def test_anomaly_matches(zscore, threshold, expected):
    assert anomaly_matches(zscore, threshold) is expected


@pytest.mark.parametrize(
    ("fp", "baseline", "expected"),
    [
        ("abc", "def", True),
        ("abc", "abc", False),
        (None, "abc", False),
        ("abc", None, False),  # no recorded baseline never fires
        (None, None, False),
    ],
)
def test_schema_drift_matches(fp, baseline, expected):
    assert schema_drift_matches(fp, baseline) is expected


# ── simulate_rule — conditions the preview used to reject ────────────────────


async def _monitor_with_rule(
    db: AsyncSession, user: User, condition: AlertCondition, **rule_kwargs
) -> tuple[Monitor, AlertRule]:
    monitor = Monitor(name=f"sim-{condition}", url="http://x", owner_id=user.id)
    db.add(monitor)
    await db.flush()
    rule = AlertRule(condition=condition, monitor_id=monitor.id, owner_id=user.id, **rule_kwargs)
    db.add(rule)
    await db.flush()
    return monitor, rule


@pytest.mark.asyncio
async def test_simulate_baseline_breach_fires(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    monitor, rule = await _monitor_with_rule(
        service_db, test_user, AlertCondition.response_time_above_baseline, baseline_factor=2.0
    )
    now = datetime.now(UTC)
    # History averaging ~100ms, then a latest sample at 500ms (> 2× avg).
    for i in range(5):
        service_db.add(
            CheckResult(
                monitor_id=monitor.id,
                probe_id=test_probe.id,
                checked_at=now - timedelta(hours=i + 1),
                status=CheckStatus.up,
                response_time_ms=100.0,
            )
        )
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            checked_at=now,
            status=CheckStatus.up,
            response_time_ms=500.0,
        )
    )
    await service_db.flush()

    result = await simulate_rule(service_db, rule)
    assert result["would_fire"] is True
    assert monitor.name in result["affected_monitors"][0]


@pytest.mark.asyncio
async def test_simulate_baseline_without_factor_cannot_fire(
    service_db: AsyncSession, test_user: User
) -> None:
    _, rule = await _monitor_with_rule(
        service_db, test_user, AlertCondition.response_time_above_baseline
    )
    result = await simulate_rule(service_db, rule)
    assert result["would_fire"] is False
    assert "Facteur" in result["reason"]


@pytest.mark.asyncio
async def test_simulate_schema_drift_fires(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    monitor, rule = await _monitor_with_rule(service_db, test_user, AlertCondition.schema_drift)
    monitor.schema_baseline = "baseline-fp"
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            schema_fingerprint="drifted-fp",
        )
    )
    await service_db.flush()

    result = await simulate_rule(service_db, rule)
    assert result["would_fire"] is True
    assert monitor.name in result["affected_monitors"]


@pytest.mark.asyncio
async def test_simulate_schema_drift_without_baseline_cannot_fire(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    monitor, rule = await _monitor_with_rule(service_db, test_user, AlertCondition.schema_drift)
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            schema_fingerprint="whatever",
        )
    )
    await service_db.flush()

    result = await simulate_rule(service_db, rule)
    assert result["would_fire"] is False
    assert "baseline" in result["reason"].lower()


@pytest.mark.asyncio
async def test_simulate_anomaly_fires_on_outlier(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    monitor, rule = await _monitor_with_rule(
        service_db, test_user, AlertCondition.anomaly_detection, anomaly_zscore_threshold=3.0
    )
    now = datetime.now(UTC)
    # 12 samples in the same hour bucket, tight around 100ms, then a 900ms outlier.
    for i in range(12):
        service_db.add(
            CheckResult(
                monitor_id=monitor.id,
                probe_id=test_probe.id,
                checked_at=now - timedelta(minutes=i + 5),
                status=CheckStatus.up,
                response_time_ms=100.0 + (i % 3),
            )
        )
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            checked_at=now,
            status=CheckStatus.up,
            response_time_ms=900.0,
        )
    )
    await service_db.flush()

    result = await simulate_rule(service_db, rule)
    assert result["would_fire"] is True
    assert "z-score" in result["affected_monitors"][0]


@pytest.mark.asyncio
async def test_simulate_anomaly_insufficient_history(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    monitor, rule = await _monitor_with_rule(
        service_db, test_user, AlertCondition.anomaly_detection
    )
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            response_time_ms=100.0,
        )
    )
    await service_db.flush()

    result = await simulate_rule(service_db, rule)
    assert result["would_fire"] is False
    assert "historique" in result["reason"]


@pytest.mark.asyncio
async def test_simulate_response_time_without_threshold_cannot_fire(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    """Parity with fire_alerts: unset threshold never fires (the preview used
    to treat it as 0 and fire on any recorded latency)."""
    monitor, rule = await _monitor_with_rule(
        service_db, test_user, AlertCondition.response_time_above
    )
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            response_time_ms=5000.0,
        )
    )
    await service_db.flush()

    result = await simulate_rule(service_db, rule)
    assert result["would_fire"] is False
    assert "Seuil non défini" in result["reason"]


@pytest.mark.asyncio
async def test_simulate_ssl_invalid_cert_fires(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    """Parity with fire_alerts: an invalid cert fires regardless of expiry."""
    monitor, rule = await _monitor_with_rule(service_db, test_user, AlertCondition.ssl_expiry)
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            ssl_valid=False,
        )
    )
    await service_db.flush()

    result = await simulate_rule(service_db, rule)
    assert result["would_fire"] is True
    assert "invalide" in result["affected_monitors"][0]


# ── Anti-divergence guard ────────────────────────────────────────────────────

# Dead enum value: defined in the model but wired to no dispatch logic, no
# frontend, no preview. If you implement it, add preview support and remove it
# from this set; if you add a NEW condition, this test fails until the preview
# handles it.
_KNOWN_UNSUPPORTED = {AlertCondition.tls_grade_below}


@pytest.mark.asyncio
async def test_every_condition_has_preview_support(
    service_db: AsyncSession, test_user: User
) -> None:
    unsupported = set()
    for condition in AlertCondition:
        _, rule = await _monitor_with_rule(
            service_db, test_user, condition, threshold_value=100.0, baseline_factor=2.0
        )
        result = await simulate_rule(service_db, rule)
        if "non supportée" in result["reason"]:
            unsupported.add(condition)
    assert unsupported == _KNOWN_UNSUPPORTED
