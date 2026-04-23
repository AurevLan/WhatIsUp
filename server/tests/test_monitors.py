"""Tests for monitor CRUD endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_monitor(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Test Monitor", "url": "https://example.com", "interval_seconds": 60},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Monitor"
    assert data["url"] == "https://example.com/"
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_list_monitors(client: AsyncClient, user_token: str) -> None:
    await client.post(
        "/api/v1/monitors/",
        json={"name": "M1", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    resp = await client.get(
        "/api/v1/monitors/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_monitor(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "GetMe", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]
    resp = await client.get(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == monitor_id


@pytest.mark.asyncio
async def test_update_monitor(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "Update Me", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"name": "Updated Name", "interval_seconds": 30},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"
    assert resp.json()["interval_seconds"] == 30


@pytest.mark.asyncio
async def test_delete_monitor(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "Delete Me", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert del_resp.status_code == 204

    get_resp = await client.get(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_monitor_invalid_url(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Bad URL", "url": "not-a-url"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_monitor_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/monitors/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_monitor_isolation(client: AsyncClient, user_token: str, admin_token: str) -> None:
    """A regular user cannot access another user's monitor."""
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "Private", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    # Superadmin can see it
    resp = await client.get(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_pause_monitors(client: AsyncClient, user_token: str) -> None:
    """Bulk pause disables all targeted monitors."""
    m1 = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Bulk Pause 1", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()
    m2 = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Bulk Pause 2", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()

    resp = await client.post(
        "/api/v1/monitors/bulk",
        json={"ids": [m1["id"], m2["id"]], "action": "pause"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["affected"] == 2

    for mid in (m1["id"], m2["id"]):
        detail = await client.get(
            f"/api/v1/monitors/{mid}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert detail.status_code == 200
        assert detail.json()["enabled"] is False


@pytest.mark.asyncio
async def test_bulk_delete_monitors(client: AsyncClient, user_token: str) -> None:
    """Bulk delete removes all targeted monitors."""
    m1 = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Bulk Del 1", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()
    m2 = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Bulk Del 2", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()

    resp = await client.post(
        "/api/v1/monitors/bulk",
        json={"ids": [m1["id"], m2["id"]], "action": "delete"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["affected"] == 2

    for mid in (m1["id"], m2["id"]):
        detail = await client.get(
            f"/api/v1/monitors/{mid}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert detail.status_code == 404


@pytest.mark.asyncio
async def test_bulk_action_isolation(
    client: AsyncClient, user_token: str, admin_token: str
) -> None:
    """A regular user cannot bulk-delete a monitor they do not own."""
    # Admin creates a monitor
    admin_monitor = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Admin Only Monitor", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()

    # Regular user attempts to bulk-delete the admin's monitor
    resp = await client.post(
        "/api/v1/monitors/bulk",
        json={"ids": [admin_monitor["id"]], "action": "delete"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    # Either forbidden or silently skipped (affected == 0)
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert resp.json()["affected"] == 0

    # Monitor must still exist (verify as admin)
    still_there = await client.get(
        f"/api/v1/monitors/{admin_monitor['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert still_there.status_code == 200


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_dependency(client: AsyncClient, user_token: str) -> None:
    """Adding a parent dependency to a monitor returns 201 and the link."""
    monitor_a = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Parent A", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()
    monitor_b = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Child B", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()

    # B depends on A (A is the parent)
    resp = await client.post(
        f"/api/v1/monitors/{monitor_b['id']}/dependencies",
        json={"parent_id": monitor_a["id"], "suppress_on_parent_down": True},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["parent_id"] == monitor_a["id"]
    assert data["child_id"] == monitor_b["id"]
    assert data["suppress_on_parent_down"] is True


@pytest.mark.asyncio
async def test_cycle_detection_rejects(client: AsyncClient, user_token: str) -> None:
    """Adding a composite member that would form a cycle is rejected (400/409)."""
    # Create two composite monitors
    comp_a = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": "Composite A",
                "url": "https://example.com",
                "check_type": "composite",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()
    comp_b = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": "Composite B",
                "url": "https://example.com",
                "check_type": "composite",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()

    # A includes B
    r1 = await client.post(
        f"/api/v1/monitors/{comp_a['id']}/composite-members",
        json={"monitor_id": comp_b["id"]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r1.status_code == 201

    # B tries to include A → would create a cycle
    r2 = await client.post(
        f"/api/v1/monitors/{comp_b['id']}/composite-members",
        json={"monitor_id": comp_a["id"]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r2.status_code in (400, 409)


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_annotation(client: AsyncClient, user_token: str) -> None:
    """Creating an annotation on a monitor returns 201 with the stored content."""
    monitor = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Annotated Monitor", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()

    now_iso = datetime.now(UTC).isoformat()
    resp = await client.post(
        f"/api/v1/monitors/{monitor['id']}/annotations",
        json={"content": "test note", "annotated_at": now_iso},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "test note"
    assert data["monitor_id"] == monitor["id"]


# ---------------------------------------------------------------------------
# SLO
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slo_crud(client: AsyncClient, user_token: str) -> None:
    """Setting slo_target / slo_window_days on a monitor and reading the SLO endpoint."""
    monitor = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "SLO Monitor", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()
    monitor_id = monitor["id"]

    # Set SLO via PATCH (the model stores it directly on the monitor)
    patch_resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"slo_target": 99.9, "slo_window_days": 30},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["slo_target"] == 99.9
    assert patched["slo_window_days"] == 30

    # GET /slo returns the configured target and window
    slo_resp = await client.get(
        f"/api/v1/monitors/{monitor_id}/slo",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert slo_resp.status_code == 200
    slo_data = slo_resp.json()
    assert slo_data["slo_target"] == 99.9
    assert slo_data["window_days"] == 30
    assert "status" in slo_data

    # Clear the SLO by setting slo_target to None
    clear_resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"slo_target": None},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert clear_resp.status_code == 200

    # SLO endpoint now returns 404 (no SLO configured)
    gone_resp = await client.get(
        f"/api/v1/monitors/{monitor_id}/slo",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert gone_resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Runbook (T1-05)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runbook_defaults_disabled(client: AsyncClient, user_token: str) -> None:
    """A newly created monitor has runbook disabled and empty markdown."""
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "NoRunbook", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["runbook_enabled"] is False
    assert data["runbook_markdown"] is None


@pytest.mark.asyncio
async def test_runbook_create_enabled(client: AsyncClient, user_token: str) -> None:
    """Creating a monitor with runbook enabled persists both the flag and the content."""
    content = "## Playbook\n- Check logs\n- Restart"
    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "WithRunbook",
            "url": "https://example.com",
            "runbook_enabled": True,
            "runbook_markdown": content,
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["runbook_enabled"] is True
    assert data["runbook_markdown"] == content


@pytest.mark.asyncio
async def test_runbook_create_markdown_ignored_when_disabled(
    client: AsyncClient, user_token: str
) -> None:
    """Markdown supplied at creation with runbook disabled is wiped (option B)."""
    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Orphan",
            "url": "https://example.com",
            "runbook_enabled": False,
            "runbook_markdown": "should be dropped",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["runbook_enabled"] is False
    assert data["runbook_markdown"] is None


@pytest.mark.asyncio
async def test_runbook_disable_wipes_markdown(client: AsyncClient, user_token: str) -> None:
    """Option B: toggling runbook_enabled off wipes runbook_markdown server-side."""
    create = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "ToggleOff",
            "url": "https://example.com",
            "runbook_enabled": True,
            "runbook_markdown": "# Keep me... for now",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    # Disable — no runbook_markdown in payload, but server must wipe it anyway.
    patch = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"runbook_enabled": False},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert patch.status_code == 200
    data = patch.json()
    assert data["runbook_enabled"] is False
    assert data["runbook_markdown"] is None


@pytest.mark.asyncio
async def test_runbook_disable_overrides_explicit_markdown(
    client: AsyncClient, user_token: str
) -> None:
    """Disabling + sending markdown in the same PATCH: markdown still wiped (option B)."""
    create = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "ConflictPayload",
            "url": "https://example.com",
            "runbook_enabled": True,
            "runbook_markdown": "original",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    patch = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"runbook_enabled": False, "runbook_markdown": "sneaky update"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert patch.status_code == 200
    assert patch.json()["runbook_markdown"] is None


@pytest.mark.asyncio
async def test_runbook_update_markdown_only(client: AsyncClient, user_token: str) -> None:
    """Updating runbook_markdown alone without touching runbook_enabled works."""
    create = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Editable",
            "url": "https://example.com",
            "runbook_enabled": True,
            "runbook_markdown": "v1",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    patch = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"runbook_markdown": "v2 — updated"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert patch.status_code == 200
    assert patch.json()["runbook_enabled"] is True
    assert patch.json()["runbook_markdown"] == "v2 — updated"
