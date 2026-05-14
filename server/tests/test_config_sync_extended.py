"""Extended config_sync tests — exercise import paths for alert channels/rules,
update flows, and the superadmin (no owner_id filter) branches.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_export_with_alert_channels_and_rules(client: AsyncClient, user_token: str) -> None:
    """Create channels + rules then export — exercises the channels/rules export branches."""
    # Create group + monitor
    await client.post("/api/v1/groups/", json={"name": "ExpGrp"}, headers=_auth(user_token))
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "ExpMon", "url": "https://example.com"},
        headers=_auth(user_token),
    )

    # Create email channel
    chan = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "ExpEmail",
            "type": "email",
            "config": {"to": ["a@example.com"]},
        },
        headers=_auth(user_token),
    )
    assert chan.status_code == 201
    chan_id = chan.json()["id"]

    # Create webhook channel
    wh = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "ExpWebhook",
            "type": "webhook",
            "config": {
                "url": "https://example.com/hook",
                "secret": "supersecret123",
            },
        },
        headers=_auth(user_token),
    )
    assert wh.status_code == 201

    # Create rule
    await client.post(
        "/api/v1/alerts/rules",
        json={
            "monitor_id": mon.json()["id"],
            "condition": "any_down",
            "channel_ids": [chan_id],
            "min_duration_seconds": 60,
            "renotify_after_minutes": 30,
            "threshold_value": 2000.0,
            "digest_minutes": 5,
        },
        headers=_auth(user_token),
    )

    # Export — should include channels (with redacted secret) and rules
    exp = await client.get("/api/v1/config/", headers=_auth(user_token))
    assert exp.status_code == 200
    data = exp.json()
    assert any(c["name"] == "ExpEmail" for c in data["alert_channels"])
    wh_ch = next(c for c in data["alert_channels"] if c["name"] == "ExpWebhook")
    # Secret should be redacted
    assert wh_ch["config"]["secret"] == "***"
    assert len(data["alert_rules"]) == 1
    assert data["alert_rules"][0]["condition"] == "any_down"
    # rule with monitor reference
    assert data["alert_rules"][0]["monitor"] == "ExpMon"
    # discriminate threshold etc.
    assert data["alert_rules"][0]["threshold_value"] == 2000.0


@pytest.mark.asyncio
async def test_import_with_alert_channels(client: AsyncClient, user_token: str) -> None:
    """Import path: create alert channels via config-sync."""
    config = {
        "version": "1",
        "groups": [],
        "monitors": [],
        "alert_channels": [
            {
                "name": "ImportedChan",
                "type": "email",
                "config": {"to": ["imported@example.com"]},
            },
            {
                "name": "ImportedWebhook",
                "type": "webhook",
                "config": {"url": "https://example.com/imp"},
            },
        ],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=false",
        json=config,
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    plan = resp.json()
    assert len(plan["channels_created"]) == 2


@pytest.mark.asyncio
async def test_import_with_alert_rules_full(client: AsyncClient, user_token: str) -> None:
    """Import path: create a monitor + channel + rule in one shot."""
    config = {
        "version": "1",
        "groups": [{"name": "FullGrp"}],
        "monitors": [
            {
                "name": "FullMon",
                "url": "https://example.com",
                "check_type": "http",
                "group": "FullGrp",
                "interval_seconds": 120,
            }
        ],
        "alert_channels": [
            {
                "name": "FullChan",
                "type": "email",
                "config": {"to": ["full@example.com"]},
            }
        ],
        "alert_rules": [
            {
                "condition": "any_down",
                "monitor": "FullMon",
                "channels": ["FullChan"],
                "min_duration_seconds": 60,
                "threshold_value": 1500.0,
                "renotify_after_minutes": 30,
                "digest_minutes": 10,
                "enabled": True,
            }
        ],
    }
    resp = await client.put(
        "/api/v1/config/?prune=false",
        json=config,
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    plan = resp.json()
    assert len(plan["groups_created"]) == 1
    assert len(plan["monitors_created"]) == 1
    assert len(plan["channels_created"]) == 1
    assert len(plan["rules_created"]) == 1


@pytest.mark.asyncio
async def test_import_updates_existing_channel_type(client: AsyncClient, user_token: str) -> None:
    """Updating a channel type via re-import is detected as a change."""
    # First create via API
    await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "ChangeMe",
            "type": "email",
            "config": {"to": ["x@example.com"]},
        },
        headers=_auth(user_token),
    )
    # Now import as webhook
    config = {
        "version": "1",
        "groups": [],
        "monitors": [],
        "alert_channels": [
            {
                "name": "ChangeMe",
                "type": "webhook",
                "config": {"url": "https://example.com/new"},
            }
        ],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=false&dry_run=true",
        json=config,
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    plan = resp.json()
    # Channel exists, type changed, so it's "updated"
    assert any(c["name"] == "ChangeMe" for c in plan["channels_updated"])


@pytest.mark.asyncio
async def test_import_prune_deletes_channels(client: AsyncClient, user_token: str) -> None:
    """Prune mode deletes channels not in the imported config."""
    # Create a channel via API
    await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "WillPrune",
            "type": "email",
            "config": {"to": ["x@example.com"]},
        },
        headers=_auth(user_token),
    )
    # Import config without this channel
    config = {
        "version": "1",
        "groups": [],
        "monitors": [],
        "alert_channels": [
            {
                "name": "Keeper",
                "type": "email",
                "config": {"to": ["k@example.com"]},
            }
        ],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=true&dry_run=true",
        json=config,
        headers=_auth(user_token),
    )
    plan = resp.json()
    assert any(c["name"] == "WillPrune" for c in plan["channels_deleted"])


@pytest.mark.asyncio
async def test_import_updates_existing_group_field(client: AsyncClient, user_token: str) -> None:
    """Importing a group with a description change yields a 'changed_fields' entry."""
    await client.post(
        "/api/v1/groups/",
        json={"name": "FieldUpdGrp", "description": "old desc"},
        headers=_auth(user_token),
    )
    config = {
        "version": "1",
        "groups": [{"name": "FieldUpdGrp", "description": "new desc"}],
        "monitors": [],
        "alert_channels": [],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=false",
        json=config,
        headers=_auth(user_token),
    )
    plan = resp.json()
    upd = next((g for g in plan["groups_updated"] if g["name"] == "FieldUpdGrp"), None)
    assert upd is not None
    assert "description" in upd["changed_fields"]


@pytest.mark.asyncio
async def test_import_updates_existing_monitor(client: AsyncClient, user_token: str) -> None:
    """Importing a monitor with field changes reports them under monitors_updated."""
    await client.post(
        "/api/v1/monitors/",
        json={"name": "FieldUpdMon", "url": "https://example.com", "interval_seconds": 60},
        headers=_auth(user_token),
    )
    config = {
        "version": "1",
        "groups": [],
        "monitors": [
            {
                "name": "FieldUpdMon",
                "url": "https://example.com",
                "check_type": "http",
                "interval_seconds": 300,
            }
        ],
        "alert_channels": [],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=false",
        json=config,
        headers=_auth(user_token),
    )
    plan = resp.json()
    upd = next((m for m in plan["monitors_updated"] if m["name"] == "FieldUpdMon"), None)
    assert upd is not None
    assert "interval_seconds" in upd["changed_fields"]


@pytest.mark.asyncio
async def test_import_with_fully_redacted_secret_skips_config_update(
    client: AsyncClient, user_token: str
) -> None:
    """When the imported config is fully redacted (all values `***`), config is left untouched."""
    # Create webhook with secret
    await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "SkippedRedact",
            "type": "webhook",
            "config": {
                "url": "https://example.com/hook",
                "secret": "real-secret-do-not-clobber",
            },
        },
        headers=_auth(user_token),
    )

    # Construct a fully-redacted config (no real URL — just `***`)
    config = {
        "version": "1",
        "groups": [],
        "monitors": [],
        "alert_channels": [
            {
                "name": "SkippedRedact",
                "type": "webhook",
                "config": {"url": "***", "secret": "***"},
            }
        ],
        "alert_rules": [],
    }
    resp = await client.put(
        "/api/v1/config/?prune=false&dry_run=true",
        json=config,
        headers=_auth(user_token),
    )
    plan = resp.json()
    # The fully-redacted config means _is_redacted=True so it's skipped
    for chg in plan["channels_updated"]:
        if chg["name"] == "SkippedRedact":
            assert "config" not in chg["changed_fields"]
