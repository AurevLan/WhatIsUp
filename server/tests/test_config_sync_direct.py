"""Direct unit tests for whatisup.services.config_sync — bypasses the HTTP layer.

Calls export_config / import_config with the service_db fixture so coverage
properly tracks the function bodies (the HTTP-driven tests appear to lose
trace data on httpx ASGI calls).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.user import User
from whatisup.services.config_sync import export_config, import_config


@pytest.mark.asyncio
async def test_export_empty(service_db: AsyncSession, test_user: User) -> None:
    out = await export_config(test_user, service_db)
    assert out["version"] == "1"
    assert out["groups"] == []
    assert out["monitors"] == []
    assert out["alert_channels"] == []
    assert out["alert_rules"] == []


@pytest.mark.asyncio
async def test_export_with_data(service_db: AsyncSession, test_user: User) -> None:
    """Export a config with monitors+groups+channels+rules; verify each block."""
    from whatisup.core.security import encrypt_channel_config
    from whatisup.models.alert import (
        AlertChannel,
        AlertChannelType,
        AlertCondition,
        AlertRule,
    )
    from whatisup.models.monitor import Monitor, MonitorGroup

    grp = MonitorGroup(
        name="ExpDirGrp",
        owner_id=test_user.id,
        description="d",
        public_slug="exp-dir",
    )
    service_db.add(grp)
    await service_db.flush()

    mon = Monitor(
        name="ExpDirMon",
        url="https://example.com",
        owner_id=test_user.id,
        group_id=grp.id,
        check_type="http",
        interval_seconds=120,
    )
    service_db.add(mon)

    chan = AlertChannel(
        name="ExpDirChan",
        owner_id=test_user.id,
        type=AlertChannelType.webhook,
        config=encrypt_channel_config({"url": "https://hooks.example.com/x", "secret": "mysecret"}),
    )
    service_db.add(chan)
    await service_db.flush()

    rule = AlertRule(
        owner_id=test_user.id,
        monitor_id=mon.id,
        condition=AlertCondition.any_down,
        min_duration_seconds=60,
        renotify_after_minutes=15,
        threshold_value=2500.0,
        digest_minutes=5,
        channels=[chan],
        enabled=False,
    )
    service_db.add(rule)
    await service_db.flush()

    out = await export_config(test_user, service_db)
    assert len(out["groups"]) == 1
    assert out["groups"][0]["name"] == "ExpDirGrp"
    assert len(out["monitors"]) == 1
    assert out["monitors"][0]["name"] == "ExpDirMon"
    assert out["monitors"][0]["group"] == "ExpDirGrp"

    # Channels: secret redacted
    assert len(out["alert_channels"]) == 1
    assert out["alert_channels"][0]["config"]["secret"] == "***"

    # Rule has monitor reference + extra fields
    assert len(out["alert_rules"]) == 1
    rule_out = out["alert_rules"][0]
    assert rule_out["monitor"] == "ExpDirMon"
    assert rule_out["condition"] == "any_down"
    assert rule_out["threshold_value"] == 2500.0
    assert rule_out["min_duration_seconds"] == 60
    assert rule_out["renotify_after_minutes"] == 15
    assert rule_out["digest_minutes"] == 5
    assert rule_out["enabled"] is False


@pytest.mark.asyncio
async def test_import_creates_full_stack(service_db: AsyncSession, test_user: User) -> None:
    config = {
        "version": "1",
        "groups": [
            {
                "name": "ImpDirGrp",
                "description": "imp desc",
                "public_slug": "imp-dir",
            }
        ],
        "monitors": [
            {
                "name": "ImpDirMon",
                "url": "https://example.com",
                "check_type": "http",
                "group": "ImpDirGrp",
                "interval_seconds": 90,
            }
        ],
        "alert_channels": [
            {
                "name": "ImpDirChan",
                "type": "email",
                "config": {"to": ["a@example.com"]},
            }
        ],
        "alert_rules": [
            {
                "condition": "any_down",
                "monitor": "ImpDirMon",
                "channels": ["ImpDirChan"],
                "min_duration_seconds": 30,
            }
        ],
    }
    plan = await import_config(test_user, service_db, config, dry_run=False, prune=False)
    assert plan["total_changes"] > 0
    assert plan["dry_run"] is False
    assert len(plan["groups_created"]) == 1
    assert len(plan["monitors_created"]) == 1
    assert len(plan["channels_created"]) == 1
    assert len(plan["rules_created"]) == 1


@pytest.mark.asyncio
async def test_import_dry_run(service_db: AsyncSession, test_user: User) -> None:
    config = {
        "version": "1",
        "groups": [{"name": "DryDirGrp"}],
        "monitors": [],
        "alert_channels": [],
        "alert_rules": [],
    }
    plan = await import_config(test_user, service_db, config, dry_run=True, prune=False)
    assert plan["dry_run"] is True
    assert len(plan["groups_created"]) == 1


@pytest.mark.asyncio
async def test_import_idempotent_update(service_db: AsyncSession, test_user: User) -> None:
    """Run import twice — second time should detect no changes."""
    config = {
        "version": "1",
        "groups": [{"name": "IdemDirGrp", "description": "v1"}],
        "monitors": [
            {
                "name": "IdemDirMon",
                "url": "https://example.com",
                "check_type": "http",
            }
        ],
        "alert_channels": [],
        "alert_rules": [],
    }
    await import_config(test_user, service_db, config, dry_run=False, prune=False)
    plan2 = await import_config(test_user, service_db, config, dry_run=True, prune=False)
    assert plan2["groups_created"] == []
    assert plan2["monitors_created"] == []


@pytest.mark.asyncio
async def test_import_update_monitor_field_change(
    service_db: AsyncSession, test_user: User
) -> None:
    """Existing monitor with different field → reported as updated."""
    from whatisup.models.monitor import Monitor

    mon = Monitor(
        name="UpdMon",
        url="https://example.com",
        owner_id=test_user.id,
        interval_seconds=60,
        check_type="http",
    )
    service_db.add(mon)
    await service_db.flush()

    config = {
        "version": "1",
        "groups": [],
        "monitors": [
            {
                "name": "UpdMon",
                "url": "https://example.com",
                "check_type": "http",
                "interval_seconds": 300,
            }
        ],
        "alert_channels": [],
        "alert_rules": [],
    }
    plan = await import_config(test_user, service_db, config, dry_run=False, prune=False)
    upd = next((m for m in plan["monitors_updated"] if m["name"] == "UpdMon"), None)
    assert upd is not None
    assert "interval_seconds" in upd["changed_fields"]


@pytest.mark.asyncio
async def test_import_prune_deletes(service_db: AsyncSession, test_user: User) -> None:
    """Prune=True removes resources not in config."""
    from whatisup.models.monitor import MonitorGroup

    grp = MonitorGroup(name="ToPruneDir", owner_id=test_user.id)
    service_db.add(grp)
    await service_db.flush()

    config = {
        "version": "1",
        "groups": [],
        "monitors": [],
        "alert_channels": [],
        "alert_rules": [],
    }
    plan = await import_config(test_user, service_db, config, dry_run=True, prune=True)
    assert any(g["name"] == "ToPruneDir" for g in plan["groups_deleted"])


@pytest.mark.asyncio
async def test_import_group_update_field_change(service_db: AsyncSession, test_user: User) -> None:
    from whatisup.models.monitor import MonitorGroup

    grp = MonitorGroup(
        name="GrpFieldChange",
        owner_id=test_user.id,
        description="old",
    )
    service_db.add(grp)
    await service_db.flush()

    config = {
        "version": "1",
        "groups": [{"name": "GrpFieldChange", "description": "new"}],
        "monitors": [],
        "alert_channels": [],
        "alert_rules": [],
    }
    plan = await import_config(test_user, service_db, config, dry_run=False, prune=False)
    upd = next((g for g in plan["groups_updated"] if g["name"] == "GrpFieldChange"), None)
    assert upd is not None
    assert "description" in upd["changed_fields"]


@pytest.mark.asyncio
async def test_import_channel_type_change(service_db: AsyncSession, test_user: User) -> None:
    from whatisup.core.security import encrypt_channel_config
    from whatisup.models.alert import AlertChannel, AlertChannelType

    chan = AlertChannel(
        name="TypeChange",
        owner_id=test_user.id,
        type=AlertChannelType.email,
        config=encrypt_channel_config({"to": ["x@example.com"]}),
    )
    service_db.add(chan)
    await service_db.flush()

    config = {
        "version": "1",
        "groups": [],
        "monitors": [],
        "alert_channels": [
            {
                "name": "TypeChange",
                "type": "webhook",
                "config": {"url": "https://example.com/new"},
            }
        ],
        "alert_rules": [],
    }
    plan = await import_config(test_user, service_db, config, dry_run=False, prune=False)
    upd = next((c for c in plan["channels_updated"] if c["name"] == "TypeChange"), None)
    assert upd is not None
    assert "type" in upd["changed_fields"]


@pytest.mark.asyncio
async def test_import_redacted_secret_skipped(service_db: AsyncSession, test_user: User) -> None:
    """A fully redacted config block doesn't update the channel."""
    from whatisup.core.security import encrypt_channel_config
    from whatisup.models.alert import AlertChannel, AlertChannelType

    chan = AlertChannel(
        name="Redact",
        owner_id=test_user.id,
        type=AlertChannelType.webhook,
        config=encrypt_channel_config({"url": "https://example.com/x", "secret": "abc"}),
    )
    service_db.add(chan)
    await service_db.flush()

    config = {
        "version": "1",
        "groups": [],
        "monitors": [],
        "alert_channels": [
            {
                "name": "Redact",
                "type": "webhook",
                "config": {"url": "***", "secret": "***"},
            }
        ],
        "alert_rules": [],
    }
    plan = await import_config(test_user, service_db, config, dry_run=True, prune=False)
    for chg in plan["channels_updated"]:
        if chg["name"] == "Redact":
            assert "config" not in chg["changed_fields"]
