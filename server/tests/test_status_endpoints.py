"""Status / Public / TLS Fleet / Templates endpoint tests — coverage boost."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Status endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_all_monitors_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/status/monitors", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_status_all_monitors_returns_list(client: AsyncClient, user_token: str) -> None:
    await client.post(
        "/api/v1/monitors/",
        json={"name": "SMon1", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    await client.post(
        "/api/v1/monitors/",
        json={"name": "SMon2", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    resp = await client.get("/api/v1/status/monitors", headers=_auth(user_token))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    for it in items:
        assert "status" in it
        # Unknown because no check_result was recorded
        assert it["status"] == "unknown"
        assert it["incident"] is None


@pytest.mark.asyncio
async def test_status_monitor_detail_404(client: AsyncClient, user_token: str) -> None:
    import uuid

    resp = await client.get(
        f"/api/v1/status/monitors/{uuid.uuid4()}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_monitor_detail_ok(client: AsyncClient, user_token: str) -> None:
    m = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "SMonDetail", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    resp = await client.get(f"/api/v1/status/monitors/{m['id']}", headers=_auth(user_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "SMonDetail"
    assert "uptime_24h_percent" in data
    assert "uptime_7d_percent" in data


@pytest.mark.asyncio
async def test_status_summary_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/status/summary", headers=_auth(user_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "operational"
    assert data["components"] == []


@pytest.mark.asyncio
async def test_status_summary_with_monitors(client: AsyncClient, user_token: str) -> None:
    for i in range(3):
        await client.post(
            "/api/v1/monitors/",
            json={"name": f"SumMon{i}", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    resp = await client.get("/api/v1/status/summary", headers=_auth(user_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "operational"
    assert data["total_count"] == 3
    assert data["down_count"] == 0
    assert len(data["components"]) == 3


# ---------------------------------------------------------------------------
# Public status pages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_page_unknown_slug_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/public/pages/nope")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_public_page_full_flow(client: AsyncClient, user_token: str) -> None:
    """Create a group with a public_slug then hit every public/* endpoint."""
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={
                "name": "PubGroup",
                "public_slug": "pubgroup",
                "public_title": "My Status",
                "public_description": "All systems green",
            },
            headers=_auth(user_token),
        )
    ).json()

    # Create a monitor in the group
    await client.post(
        "/api/v1/monitors/",
        json={"name": "PubMon", "url": "https://example.com", "group_id": grp["id"]},
        headers=_auth(user_token),
    )

    # 1) Page meta
    r1 = await client.get("/api/v1/public/pages/pubgroup")
    assert r1.status_code == 200
    assert r1.json()["name"] == "PubGroup"
    assert r1.json()["slug"] == "pubgroup"

    # 2) Monitors list
    r2 = await client.get("/api/v1/public/pages/pubgroup/monitors")
    assert r2.status_code == 200
    items = r2.json()
    assert len(items) == 1
    assert items[0]["name"] == "PubMon"
    assert "history_90d" in items[0]
    assert len(items[0]["history_90d"]) == 90

    # 3) Status (incidents_30d)
    r3 = await client.get("/api/v1/public/pages/pubgroup/status")
    assert r3.status_code == 200
    assert r3.json()["incidents_30d"] == []


@pytest.mark.asyncio
async def test_public_page_subscribe_and_unsubscribe(client: AsyncClient, user_token: str) -> None:
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={"name": "SubGroup", "public_slug": "subgroup"},
            headers=_auth(user_token),
        )
    ).json()
    assert grp["public_slug"] == "subgroup"

    r = await client.post(
        "/api/v1/public/pages/subgroup/subscribe",
        json={"email": "subscriber@example.com"},
    )
    assert r.status_code == 201
    assert "message" in r.json()

    # Duplicate subscription → still 201 (anti-enumeration)
    r2 = await client.post(
        "/api/v1/public/pages/subgroup/subscribe",
        json={"email": "subscriber@example.com"},
    )
    assert r2.status_code == 201

    # Unknown unsubscribe token → 404
    r3 = await client.get("/api/v1/public/pages/subgroup/unsubscribe?token=invalid")
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_public_incident_updates_404(client: AsyncClient, user_token: str) -> None:
    import uuid

    await client.post(
        "/api/v1/groups/",
        json={"name": "IncGrp", "public_slug": "incgrp"},
        headers=_auth(user_token),
    )
    resp = await client.get(f"/api/v1/public/pages/incgrp/incidents/{uuid.uuid4()}/updates")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_public_badge_not_found(client: AsyncClient, user_token: str) -> None:
    await client.post(
        "/api/v1/groups/",
        json={"name": "BadgeGrp", "public_slug": "badgegrp"},
        headers=_auth(user_token),
    )
    # Monitor name not in group → still returns a "not found" SVG with 200
    resp = await client.get("/api/v1/public/badge/badgegrp/unknown-monitor")
    assert resp.status_code == 200
    assert "svg" in resp.headers["content-type"].lower()
    assert b"not found" in resp.content


@pytest.mark.asyncio
async def test_public_badge_with_monitor(client: AsyncClient, user_token: str) -> None:
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={"name": "BG", "public_slug": "bggrp"},
            headers=_auth(user_token),
        )
    ).json()
    await client.post(
        "/api/v1/monitors/",
        json={"name": "BadgeMon", "url": "https://example.com", "group_id": grp["id"]},
        headers=_auth(user_token),
    )
    resp = await client.get("/api/v1/public/badge/bggrp/BadgeMon")
    assert resp.status_code == 200
    assert "svg" in resp.headers["content-type"].lower()
    assert b"uptime" in resp.content


# ---------------------------------------------------------------------------
# TLS Fleet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tls_fleet_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/tls-fleet/", headers=_auth(user_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_tls_fleet_csv_format(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/tls-fleet/?fmt=csv", headers=_auth(user_token))
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    # CSV header line present
    assert b"monitor_name" in resp.content


@pytest.mark.asyncio
async def test_tls_fleet_with_data(
    client: AsyncClient, user_token: str, db_session, regular_user
) -> None:
    """Insert a CheckResult with tls_audit and verify the fleet endpoint enriches it."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from whatisup.models.monitor import Monitor
    from whatisup.models.result import CheckResult, CheckStatus

    m = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "TLSMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()

    # Insert a TLS audit
    import uuid

    monitor_obj = (
        await db_session.execute(select(Monitor).where(Monitor.id == uuid.UUID(m["id"])))
    ).scalar_one()
    cr = CheckResult(
        monitor_id=monitor_obj.id,
        status=CheckStatus.up,
        checked_at=datetime.now(UTC),
        tls_audit={
            "grade": "B",
            "tls_version": "TLS 1.2",
            "cipher_name": "ECDHE-RSA",
            "san_match": True,
            "days_remaining": 45,
            "expires_at": "2026-12-31",
        },
    )
    db_session.add(cr)
    await db_session.flush()

    # JSON, no filter
    r = await client.get("/api/v1/tls-fleet/", headers=_auth(user_token))
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["grade"] == "B"

    # Filter: grade_below=A (grade B is worse than A → matches)
    r2 = await client.get("/api/v1/tls-fleet/?grade_below=A", headers=_auth(user_token))
    assert r2.status_code == 200
    assert r2.json()["count"] == 1

    # Filter: grade_below=F (grade B is better than F → filtered out)
    r3 = await client.get("/api/v1/tls-fleet/?grade_below=F", headers=_auth(user_token))
    assert r3.status_code == 200
    assert r3.json()["count"] == 0

    # Filter: expires_within_days=10 (45 > 10 → filtered out)
    r4 = await client.get("/api/v1/tls-fleet/?expires_within_days=10", headers=_auth(user_token))
    assert r4.status_code == 200
    assert r4.json()["count"] == 0

    # CSV export with data
    r5 = await client.get("/api/v1/tls-fleet/?fmt=csv", headers=_auth(user_token))
    assert r5.status_code == 200
    assert b"TLSMon" in r5.content


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_templates_list_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/templates/", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_templates_create_and_get(client: AsyncClient, user_token: str) -> None:
    payload = {
        "name": "tpl1",
        "description": "test template",
        "variables": [
            {"name": "URL", "description": "target URL", "default": "https://example.com"}
        ],
        "monitor_config": {"name": "{{ NAME }}", "url": "{{ URL }}", "interval_seconds": 60},
        "is_public": False,
    }
    create = await client.post("/api/v1/templates/", json=payload, headers=_auth(user_token))
    assert create.status_code == 201
    tpl = create.json()
    assert tpl["name"] == "tpl1"
    template_id = tpl["id"]

    # GET
    get_resp = await client.get(f"/api/v1/templates/{template_id}", headers=_auth(user_token))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == template_id

    # GET unknown
    import uuid

    not_found = await client.get(f"/api/v1/templates/{uuid.uuid4()}", headers=_auth(user_token))
    assert not_found.status_code == 404


@pytest.mark.asyncio
async def test_templates_update(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/templates/",
        json={
            "name": "tpl_upd",
            "monitor_config": {"url": "https://example.com"},
        },
        headers=_auth(user_token),
    )
    template_id = create.json()["id"]
    upd = await client.patch(
        f"/api/v1/templates/{template_id}",
        json={"name": "renamed", "is_public": True},
        headers=_auth(user_token),
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "renamed"
    assert upd.json()["is_public"] is True


@pytest.mark.asyncio
async def test_templates_update_unknown_404(client: AsyncClient, user_token: str) -> None:
    import uuid

    resp = await client.patch(
        f"/api/v1/templates/{uuid.uuid4()}",
        json={"name": "x"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_templates_delete(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/templates/",
        json={
            "name": "tpl_del",
            "monitor_config": {"url": "https://example.com"},
        },
        headers=_auth(user_token),
    )
    template_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/templates/{template_id}", headers=_auth(user_token))
    assert resp.status_code == 204

    # Second delete → 404
    resp2 = await client.delete(f"/api/v1/templates/{template_id}", headers=_auth(user_token))
    assert resp2.status_code == 404
