"""Tests for the Infrastructure-as-Code config export/import."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.user import User


# ── Export ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_empty_config(client: AsyncClient, user_token: str) -> None:
    """Export with no resources should return empty lists."""
    resp = await client.get(
        "/api/v1/config/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "1"
    assert data["groups"] == []
    assert data["monitors"] == []
    assert data["alert_channels"] == []
    assert data["alert_rules"] == []
    assert "exported_at" in data


@pytest.mark.asyncio
async def test_export_includes_created_resources(
    client: AsyncClient, admin_token: str
) -> None:
    """Resources created via API should appear in export (superadmin bypasses owner filter)."""
    # Create a group
    grp = await client.post(
        "/api/v1/groups/",
        json={"name": "Export Group", "public_slug": "export-grp"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert grp.status_code == 201

    # Create a monitor
    mon = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Export Monitor",
            "url": "https://example.com",
            "check_type": "http",
            "expected_status_codes": [200],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert mon.status_code == 201

    resp = await client.get(
        "/api/v1/config/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    data = resp.json()
    group_names = [g["name"] for g in data["groups"]]
    monitor_names = [m["name"] for m in data["monitors"]]
    assert "Export Group" in group_names
    assert "Export Monitor" in monitor_names


@pytest.mark.asyncio
async def test_export_redacts_secrets(client: AsyncClient, user_token: str) -> None:
    """Alert channel secrets should be redacted in export."""
    await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "Secret Channel",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/wh", "secret": "mysupersecret"},
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )

    resp = await client.get(
        "/api/v1/config/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = resp.json()
    channel = next(c for c in data["alert_channels"] if c["name"] == "Secret Channel")
    assert channel["config"]["secret"] == "***"
    assert channel["config"]["url"] == "https://hooks.example.com/wh"


# ── Import dry_run ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_dry_run_no_changes(client: AsyncClient, user_token: str) -> None:
    """dry_run should show plan but not create resources."""
    config = {
        "version": "1",
        "groups": [{"name": "DryRun Group"}],
        "monitors": [
            {
                "name": "DryRun Monitor",
                "url": "https://example.com",
                "check_type": "http",
            }
        ],
        "alert_channels": [],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?dry_run=true",
        json=config,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["dry_run"] is True
    assert len(plan["groups_created"]) == 1
    assert len(plan["monitors_created"]) == 1

    # Verify nothing was actually created
    export_resp = await client.get(
        "/api/v1/config/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    export = export_resp.json()
    assert not any(g["name"] == "DryRun Group" for g in export["groups"])
    assert not any(m["name"] == "DryRun Monitor" for m in export["monitors"])


# ── Import idempotent ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_then_reimport_is_idempotent(
    client: AsyncClient, user_token: str
) -> None:
    """Importing the same config twice should show 0 changes on second run."""
    config = {
        "version": "1",
        "groups": [{"name": "Idempotent Group"}],
        "monitors": [
            {
                "name": "Idempotent Monitor",
                "url": "https://example.com",
                "check_type": "http",
            }
        ],
        "alert_channels": [],
        "alert_rules": [],
    }

    # First import
    resp1 = await client.put(
        "/api/v1/config/?prune=false",
        json=config,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["total_changes"] > 0

    # Second import — same config, should be no-op
    resp2 = await client.put(
        "/api/v1/config/?prune=false&dry_run=true",
        json=config,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    plan = resp2.json()
    assert plan["groups_created"] == []
    assert plan["monitors_created"] == []
    # Updated lists may be empty or contain no meaningful changes
    assert plan["groups_deleted"] == []
    assert plan["monitors_deleted"] == []


# ── Import with prune ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_prune_deletes_extra_resources(
    client: AsyncClient, user_token: str
) -> None:
    """Import with prune=true should plan deletion of resources created in same import."""
    # First, create a resource via import (not API) so it's visible in same session
    setup_config = {
        "version": "1",
        "groups": [{"name": "Will Be Pruned"}],
        "monitors": [],
        "alert_channels": [],
        "alert_rules": [],
    }
    setup_resp = await client.put(
        "/api/v1/config/?prune=false",
        json=setup_config,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert setup_resp.status_code == 200
    assert len(setup_resp.json()["groups_created"]) == 1

    # Now import without that group, with prune
    prune_config = {
        "version": "1",
        "groups": [{"name": "Keeper Group"}],
        "monitors": [],
        "alert_channels": [],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=true&dry_run=true",
        json=prune_config,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    plan = resp.json()
    deleted_names = [g["name"] for g in plan["groups_deleted"]]
    assert "Will Be Pruned" in deleted_names


@pytest.mark.asyncio
async def test_import_no_prune_keeps_extra(
    client: AsyncClient, user_token: str
) -> None:
    """Import with prune=false should NOT delete resources not in config."""
    await client.post(
        "/api/v1/groups",
        json={"name": "Should Stay", "public_slug": "stay-put"},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    config = {
        "version": "1",
        "groups": [],
        "monitors": [],
        "alert_channels": [],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=false&dry_run=true",
        json=config,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    plan = resp.json()
    assert plan["groups_deleted"] == []


# ── Import creates monitors with group reference ─────────────────────────────


@pytest.mark.asyncio
async def test_import_monitor_with_group_reference(
    client: AsyncClient, user_token: str
) -> None:
    """Monitors should be linked to groups by name."""
    config = {
        "version": "1",
        "groups": [{"name": "Ref Group"}],
        "monitors": [
            {
                "name": "Ref Monitor",
                "url": "https://example.com",
                "check_type": "http",
                "group": "Ref Group",
            }
        ],
        "alert_channels": [],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=false",
        json=config,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200

    # Verify via export
    export_resp = await client.get(
        "/api/v1/config/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitors = export_resp.json()["monitors"]
    ref_mon = next((m for m in monitors if m["name"] == "Ref Monitor"), None)
    assert ref_mon is not None
    assert ref_mon.get("group") == "Ref Group"
