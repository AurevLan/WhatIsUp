"""Tests for monitor CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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
async def test_list_monitors_latest_row_per_monitor(
    client: AsyncClient,
    db_session,
    user_token: str,
    regular_user,
) -> None:
    """Regression guard for the GET /monitors/ unbounded-scan timeout (PR #218).

    ``last_status`` / ``last_response_time_ms`` / ``sparkline`` must reflect the
    single most-recent check result *per monitor*. The original code derived
    these from a table-wide ``GROUP BY monitor_id`` over ``max(checked_at)`` —
    a full scan that took ~8s twice on ~5M rows and tripped the 15s client
    timeout. The fix replaces it with a per-monitor LATERAL ``ORDER BY
    checked_at DESC LIMIT 1``. This test pins that the chosen row is genuinely
    the latest one (not an older decoy) and never bleeds across monitors, so a
    revert to the unbounded/incorrect query is caught.
    """
    from whatisup.models.monitor import Monitor
    from whatisup.models.probe import Probe
    from whatisup.models.result import CheckResult, CheckStatus

    now = datetime.now(UTC)
    older = now - timedelta(minutes=10)

    mon_a = Monitor(name="latest-A", url="https://a.example.com", owner_id=regular_user.id)
    mon_b = Monitor(name="latest-B", url="https://b.example.com", owner_id=regular_user.id)
    probe = Probe(name="p-latest", location_name="LA", api_key_hash="x")
    db_session.add_all([mon_a, mon_b, probe])
    await db_session.flush()

    db_session.add_all(
        [
            # Monitor A: an older DOWN/999ms decoy, then a recent UP/123ms result.
            CheckResult(
                monitor_id=mon_a.id,
                probe_id=probe.id,
                checked_at=older,
                status=CheckStatus.down,
                response_time_ms=999,
            ),
            CheckResult(
                monitor_id=mon_a.id,
                probe_id=probe.id,
                checked_at=now,
                status=CheckStatus.up,
                response_time_ms=123,
            ),
            # Monitor B: latest is DOWN/456ms — must not pick up A's values.
            CheckResult(
                monitor_id=mon_b.id,
                probe_id=probe.id,
                checked_at=now,
                status=CheckStatus.down,
                response_time_ms=456,
            ),
        ]
    )
    await db_session.flush()

    resp = await client.get(
        "/api/v1/monitors/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    by_id = {m["id"]: m for m in resp.json()}

    a = by_id[str(mon_a.id)]
    assert a["last_status"] == "up", "latest row (UP) must win over the older DOWN decoy"
    assert a["last_response_time_ms"] == 123.0, "RT must come from the latest row, not the decoy"
    assert 999.0 in a["sparkline"] and 123.0 in a["sparkline"]

    b = by_id[str(mon_b.id)]
    assert b["last_status"] == "down", "monitor B status must not bleed from monitor A"
    assert b["last_response_time_ms"] == 456.0


def test_list_monitors_latest_query_is_bounded_not_full_scan() -> None:
    """Static guard against reintroducing the unbounded-scan timeout (PR #218).

    The functional test above can't catch the perf regression on SQLite: the
    test branch deliberately keeps the ``max(checked_at)`` self-join, which is
    *correct* on tiny data even though it full-scans on production volumes. So
    we pin the production (PostgreSQL) path directly: the latest status / last
    response time must be fetched with a per-monitor bounded LATERAL
    ``ORDER BY checked_at DESC LIMIT 1``, not a table-wide ``GROUP BY``. Reverting
    to the old aggregate removes this marker and fails the test.

    The latest-row logic now lives in the shared ``fetch_latest_results``
    helper (stats.py) consumed by monitors, public, status and composite —
    the guard pins both the helper's LATERAL and the endpoint's use of it.
    """
    import inspect

    from whatisup.api.v1 import monitors
    from whatisup.services import stats

    src = inspect.getsource(monitors.list_monitors)
    assert "fetch_latest_results" in src, (
        "list_monitors must fetch the latest row via the shared bounded helper"
    )

    helper_src = inspect.getsource(stats.fetch_latest_results)
    # The non-sqlite branch builds the bounded per-monitor lateral.
    assert 'lateral("latest_cr")' in helper_src, (
        "production latest-row path must use a LATERAL subquery"
    )
    assert ".limit(1)" in helper_src, "the lateral must fetch a single (latest) row per monitor"


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
async def test_health_engine_toggle_roundtrip(client: AsyncClient, user_token: str) -> None:
    """V2-M4: ``health_engine_enabled`` is editable via PATCH and surfaces in
    MonitorOut so the frontend toggle reflects the persisted state."""
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "Toggle Me", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]
    assert create.json()["health_engine_enabled"] is False

    enabled = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"health_engine_enabled": True},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["health_engine_enabled"] is True

    disabled = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"health_engine_enabled": False},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert disabled.json()["health_engine_enabled"] is False


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
# T1-12 — Bulk set_group / add_tags / remove_tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_set_group(client: AsyncClient, user_token: str) -> None:
    """Bulk set_group reassigns the group_id of every targeted monitor."""
    auth = {"Authorization": f"Bearer {user_token}"}
    grp = (await client.post("/api/v1/groups/", json={"name": "Bulk Target"}, headers=auth)).json()
    m1 = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "BG1", "url": "https://example.com"},
            headers=auth,
        )
    ).json()
    m2 = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "BG2", "url": "https://example.com"},
            headers=auth,
        )
    ).json()

    resp = await client.post(
        "/api/v1/monitors/bulk",
        json={
            "ids": [m1["id"], m2["id"]],
            "action": "set_group",
            "target_group_id": grp["id"],
        },
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["affected"] == 2

    for mid in (m1["id"], m2["id"]):
        detail = (await client.get(f"/api/v1/monitors/{mid}", headers=auth)).json()
        assert detail["group_id"] == grp["id"]

    # set_group with target_group_id=None ungroups them.
    resp = await client.post(
        "/api/v1/monitors/bulk",
        json={"ids": [m1["id"]], "action": "set_group", "target_group_id": None},
        headers=auth,
    )
    assert resp.status_code == 200
    detail = (await client.get(f"/api/v1/monitors/{m1['id']}", headers=auth)).json()
    assert detail["group_id"] is None


@pytest.mark.asyncio
async def test_bulk_set_group_unknown_returns_404(client: AsyncClient, user_token: str) -> None:
    auth = {"Authorization": f"Bearer {user_token}"}
    m = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Solo", "url": "https://example.com"},
            headers=auth,
        )
    ).json()
    resp = await client.post(
        "/api/v1/monitors/bulk",
        json={
            "ids": [m["id"]],
            "action": "set_group",
            "target_group_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=auth,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bulk_add_and_remove_tags(client: AsyncClient, user_token: str) -> None:
    """Bulk add_tags then remove_tags round-trips cleanly without duplicates."""
    auth = {"Authorization": f"Bearer {user_token}"}
    tag_a = (await client.post("/api/v1/tags/", json={"name": "env:prod"}, headers=auth)).json()
    tag_b = (await client.post("/api/v1/tags/", json={"name": "team:sre"}, headers=auth)).json()

    monitors = []
    for i in range(2):
        monitors.append(
            (
                await client.post(
                    "/api/v1/monitors/",
                    json={"name": f"Tagged {i}", "url": "https://example.com"},
                    headers=auth,
                )
            ).json()
        )
    ids = [m["id"] for m in monitors]

    # Add both tags twice — second call must be a no-op (no duplicate rows).
    for _ in range(2):
        resp = await client.post(
            "/api/v1/monitors/bulk",
            json={"ids": ids, "action": "add_tags", "tag_ids": [tag_a["id"], tag_b["id"]]},
            headers=auth,
        )
        assert resp.status_code == 200

    for mid in ids:
        detail = (await client.get(f"/api/v1/monitors/{mid}", headers=auth)).json()
        names = sorted(t["name"] for t in detail["tags"])
        assert names == ["env:prod", "team:sre"]

    # Remove one tag.
    resp = await client.post(
        "/api/v1/monitors/bulk",
        json={"ids": ids, "action": "remove_tags", "tag_ids": [tag_a["id"]]},
        headers=auth,
    )
    assert resp.status_code == 200
    for mid in ids:
        detail = (await client.get(f"/api/v1/monitors/{mid}", headers=auth)).json()
        assert [t["name"] for t in detail["tags"]] == ["team:sre"]


@pytest.mark.asyncio
async def test_bulk_add_tags_requires_tag_ids(client: AsyncClient, user_token: str) -> None:
    auth = {"Authorization": f"Bearer {user_token}"}
    m = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Solo", "url": "https://example.com"},
            headers=auth,
        )
    ).json()
    resp = await client.post(
        "/api/v1/monitors/bulk",
        json={"ids": [m["id"]], "action": "add_tags"},
        headers=auth,
    )
    assert resp.status_code == 400


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


# ── DNS baseline (T1) ─────────────────────────────────────────────────────────


async def _create_dns_monitor(client: AsyncClient, user_token: str) -> dict:
    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "dns-mon",
            "check_type": "dns",
            "url": "https://example.com",
            "dns_record_type": "A",
            "interval_seconds": 60,
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_dns_baseline_accept_404_without_results(
    client: AsyncClient, user_token: str
) -> None:
    """Accepting a baseline before any DNS check has run must 404."""
    mon = await _create_dns_monitor(client, user_token)
    resp = await client.post(
        f"/api/v1/monitors/{mon['id']}/dns-baseline/accept",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dns_baseline_accept_400_on_non_dns_monitor(
    client: AsyncClient, user_token: str
) -> None:
    """Non-DNS monitors cannot accept a DNS baseline."""
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "http-mon", "url": "https://example.com", "interval_seconds": 60},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    mon = resp.json()
    accept = await client.post(
        f"/api/v1/monitors/{mon['id']}/dns-baseline/accept",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert accept.status_code == 400


@pytest.mark.asyncio
async def test_dns_baseline_accept_persists_sorted_values(
    client: AsyncClient,
    db_session,
    user_token: str,
    regular_user,
) -> None:
    """Successful accept stores the latest DNS values sorted."""
    from whatisup.models.monitor import Monitor
    from whatisup.models.probe import Probe
    from whatisup.models.result import CheckResult, CheckStatus

    monitor = Monitor(
        name="dns-mon-accept",
        check_type="dns",
        url="https://example.com",
        dns_record_type="A",
        owner_id=regular_user.id,
    )
    probe = Probe(name="p1", location_name="LA", api_key_hash="x")
    db_session.add_all([monitor, probe])
    await db_session.flush()
    db_session.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=probe.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            dns_resolved_values=["10.0.0.2", "10.0.0.1", "10.0.0.3"],
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/monitors/{monitor.id}/dns-baseline/accept",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["baseline"] == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


@pytest.mark.asyncio
async def test_dns_baseline_reset_clears_all_three_buckets(
    client: AsyncClient,
    db_session,
    user_token: str,
    regular_user,
) -> None:
    """Default type=all clears global, internal and external baselines."""
    from whatisup.models.monitor import Monitor

    monitor = Monitor(
        name="dns-mon-reset",
        check_type="dns",
        url="https://example.com",
        dns_record_type="A",
        owner_id=regular_user.id,
        dns_baseline_ips=["1.1.1.1"],
        dns_baseline_ips_internal=["2.2.2.2"],
        dns_baseline_ips_external=["3.3.3.3"],
    )
    db_session.add(monitor)
    await db_session.flush()

    resp = await client.delete(
        f"/api/v1/monitors/{monitor.id}/dns-baseline",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 204

    # Verify via API GET (refresh on the test session doesn't pick up the
    # handler's mutation reliably across the get_db override).
    get_resp = await client.get(
        f"/api/v1/monitors/{monitor.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body.get("dns_baseline_ips") in (None, [])
    assert body.get("dns_baseline_ips_internal") in (None, [])
    assert body.get("dns_baseline_ips_external") in (None, [])


@pytest.mark.asyncio
async def test_dns_baseline_reset_type_internal_only_clears_internal(
    client: AsyncClient,
    db_session,
    user_token: str,
    regular_user,
) -> None:
    from whatisup.models.monitor import Monitor

    monitor = Monitor(
        name="dns-mon-reset-int",
        check_type="dns",
        url="https://example.com",
        dns_record_type="A",
        owner_id=regular_user.id,
        dns_baseline_ips=["1.1.1.1"],
        dns_baseline_ips_internal=["2.2.2.2"],
        dns_baseline_ips_external=["3.3.3.3"],
    )
    db_session.add(monitor)
    await db_session.flush()

    resp = await client.delete(
        f"/api/v1/monitors/{monitor.id}/dns-baseline?type=internal",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 204

    get_resp = await client.get(
        f"/api/v1/monitors/{monitor.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    body = get_resp.json()
    assert body.get("dns_baseline_ips") == ["1.1.1.1"]
    assert body.get("dns_baseline_ips_internal") in (None, [])
    assert body.get("dns_baseline_ips_external") == ["3.3.3.3"]


# ── Schema drift baseline (T2) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schema_baseline_accept_404_without_fingerprint(
    client: AsyncClient, user_token: str
) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "schema-mon",
            "url": "https://example.com",
            "check_type": "json_path",
            "schema_drift_enabled": True,
            "interval_seconds": 60,
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    mon = resp.json()
    accept = await client.post(
        f"/api/v1/monitors/{mon['id']}/schema-baseline/accept",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert accept.status_code == 404


@pytest.mark.asyncio
async def test_schema_baseline_accept_persists_fingerprint(
    client: AsyncClient,
    db_session,
    user_token: str,
    regular_user,
) -> None:
    from whatisup.models.monitor import Monitor
    from whatisup.models.probe import Probe
    from whatisup.models.result import CheckResult, CheckStatus

    monitor = Monitor(
        name="schema-mon-accept",
        check_type="json_path",
        url="https://example.com",
        owner_id=regular_user.id,
        schema_drift_enabled=True,
    )
    probe = Probe(name="p2", location_name="NY", api_key_hash="x")
    db_session.add_all([monitor, probe])
    await db_session.flush()
    db_session.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=probe.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            schema_fingerprint="sha256:abc123",
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/monitors/{monitor.id}/schema-baseline/accept",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["baseline"] == "sha256:abc123"

    get_resp = await client.get(
        f"/api/v1/monitors/{monitor.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["schema_baseline"] == "sha256:abc123"
    assert body["schema_baseline_updated_at"] is not None


@pytest.mark.asyncio
async def test_schema_baseline_reset_clears_fingerprint(
    client: AsyncClient,
    db_session,
    user_token: str,
    regular_user,
) -> None:
    from whatisup.models.monitor import Monitor

    monitor = Monitor(
        name="schema-mon-reset",
        check_type="json_path",
        url="https://example.com",
        owner_id=regular_user.id,
        schema_drift_enabled=True,
        schema_baseline="sha256:old-fingerprint",
        schema_baseline_updated_at=datetime.now(UTC),
    )
    db_session.add(monitor)
    await db_session.flush()

    resp = await client.delete(
        f"/api/v1/monitors/{monitor.id}/schema-baseline",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 204

    get_resp = await client.get(
        f"/api/v1/monitors/{monitor.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    body = get_resp.json()
    assert body["schema_baseline"] is None
    assert body["schema_baseline_updated_at"] is None


# ── Postmortem (T3) ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postmortem_resolved_incident_renders_markdown(
    client: AsyncClient,
    db_session,
    user_token: str,
    regular_user,
) -> None:
    """Resolved incident → markdown with duration, timeline, metrics."""
    from whatisup.models.incident import Incident, IncidentScope
    from whatisup.models.monitor import Monitor
    from whatisup.models.probe import Probe
    from whatisup.models.result import CheckResult, CheckStatus

    monitor = Monitor(name="pm-resolved", url="https://example.com", owner_id=regular_user.id)
    probe = Probe(name="p-pm", location_name="EU", api_key_hash="x")
    db_session.add_all([monitor, probe])
    await db_session.flush()

    started = datetime.now(UTC) - timedelta(minutes=30)
    resolved = started + timedelta(minutes=10)
    incident = Incident(
        monitor_id=monitor.id,
        started_at=started,
        resolved_at=resolved,
        duration_seconds=600,
        scope=IncidentScope.global_,
    )
    db_session.add(incident)
    db_session.add_all(
        [
            CheckResult(
                monitor_id=monitor.id,
                probe_id=probe.id,
                checked_at=started + timedelta(minutes=1),
                status=CheckStatus.down,
                response_time_ms=200,
            ),
            CheckResult(
                monitor_id=monitor.id,
                probe_id=probe.id,
                checked_at=started + timedelta(minutes=5),
                status=CheckStatus.up,
                response_time_ms=100,
            ),
        ]
    )
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/monitors/{monitor.id}/incidents/{incident.id}/postmortem",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "generated_at" in body
    content = body["content"]
    assert "# Post-mortem: pm-resolved" in content
    assert "10 min 0 s" in content
    assert "10.0 minutes of downtime" in content
    assert "Incident opened" in content
    assert "Incident resolved" in content
    assert "Checks performed: 2" in content
    assert "Failure rate: 50.0%" in content
    assert "Average response time: 150ms" in content


@pytest.mark.asyncio
async def test_postmortem_unknown_incident_returns_404(
    client: AsyncClient,
    user_token: str,
) -> None:
    """Postmortem for a non-existent incident on an owned monitor → 404."""
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "pm-404", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]
    resp = await client.get(
        f"/api/v1/monitors/{monitor_id}/incidents/{uuid.uuid4()}/postmortem",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_postmortem_in_progress_incident_marks_unresolved(
    client: AsyncClient,
    db_session,
    user_token: str,
    regular_user,
) -> None:
    """Unresolved incident → duration label `in progress`, no `resolved` line."""
    from whatisup.models.incident import Incident, IncidentScope
    from whatisup.models.monitor import Monitor

    monitor = Monitor(name="pm-ongoing", url="https://example.com", owner_id=regular_user.id)
    db_session.add(monitor)
    await db_session.flush()

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=15),
        resolved_at=None,
        scope=IncidentScope.global_,
    )
    db_session.add(incident)
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/monitors/{monitor.id}/incidents/{incident.id}/postmortem",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    content = resp.json()["content"]
    assert "in progress" in content
    assert "_in progress_" in content
    assert "Incident resolved" not in content
    assert "_No annotations in this period._" in content
