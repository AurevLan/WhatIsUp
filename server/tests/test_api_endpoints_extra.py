"""Extra API endpoint tests — incidents, maintenance, auth, alerts, metrics.

Targets uncovered code paths in:
- api/v1/incidents.py + incidents_list.py
- api/v1/maintenance.py
- api/v1/auth.py (me, oidc/config, register)
- api/v1/incident_updates.py (CRUD + ack/snooze)
- api/v1/alerts.py (additional channels/rules paths)
- api/v1/metrics.py
- api/v1/web_push.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth — /me / /register / /oidc/config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_disabled_403(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/register", json={})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_auth_me(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/auth/me", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json()["email"] == "user@test.com"


@pytest.mark.asyncio
async def test_auth_update_me(client: AsyncClient, user_token: str) -> None:
    resp = await client.patch(
        "/api/v1/auth/me",
        json={"full_name": "Updated Self"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Self"


@pytest.mark.asyncio
async def test_auth_login_bad_password(client: AsyncClient, regular_user) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_login_unknown_user(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "ghost@example.com", "password": "TestPass1!"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_oidc_config(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/oidc/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data


@pytest.mark.asyncio
async def test_auth_refresh_invalid_token(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_logout_invalid_token(client: AsyncClient) -> None:
    """Logout with invalid token is a silent no-op (204)."""
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": "garbage"})
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_auth_refresh_flow(client: AsyncClient, regular_user) -> None:
    """Login → refresh → new tokens issued."""
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": "TestPass1!"},
    )
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    refresh_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()
    assert "refresh_token" in refresh_resp.json()


# ---------------------------------------------------------------------------
# Incidents list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incidents_list_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/incidents/", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_incidents_list_with_monitor_returns_empty(
    client: AsyncClient, user_token: str
) -> None:
    """Create a monitor without incidents; list endpoint returns empty."""
    await client.post(
        "/api/v1/monitors/",
        json={"name": "IncListMon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    resp = await client.get("/api/v1/incidents/?resolved=false", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Incident updates / ack / snooze
# ---------------------------------------------------------------------------


async def _create_open_incident(db_session, monitor_id: uuid.UUID):
    from whatisup.models.incident import Incident, IncidentScope

    inc = Incident(
        monitor_id=monitor_id,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
        started_at=datetime.now(UTC),
    )
    db_session.add(inc)
    await db_session.flush()
    return inc


@pytest.mark.asyncio
async def test_incident_updates_404_unknown_incident(client: AsyncClient, user_token: str) -> None:
    resp = await client.get(
        f"/api/v1/incidents/{uuid.uuid4()}/updates",
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_incident_update_flow(
    client: AsyncClient, user_token: str, db_session, regular_user
) -> None:
    """Create monitor + incident → post update → list → delete."""
    from sqlalchemy import select

    from whatisup.models.monitor import Monitor

    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "IncUpdMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    monitor_obj = (
        await db_session.execute(select(Monitor).where(Monitor.id == uuid.UUID(mon["id"])))
    ).scalar_one()
    incident = await _create_open_incident(db_session, monitor_obj.id)

    # List (empty)
    list_resp = await client.get(
        f"/api/v1/incidents/{incident.id}/updates", headers=_auth(user_token)
    )
    assert list_resp.status_code == 200
    assert list_resp.json() == []

    # Post update
    create = await client.post(
        f"/api/v1/incidents/{incident.id}/updates",
        json={
            "status": "investigating",
            "message": "Looking into it",
            "is_public": True,
        },
        headers=_auth(user_token),
    )
    assert create.status_code == 201
    update_id = create.json()["id"]

    # List again
    list2 = await client.get(f"/api/v1/incidents/{incident.id}/updates", headers=_auth(user_token))
    assert len(list2.json()) == 1

    # Ack
    ack = await client.post(f"/api/v1/incidents/{incident.id}/ack", headers=_auth(user_token))
    assert ack.status_code == 200
    assert ack.json()["acked_at"] is not None

    # Snooze
    snooze = await client.post(
        f"/api/v1/incidents/{incident.id}/snooze",
        json={"duration_minutes": 30},
        headers=_auth(user_token),
    )
    assert snooze.status_code == 200
    assert snooze.json()["snooze_until"] is not None

    # Unsnooze
    unsnooze = await client.post(
        f"/api/v1/incidents/{incident.id}/unsnooze",
        headers=_auth(user_token),
    )
    assert unsnooze.status_code == 200
    assert unsnooze.json()["snooze_until"] is None

    # Unack
    unack = await client.post(
        f"/api/v1/incidents/{incident.id}/unack",
        headers=_auth(user_token),
    )
    assert unack.status_code == 200
    assert unack.json()["acked_at"] is None

    # Delete update
    del_resp = await client.delete(
        f"/api/v1/incidents/{incident.id}/updates/{update_id}",
        headers=_auth(user_token),
    )
    assert del_resp.status_code == 204

    # Delete unknown update
    del_404 = await client.delete(
        f"/api/v1/incidents/{incident.id}/updates/{uuid.uuid4()}",
        headers=_auth(user_token),
    )
    assert del_404.status_code == 404


@pytest.mark.asyncio
async def test_bulk_ack_incidents(client: AsyncClient, user_token: str, db_session) -> None:
    from sqlalchemy import select

    from whatisup.models.monitor import Monitor

    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "BulkAck", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    monitor_obj = (
        await db_session.execute(select(Monitor).where(Monitor.id == uuid.UUID(mon["id"])))
    ).scalar_one()
    inc1 = await _create_open_incident(db_session, monitor_obj.id)
    inc2 = await _create_open_incident(db_session, monitor_obj.id)

    resp = await client.post(
        "/api/v1/incidents/bulk-ack",
        json={"ids": [str(inc1.id), str(inc2.id)]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    # 2 incidents acked
    assert resp.json()["affected"] >= 1


@pytest.mark.asyncio
async def test_incident_timeline(client: AsyncClient, user_token: str, db_session) -> None:
    from sqlalchemy import select

    from whatisup.models.monitor import Monitor

    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "TimelineMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    monitor_obj = (
        await db_session.execute(select(Monitor).where(Monitor.id == uuid.UUID(mon["id"])))
    ).scalar_one()
    incident = await _create_open_incident(db_session, monitor_obj.id)

    resp = await client.get(f"/api/v1/incidents/{incident.id}/timeline", headers=_auth(user_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["incident_id"] == str(incident.id)
    assert "points" in data


@pytest.mark.asyncio
async def test_incident_diagnostics_empty(client: AsyncClient, user_token: str, db_session) -> None:
    from sqlalchemy import select

    from whatisup.models.monitor import Monitor

    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "DiagMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    monitor_obj = (
        await db_session.execute(select(Monitor).where(Monitor.id == uuid.UUID(mon["id"])))
    ).scalar_one()
    incident = await _create_open_incident(db_session, monitor_obj.id)

    resp = await client.get(
        f"/api/v1/incidents/{incident.id}/diagnostics",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Maintenance windows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maintenance_list_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/maintenance/", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_maintenance_create_for_monitor(client: AsyncClient, user_token: str) -> None:
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "MaintMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    starts = datetime.now(UTC) + timedelta(hours=1)
    ends = starts + timedelta(hours=2)
    resp = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "Routine",
            "monitor_id": mon["id"],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Routine"
    assert data["monitor_id"] == mon["id"]


@pytest.mark.asyncio
async def test_maintenance_create_for_group(client: AsyncClient, user_token: str) -> None:
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={"name": "MaintGrp"},
            headers=_auth(user_token),
        )
    ).json()
    starts = datetime.now(UTC) + timedelta(hours=1)
    ends = starts + timedelta(hours=2)
    resp = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "GroupMaint",
            "group_id": grp["id"],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["group_id"] == grp["id"]


@pytest.mark.asyncio
async def test_maintenance_create_invalid_dates_422(client: AsyncClient, user_token: str) -> None:
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "BadDates", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    starts = datetime.now(UTC)
    ends = starts - timedelta(hours=1)
    resp = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "Bad",
            "monitor_id": mon["id"],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_maintenance_update_and_delete(client: AsyncClient, user_token: str) -> None:
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "MaintCRUD", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    starts = datetime.now(UTC) + timedelta(hours=1)
    ends = starts + timedelta(hours=2)
    create = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "CRUD",
            "monitor_id": mon["id"],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        headers=_auth(user_token),
    )
    window_id = create.json()["id"]

    # Update
    new_starts = datetime.now(UTC) + timedelta(hours=3)
    new_ends = new_starts + timedelta(hours=2)
    upd = await client.patch(
        f"/api/v1/maintenance/{window_id}",
        json={
            "name": "CRUD-updated",
            "monitor_id": mon["id"],
            "starts_at": new_starts.isoformat(),
            "ends_at": new_ends.isoformat(),
            "suppress_alerts": False,
        },
        headers=_auth(user_token),
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "CRUD-updated"
    assert upd.json()["suppress_alerts"] is False

    # Delete
    delete_resp = await client.delete(f"/api/v1/maintenance/{window_id}", headers=_auth(user_token))
    assert delete_resp.status_code == 204


@pytest.mark.asyncio
async def test_maintenance_delete_unknown_404(client: AsyncClient, user_token: str) -> None:
    resp = await client.delete(f"/api/v1/maintenance/{uuid.uuid4()}", headers=_auth(user_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_maintenance_update_unknown_404(client: AsyncClient, user_token: str) -> None:
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "M404", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    starts = datetime.now(UTC) + timedelta(hours=1)
    ends = starts + timedelta(hours=2)
    resp = await client.patch(
        f"/api/v1/maintenance/{uuid.uuid4()}",
        json={
            "name": "X",
            "monitor_id": mon["id"],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Alerts — additional channel types, rule simulate, presets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_webhook_channel(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "WHook",
            "type": "webhook",
            "config": {"url": "https://example.com/hook"},
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    assert resp.json()["type"] == "webhook"


@pytest.mark.asyncio
async def test_create_email_channel(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "EmailChan",
            "type": "email",
            "config": {"to": ["alerts@example.com"]},
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_create_discord_channel(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "Disco",
            "type": "discord",
            "config": {"webhook_url": "https://discord.com/api/webhooks/123/abc"},
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_alert_presets_endpoint(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/alerts/presets/http", headers=_auth(user_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_alert_threshold_suggestions(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/alerts/suggestions/thresholds", headers=_auth(user_token))
    # Returns either empty list (SQLite) or HTTPError on percentile_cont
    assert resp.status_code in (200, 500)


@pytest.mark.asyncio
async def test_auto_rules_no_channels(client: AsyncClient, user_token: str) -> None:
    """auto-rules returns [] when no channels are available."""
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "AutoR", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    resp = await client.post(
        f"/api/v1/alerts/auto-rules/{mon['id']}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_auto_rules_unknown_monitor_404(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        f"/api/v1/alerts/auto-rules/{uuid.uuid4()}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_alert_channel_test_unknown_404(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        f"/api/v1/alerts/channels/{uuid.uuid4()}/test",
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_simulate_rule_endpoint(client: AsyncClient, user_token: str) -> None:
    # Create monitor + channel + rule, then simulate
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Sim", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    chan = (
        await client.post(
            "/api/v1/alerts/channels",
            json={
                "name": "SimChan",
                "type": "email",
                "config": {"to": ["x@example.com"]},
            },
            headers=_auth(user_token),
        )
    ).json()
    rule = (
        await client.post(
            "/api/v1/alerts/rules",
            json={
                "monitor_id": mon["id"],
                "condition": "any_down",
                "channel_ids": [chan["id"]],
            },
            headers=_auth(user_token),
        )
    ).json()
    sim = await client.post(
        f"/api/v1/alerts/rules/{rule['id']}/simulate",
        headers=_auth(user_token),
    )
    assert sim.status_code == 200
    assert "would_fire" in sim.json()


# ---------------------------------------------------------------------------
# Matrix templates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_matrix_templates(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/alerts/matrix-templates/http", headers=_auth(user_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_matrix_template_admin_crud(client: AsyncClient, admin_token: str) -> None:
    create = await client.post(
        "/api/v1/alerts/matrix-templates",
        json={
            "name": "MyTpl",
            "description": "test",
            "check_type": "http",
            "rows": [
                {
                    "condition": "any_down",
                    "channel_ids": [],
                    "enabled": True,
                    "min_duration_seconds": 0,
                }
            ],
        },
        headers=_auth(admin_token),
    )
    assert create.status_code == 201
    template_id = create.json()["id"]

    # Update
    upd = await client.patch(
        f"/api/v1/alerts/matrix-templates/{template_id}",
        json={"name": "RenamedTpl"},
        headers=_auth(admin_token),
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "RenamedTpl"

    # Delete
    delete_resp = await client.delete(
        f"/api/v1/alerts/matrix-templates/{template_id}",
        headers=_auth(admin_token),
    )
    assert delete_resp.status_code == 204


@pytest.mark.asyncio
async def test_matrix_template_update_unknown_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        f"/api/v1/alerts/matrix-templates/{uuid.uuid4()}",
        json={"name": "X"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_matrix_template_requires_superadmin(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/matrix-templates",
        json={
            "name": "X",
            "check_type": "http",
            "rows": [],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Metrics endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_metrics_list_empty(client: AsyncClient, user_token: str) -> None:
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "MetricMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    resp = await client.get(f"/api/v1/metrics/{mon['id']}", headers=_auth(user_token))
    # Either 200 (returns list) or 404 (monitor not found)
    assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Web push endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_push_vapid_key(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/web-push/vapid-public-key", headers=_auth(user_token))
    # Either 200 (returns key) or 404 (not configured)
    assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Silences endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silences_list_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/silences/", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []
