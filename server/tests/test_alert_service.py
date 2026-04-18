"""Tests for the alert service."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertCondition, AlertRule
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.alert import simulate_rule
from whatisup.services.channels._helpers import _validate_webhook_url_sync as _validate_webhook_url

# ── _validate_webhook_url (SSRF guard) ────────────────────────────────────────


def test_validate_webhook_public_url(monkeypatch) -> None:
    # Mock DNS resolution so the test works even when hooks.example.com is unresolvable (CI)
    import socket
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    # Should not raise
    _validate_webhook_url("https://hooks.example.com/abc")


def test_validate_webhook_blocks_localhost() -> None:
    with pytest.raises(ValueError, match="blocked"):
        _validate_webhook_url("http://localhost/hook")


def test_validate_webhook_blocks_127() -> None:
    with pytest.raises(ValueError, match="blocked"):
        _validate_webhook_url("http://127.0.0.1/hook")


def test_validate_webhook_blocks_private_range() -> None:
    with pytest.raises(ValueError, match="internal"):
        _validate_webhook_url("http://10.0.0.1/hook")


def test_validate_webhook_blocks_private_192() -> None:
    with pytest.raises(ValueError, match="internal"):
        _validate_webhook_url("http://192.168.1.100/hook")


# ── simulate_rule ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_simulate_rule_no_target(service_db: AsyncSession, test_user: User) -> None:
    rule = AlertRule(condition=AlertCondition.any_down)
    service_db.add(rule)
    await service_db.flush()

    result = await simulate_rule(service_db, rule)

    assert result["would_fire"] is False
    assert "ciblé" in result["reason"]


@pytest.mark.asyncio
async def test_simulate_rule_any_down_fires(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
) -> None:
    service_db.add(CheckResult(
        monitor_id=test_monitor.id,
        probe_id=test_probe.id,
        checked_at=datetime.now(UTC),
        status=CheckStatus.down,
    ))
    rule = AlertRule(condition=AlertCondition.any_down, monitor_id=test_monitor.id)
    service_db.add(rule)
    await service_db.flush()

    result = await simulate_rule(service_db, rule)

    assert result["would_fire"] is True
    assert test_monitor.name in result["affected_monitors"]


@pytest.mark.asyncio
async def test_simulate_rule_any_down_no_fire_when_up(
    service_db: AsyncSession,
    test_monitor: Monitor,
    test_probe: Probe,
) -> None:
    service_db.add(CheckResult(
        monitor_id=test_monitor.id,
        probe_id=test_probe.id,
        checked_at=datetime.now(UTC),
        status=CheckStatus.up,
    ))
    rule = AlertRule(condition=AlertCondition.any_down, monitor_id=test_monitor.id)
    service_db.add(rule)
    await service_db.flush()

    result = await simulate_rule(service_db, rule)

    assert result["would_fire"] is False


@pytest.mark.asyncio
async def test_simulate_rule_no_monitors_found(
    service_db: AsyncSession, test_user: User
) -> None:
    import uuid
    rule = AlertRule(condition=AlertCondition.any_down, monitor_id=uuid.uuid4())
    service_db.add(rule)
    await service_db.flush()

    result = await simulate_rule(service_db, rule)

    assert result["would_fire"] is False
    assert "trouvé" in result["reason"]
