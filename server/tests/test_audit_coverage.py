"""Regression tests — audit log coverage (finding M3).

Each test verifies that a state-changing mutation produces an AuditLog entry
with the correct action / object_type.  No secrets must appear in audit details.
"""

from __future__ import annotations

import uuid
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
    secret_url = "https://hooks.example.com/x"
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "AuditCh",
            "type": "webhook",
            "config": {"url": secret_url},
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    entries = await _audit_entries(db_session, "alert_channel.create")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "alert_channel"
    assert entry.object_name == "AuditCh"
    assert entry.user_id is not None
    # The webhook URL is Fernet-encrypted at rest (core CLAUDE.md secret list) — its
    # *value* must never leak into the audit trail, whatever key it's nested under.
    assert secret_url not in str(entry.diff)
    assert secret_url not in (entry.object_name or "")


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
    assert entry.user_id is not None
    # monitor_id in the diff disambiguates identical conditions across monitors.
    assert entry.diff["monitor_id"] == monitor_id


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
    assert entry.diff["monitor_id"] == monitor_id


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
    assert entry.diff["monitor_id"] == monitor_id


# ── AlertRule bulk endpoints (matrix PUT / auto-rules) ───────────────────────
#
# These bypass create_rule/update_rule/delete_rule entirely (they touch
# AlertRule rows directly), so they need their own synthetic trace — see
# finding M-major #1/#2 in the audit-coverage follow-up review.


@pytest.mark.asyncio
async def test_audit_alert_matrix_update(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "MatrixMon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]
    ch = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "MatrixCh",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/matrix"},
        },
        headers=_auth(user_token),
    )
    channel_id = ch.json()["id"]

    # First PUT: create two rows.
    resp = await client.put(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix",
        json={
            "rows": [
                {"condition": "any_down", "channel_ids": [channel_id]},
                {"condition": "all_down", "channel_ids": [channel_id]},
            ]
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    entries = await _audit_entries(db_session, "alert_rule.matrix_update")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.object_type == "monitor"
    assert entry.object_id == uuid.UUID(monitor_id)
    assert entry.object_name == "MatrixMon"
    assert entry.user_id is not None
    assert entry.diff["created"] == 2
    assert entry.diff["updated"] == 0
    assert entry.diff["deleted"] == 0
    assert set(entry.diff["created_conditions"]) == {"any_down", "all_down"}

    # Second PUT: keep any_down (updated), drop all_down (deleted) — one trace per request,
    # not one per underlying AlertRule mutation.
    resp = await client.put(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix",
        json={"rows": [{"condition": "any_down", "channel_ids": [channel_id], "enabled": False}]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    entries = await _audit_entries(db_session, "alert_rule.matrix_update")
    assert len(entries) == 2
    entry = entries[-1]
    assert entry.diff["created"] == 0
    assert entry.diff["updated"] == 1
    assert entry.diff["deleted"] == 1
    assert entry.diff["updated_conditions"] == ["any_down"]
    assert entry.diff["deleted_conditions"] == ["all_down"]


@pytest.mark.asyncio
async def test_audit_alert_auto_rules(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "AutoRuleMon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]
    ch = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "AutoCh",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/auto"},
        },
        headers=_auth(user_token),
    )
    channel_id = ch.json()["id"]

    resp = await client.post(
        f"/api/v1/alerts/auto-rules/{monitor_id}",
        params={"channel_ids": [channel_id]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    entries = await _audit_entries(db_session, "alert_rule.auto_create")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.object_type == "monitor"
    assert entry.object_id == uuid.UUID(monitor_id)
    assert entry.object_name == "AutoRuleMon"
    assert entry.user_id is not None
    assert entry.diff["created"] == len(resp.json())
    assert entry.diff["created"] > 0
    assert set(entry.diff["conditions"]) == {r["condition"] for r in resp.json()}


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
    assert entry.user_id is not None


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
    # Regression: log_action used to be called with user=None despite the
    # authenticated superadmin being available — traces were anonymous.
    assert entry.user_id is not None
    assert entry.diff == {"is_active": False}


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
    assert entry.user_id is not None


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
    assert entry.user_id is not None


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


# ── UserApiKey ────────────────────────────────────────────────────────────────
#
# Regression: api_keys.py used to pass `current_user.id` (a bare uuid.UUID) as the
# `user` positional arg of log_action(), which expects a `User` object. log_action's
# `user.id if user else None` then raised AttributeError('id') on the UUID, which
# was swallowed by log_action's own try/except — so these two traces were NEVER
# written, silently. Assert both the entry AND its attribution to catch a repeat.


@pytest.mark.asyncio
async def test_audit_api_key_create(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/api-keys/",
        json={"name": "AuditKey"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    entries = await _audit_entries(db_session, "api_key.create")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "api_key"
    assert entry.object_name == "AuditKey"
    assert entry.user_id is not None
    assert entry.user_email is not None
    # The raw key itself must never be persisted in the audit trail.
    raw_key = resp.json()["key"]
    assert raw_key not in str(entry.diff)


@pytest.mark.asyncio
async def test_audit_api_key_revoke(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/v1/api-keys/",
        json={"name": "KeyToRevoke"},
        headers=_auth(user_token),
    )
    key_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/api-keys/{key_id}", headers=_auth(user_token))
    assert resp.status_code == 204
    entries = await _audit_entries(db_session, "api_key.revoke")
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.object_type == "api_key"
    assert entry.object_name == "KeyToRevoke"
    assert entry.user_id is not None
    assert entry.user_email is not None
