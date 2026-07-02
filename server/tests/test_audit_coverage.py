"""Regression tests — audit log coverage (finding M3).

Each test verifies that a state-changing mutation produces an AuditLog entry
with the correct action / object_type.  No secrets must appear in audit details.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.audit_log import AuditLog


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _audit_entries(db: AsyncSession, action: str) -> list[AuditLog]:
    result = await db.execute(select(AuditLog).where(AuditLog.action == action))
    return list(result.scalars().all())


# ── AlertChannel ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_alert_channel_create(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "AuditCh",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/x"},
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    entries = await _audit_entries(db_session, "alert_channel.create")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "alert_channel"
    assert entry.object_name == "AuditCh"
    # No secret in diff
    if entry.diff:
        for key in ("config", "url", "bot_token", "webhook_url", "api_key", "webhook_secret"):
            assert key not in str(entry.diff).lower() or entry.diff.get(key) is None


@pytest.mark.asyncio
async def test_audit_alert_channel_delete(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/v1/alerts/channels",
        json={"name": "DelCh", "type": "webhook", "config": {"url": "https://hooks.example.com/d"}},
        headers=_auth(user_token),
    )
    channel_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/alerts/channels/{channel_id}", headers=_auth(user_token))
    assert resp.status_code == 204
    entries = await _audit_entries(db_session, "alert_channel.delete")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "alert_channel"
    assert entry.object_name == "DelCh"


# ── AlertRule ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_alert_rule_create(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    # Need a monitor and channel first
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "RuleMon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]
    ch = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "RuleCh",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/r"},
        },
        headers=_auth(user_token),
    )
    channel_id = ch.json()["id"]

    resp = await client.post(
        "/api/v1/alerts/rules",
        json={"monitor_id": monitor_id, "condition": "any_down", "channel_ids": [channel_id]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    entries = await _audit_entries(db_session, "alert_rule.create")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "alert_rule"
    assert entry.object_name == "any_down"


@pytest.mark.asyncio
async def test_audit_alert_rule_update(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "RuleMonU", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]
    ch = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "RuleChU",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/u"},
        },
        headers=_auth(user_token),
    )
    channel_id = ch.json()["id"]
    rule = await client.post(
        "/api/v1/alerts/rules",
        json={"monitor_id": monitor_id, "condition": "any_down", "channel_ids": [channel_id]},
        headers=_auth(user_token),
    )
    rule_id = rule.json()["id"]

    resp = await client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        json={"enabled": False},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    entries = await _audit_entries(db_session, "alert_rule.update")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "alert_rule"


@pytest.mark.asyncio
async def test_audit_alert_rule_delete(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "RuleMonD", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]
    ch = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "RuleChD",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/dd"},
        },
        headers=_auth(user_token),
    )
    channel_id = ch.json()["id"]
    rule = await client.post(
        "/api/v1/alerts/rules",
        json={"monitor_id": monitor_id, "condition": "any_down", "channel_ids": [channel_id]},
        headers=_auth(user_token),
    )
    rule_id = rule.json()["id"]

    resp = await client.delete(f"/api/v1/alerts/rules/{rule_id}", headers=_auth(user_token))
    assert resp.status_code == 204
    entries = await _audit_entries(db_session, "alert_rule.delete")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "alert_rule"
    assert entry.object_name == "any_down"


# ── MonitorGroup ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_group_create(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/groups/",
        json={"name": "AuditGroup"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    entries = await _audit_entries(db_session, "group.create")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "group"
    assert entry.object_name == "AuditGroup"


@pytest.mark.asyncio
async def test_audit_group_update(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/v1/groups/",
        json={"name": "GroupBeforeUpdate"},
        headers=_auth(user_token),
    )
    group_id = create.json()["id"]
    resp = await client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "GroupAfterUpdate"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    entries = await _audit_entries(db_session, "group.update")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "group"
    assert entry.object_name == "GroupAfterUpdate"


@pytest.mark.asyncio
async def test_audit_group_delete(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/v1/groups/",
        json={"name": "GroupToDelete"},
        headers=_auth(user_token),
    )
    group_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/groups/{group_id}", headers=_auth(user_token))
    assert resp.status_code == 204
    entries = await _audit_entries(db_session, "group.delete")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "group"
    assert entry.object_name == "GroupToDelete"


# ── Probe PATCH (revocation de facto) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_probe_update(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    """Deactivating a probe via PATCH is a de-facto revocation; must be audited."""
    from whatisup.models.probe import Probe

    probe = Probe(name="audit-probe", location_name="Paris", api_key_hash="x")
    db_session.add(probe)
    await db_session.flush()

    resp = await client.patch(
        f"/api/v1/probes/{probe.id}",
        json={"is_active": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    entries = await _audit_entries(db_session, "probe.update")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "probe"
    assert entry.object_name == "audit-probe"


# ── MaintenanceWindow ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_maintenance_create(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "MaintMon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]
    now = datetime.now(UTC)
    resp = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "AuditMaint",
            "monitor_id": monitor_id,
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    entries = await _audit_entries(db_session, "maintenance.create")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "maintenance_window"
    assert entry.object_name == "AuditMaint"


@pytest.mark.asyncio
async def test_audit_maintenance_delete(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "MaintMonDel", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]
    now = datetime.now(UTC)
    create = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "MaintToDel",
            "monitor_id": monitor_id,
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
        headers=_auth(user_token),
    )
    window_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/maintenance/{window_id}", headers=_auth(user_token))
    assert resp.status_code == 204
    entries = await _audit_entries(db_session, "maintenance.delete")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "maintenance_window"


@pytest.mark.asyncio
async def test_audit_maintenance_update(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "MaintMonUpd", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]
    now = datetime.now(UTC)
    create = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "MaintToUpd",
            "monitor_id": monitor_id,
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
        headers=_auth(user_token),
    )
    window_id = create.json()["id"]
    resp = await client.patch(
        f"/api/v1/maintenance/{window_id}",
        json={
            "name": "MaintUpdated",
            "monitor_id": monitor_id,
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    entries = await _audit_entries(db_session, "maintenance.update")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "maintenance_window"
    assert entry.object_name == "MaintUpdated"


# ── MonitorTemplate ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_template_create(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/templates/",
        json={
            "name": "AuditTpl",
            "monitor_config": {"name": "{{NAME}}", "url": "https://example.com"},
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    entries = await _audit_entries(db_session, "template.create")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "monitor_template"
    assert entry.object_name == "AuditTpl"


@pytest.mark.asyncio
async def test_audit_template_update(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/v1/templates/",
        json={
            "name": "TplToUpd",
            "monitor_config": {"name": "X", "url": "https://example.com"},
        },
        headers=_auth(user_token),
    )
    tpl_id = create.json()["id"]
    resp = await client.patch(
        f"/api/v1/templates/{tpl_id}",
        json={"name": "TplUpdated"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    entries = await _audit_entries(db_session, "template.update")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "monitor_template"
    assert entry.object_name == "TplUpdated"


@pytest.mark.asyncio
async def test_audit_template_delete(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/v1/templates/",
        json={
            "name": "TplToDel",
            "monitor_config": {"name": "X", "url": "https://example.com"},
        },
        headers=_auth(user_token),
    )
    tpl_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/templates/{tpl_id}", headers=_auth(user_token))
    assert resp.status_code == 204
    entries = await _audit_entries(db_session, "template.delete")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "monitor_template"
    assert entry.object_name == "TplToDel"
