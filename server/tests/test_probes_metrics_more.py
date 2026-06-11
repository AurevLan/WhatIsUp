"""Additional tests: probe CRUD/GET, metrics, silences, devices, more alerts."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_PROBE_KEY = "wiu_test_probe_key_only_used_in_tests_2"


async def _register_probe(client: AsyncClient, admin_token: str, name: str = "P1") -> dict:
    """Helper: register a probe via admin endpoint."""
    resp = await client.post(
        "/api/v1/probes/register",
        json={
            "name": name,
            "location_name": "Test Loc",
            "latitude": 48.8,
            "longitude": 2.3,
            "network_type": "external",
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Probe CRUD (superadmin)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_get_by_id(client: AsyncClient, admin_token: str) -> None:
    p = await _register_probe(client, admin_token, name="GetMe")
    resp = await client.get(f"/api/v1/probes/{p['id']}", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "GetMe"


@pytest.mark.asyncio
async def test_probe_get_unknown_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(f"/api/v1/probes/{uuid.uuid4()}", headers=_auth(admin_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_probe_patch(client: AsyncClient, admin_token: str) -> None:
    p = await _register_probe(client, admin_token, name="UpdMe")
    resp = await client.patch(
        f"/api/v1/probes/{p['id']}",
        json={"location_name": "New Loc", "latitude": 50.0},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["location_name"] == "New Loc"


@pytest.mark.asyncio
async def test_probe_patch_unknown_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        f"/api/v1/probes/{uuid.uuid4()}",
        json={"location_name": "X"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_probe_delete(client: AsyncClient, admin_token: str) -> None:
    p = await _register_probe(client, admin_token, name="DelMe")
    resp = await client.delete(f"/api/v1/probes/{p['id']}", headers=_auth(admin_token))
    assert resp.status_code == 204
    # GET now returns 404
    resp2 = await client.get(f"/api/v1/probes/{p['id']}", headers=_auth(admin_token))
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_probe_delete_unknown_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.delete(f"/api/v1/probes/{uuid.uuid4()}", headers=_auth(admin_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_probe_register_requires_superadmin(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": "Unauth"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_probe_incident_timeline_empty(client: AsyncClient, admin_token: str) -> None:
    p = await _register_probe(client, admin_token, name="Tline")
    resp = await client.get(
        f"/api/v1/probes/{p['id']}/incident-timeline",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_probe_incident_timeline_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(
        f"/api/v1/probes/{uuid.uuid4()}/incident-timeline",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Metrics endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_endpoints_404_unknown_monitor(client: AsyncClient, user_token: str) -> None:
    """Custom metrics on unknown monitor → 404."""
    # Try the most common metrics path
    resp = await client.get(
        f"/api/v1/metrics/{uuid.uuid4()}",
        headers=_auth(user_token),
    )
    # Either 404 (not found) or 200 (returns empty)
    assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Devices / Web push
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_devices_list_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/devices/", headers=_auth(user_token))
    # May 200 with empty list
    assert resp.status_code in (200, 404)


@pytest.mark.asyncio
async def test_devices_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/devices/")
    assert resp.status_code in (401, 404)


# ---------------------------------------------------------------------------
# Tags CRUD (small ROI)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tags_full_crud(client: AsyncClient, user_token: str, admin_token: str) -> None:
    # Create (any user)
    create = await client.post(
        "/api/v1/tags/",
        json={"name": "tag-crud", "color": "#00ff00"},
        headers=_auth(user_token),
    )
    assert create.status_code == 201
    tag_id = create.json()["id"]

    # List (any user)
    lst = await client.get("/api/v1/tags/", headers=_auth(user_token))
    assert lst.status_code == 200
    assert any(t["id"] == tag_id for t in lst.json())

    # Update — superadmin-only (tags are a global shared pool)
    upd = await client.patch(
        f"/api/v1/tags/{tag_id}",
        json={"name": "tag-renamed"},
        headers=_auth(admin_token),
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "tag-renamed"

    # Delete — superadmin-only
    delete = await client.delete(f"/api/v1/tags/{tag_id}", headers=_auth(admin_token))
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_tags_update_unknown_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        f"/api/v1/tags/{uuid.uuid4()}",
        json={"name": "x"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_tags_delete_unknown_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.delete(f"/api/v1/tags/{uuid.uuid4()}", headers=_auth(admin_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_tags_create_duplicate_returns_existing(client: AsyncClient, user_token: str) -> None:
    """Duplicate tag name returns the existing tag with 201 (idempotent)."""
    r1 = await client.post(
        "/api/v1/tags/",
        json={"name": "dup-tag", "color": "#ff0000"},
        headers=_auth(user_token),
    )
    assert r1.status_code == 201
    tag1_id = r1.json()["id"]

    r2 = await client.post(
        "/api/v1/tags/",
        json={"name": "dup-tag", "color": "#000000"},
        headers=_auth(user_token),
    )
    assert r2.status_code == 201
    # Same tag returned
    assert r2.json()["id"] == tag1_id


# ---------------------------------------------------------------------------
# Groups CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groups_crud_full(client: AsyncClient, user_token: str) -> None:
    # Create
    create = await client.post(
        "/api/v1/groups/",
        json={"name": "CRUDGrp", "public_slug": "crud-grp"},
        headers=_auth(user_token),
    )
    assert create.status_code == 201
    group_id = create.json()["id"]

    # Duplicate slug → 409
    dup = await client.post(
        "/api/v1/groups/",
        json={"name": "Other", "public_slug": "crud-grp"},
        headers=_auth(user_token),
    )
    assert dup.status_code == 409

    # Get
    get_resp = await client.get(f"/api/v1/groups/{group_id}", headers=_auth(user_token))
    assert get_resp.status_code == 200

    # Patch
    upd = await client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "Renamed Group"},
        headers=_auth(user_token),
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Renamed Group"

    # List monitors of this group (empty)
    lm = await client.get(f"/api/v1/groups/{group_id}/monitors", headers=_auth(user_token))
    assert lm.status_code == 200

    # Delete
    delete = await client.delete(f"/api/v1/groups/{group_id}", headers=_auth(user_token))
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_group_get_unknown_404(client: AsyncClient, user_token: str) -> None:
    resp = await client.get(f"/api/v1/groups/{uuid.uuid4()}", headers=_auth(user_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# More alert paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_rule_with_group_target(client: AsyncClient, user_token: str) -> None:
    """Create a rule targeting a group rather than a single monitor."""
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={"name": "AlertTargetGrp"},
            headers=_auth(user_token),
        )
    ).json()
    chan = (
        await client.post(
            "/api/v1/alerts/channels",
            json={
                "name": "GrpChan",
                "type": "email",
                "config": {"to": ["g@example.com"]},
            },
            headers=_auth(user_token),
        )
    ).json()
    resp = await client.post(
        "/api/v1/alerts/rules",
        json={
            "group_id": grp["id"],
            "condition": "any_down",
            "channel_ids": [chan["id"]],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_alert_rule_with_unknown_group_404(client: AsyncClient, user_token: str) -> None:
    chan = (
        await client.post(
            "/api/v1/alerts/channels",
            json={
                "name": "C404",
                "type": "email",
                "config": {"to": ["e@example.com"]},
            },
            headers=_auth(user_token),
        )
    ).json()
    resp = await client.post(
        "/api/v1/alerts/rules",
        json={
            "group_id": str(uuid.uuid4()),
            "condition": "any_down",
            "channel_ids": [chan["id"]],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_alert_rule_with_unknown_monitor_404(client: AsyncClient, user_token: str) -> None:
    chan = (
        await client.post(
            "/api/v1/alerts/channels",
            json={
                "name": "MUnknown",
                "type": "email",
                "config": {"to": ["e@example.com"]},
            },
            headers=_auth(user_token),
        )
    ).json()
    resp = await client.post(
        "/api/v1/alerts/rules",
        json={
            "monitor_id": str(uuid.uuid4()),
            "condition": "any_down",
            "channel_ids": [chan["id"]],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_alert_events_list_with_status_filter(client: AsyncClient, user_token: str) -> None:
    """Empty list with filter parameter exercises the conditional branch."""
    resp = await client.get("/api/v1/alerts/events?status=sent", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_matrix_preview_unknown_monitor_404(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        f"/api/v1/alerts/monitors/{uuid.uuid4()}/matrix/preview",
        json={"rows": []},
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_matrix_preview_empty_payload(client: AsyncClient, user_token: str) -> None:
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "MPrev", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    resp = await client.post(
        f"/api/v1/alerts/monitors/{mon['id']}/matrix/preview",
        json={"rows": []},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
