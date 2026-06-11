"""Contract test: the heartbeat payload must carry every checker-relevant field.

Regression guard for the toggle-orphan anti-pattern: ProbeMonitorConfig has
defaults (None/False), so a field configured in the UI but forgotten in the
heartbeat construction is silently ignored by the probe (the advanced HTTP
assertions body_regex/expected_headers/json_schema/schema_drift_enabled were
inert because of exactly this).
"""

from __future__ import annotations

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.probe import Probe

_PROBE_KEY = "wiu_contract_probe_key_only_used_in_tests"
_PROBE_HEADERS = {"X-Probe-Api-Key": _PROBE_KEY}


@pytest_asyncio.fixture
async def probe_with_key(db_session: AsyncSession) -> Probe:
    key_hash = bcrypt.hashpw(_PROBE_KEY.encode(), bcrypt.gensalt(rounds=4)).decode()
    probe = Probe(name="contract-probe", location_name="Test DC", api_key_hash=key_hash)
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest.mark.asyncio
async def test_heartbeat_carries_advanced_http_assertions(
    client: AsyncClient, user_token: str, probe_with_key: Probe
) -> None:
    """body_regex / expected_headers / json_schema / schema_drift_enabled
    configured on a monitor must reach the probe via the heartbeat."""
    created = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Advanced HTTP",
            "url": "https://example.com",
            "body_regex": "status.?ok",
            "expected_headers": {"X-Frame-Options": "DENY"},
            "json_schema": {"type": "object", "required": ["status"]},
            "schema_drift_enabled": True,
            "keyword": "needle",
            "keyword_negate": True,
            "custom_headers": {"X-Probe": "1"},
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert created.status_code == 201, created.text
    monitor_id = created.json()["id"]

    resp = await client.post("/api/v1/probes/heartbeat", json={}, headers=_PROBE_HEADERS)
    assert resp.status_code == 200
    configs = {m["id"]: m for m in resp.json()["monitors"]}
    cfg = configs.get(monitor_id)
    assert cfg is not None, "monitor missing from heartbeat payload"

    assert cfg["body_regex"] == "status.?ok"
    assert cfg["expected_headers"] == {"X-Frame-Options": "DENY"}
    assert cfg["json_schema"] == {"type": "object", "required": ["status"]}
    assert cfg["schema_drift_enabled"] is True
    # Already-wired fields, pinned so they never regress either
    assert cfg["keyword"] == "needle"
    assert cfg["keyword_negate"] is True
    assert cfg["custom_headers"] == {"X-Probe": "1"}


@pytest.mark.asyncio
async def test_heartbeat_defaults_when_not_configured(
    client: AsyncClient, user_token: str, probe_with_key: Probe
) -> None:
    created = await client.post(
        "/api/v1/monitors/",
        json={"name": "Plain HTTP", "url": "https://plain.example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert created.status_code == 201, created.text
    monitor_id = created.json()["id"]

    resp = await client.post("/api/v1/probes/heartbeat", json={}, headers=_PROBE_HEADERS)
    cfg = {m["id"]: m for m in resp.json()["monitors"]}[monitor_id]

    assert cfg["body_regex"] is None
    assert cfg["expected_headers"] is None
    assert cfg["json_schema"] is None
    assert cfg["schema_drift_enabled"] is False
