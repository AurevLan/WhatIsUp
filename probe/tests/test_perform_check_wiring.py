"""Contract test: perform_check must forward every config field to the checker.

Regression guard for the toggle-orphan anti-pattern on the probe side:
dns_nameservers was supported by the DNS checker and sent by the server,
but perform_check never forwarded it — custom nameservers were silently
ignored and checks always used the system resolver.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from whatisup_probe.checkers import REGISTRY, perform_check
from whatisup_probe.checkers.base import CheckResult


@pytest.mark.asyncio
async def test_perform_check_forwards_dns_nameservers(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def capture_check(monitor_id: str, config: dict, **kwargs: Any) -> CheckResult:
        captured.update(config)
        return CheckResult(monitor_id=monitor_id, checked_at=datetime.now(UTC), status="up")

    monkeypatch.setattr(REGISTRY["dns"], "check", capture_check)

    await perform_check(
        monitor_id="dns-wiring",
        url="http://example.com",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="dns",
        dns_record_type="A",
        dns_expected_value="93.184.216.34",
        dns_nameservers=["9.9.9.9", "149.112.112.112"],
    )

    assert captured["dns_nameservers"] == ["9.9.9.9", "149.112.112.112"]
    assert captured["dns_record_type"] == "A"
    assert captured["dns_expected_value"] == "93.184.216.34"


@pytest.mark.asyncio
async def test_perform_check_forwards_advanced_http_fields(monkeypatch) -> None:
    """Pin the rest of the config contract so a new field can't go orphan silently."""
    captured: dict[str, Any] = {}

    async def capture_check(monitor_id: str, config: dict, **kwargs: Any) -> CheckResult:
        captured.update(config)
        return CheckResult(monitor_id=monitor_id, checked_at=datetime.now(UTC), status="up")

    monkeypatch.setattr(REGISTRY["http"], "check", capture_check)

    await perform_check(
        monitor_id="http-wiring",
        url="https://example.com",
        timeout_seconds=5,
        follow_redirects=False,
        expected_status_codes=[200, 301],
        ssl_check_enabled=True,
        body_regex="ok",
        expected_headers={"X-A": "1"},
        json_schema={"type": "object"},
        custom_headers={"User-Agent": "test"},
        schema_drift_enabled=True,
        keyword="needle",
        keyword_negate=True,
    )

    assert captured["body_regex"] == "ok"
    assert captured["expected_headers"] == {"X-A": "1"}
    assert captured["json_schema"] == {"type": "object"}
    assert captured["custom_headers"] == {"User-Agent": "test"}
    assert captured["schema_drift_enabled"] is True
    assert captured["keyword"] == "needle"
    assert captured["keyword_negate"] is True
    assert captured["follow_redirects"] is False
