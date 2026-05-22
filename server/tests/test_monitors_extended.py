"""Extended API tests for monitors.py — coverage boost.

Targets endpoints that were previously uncovered: SLO rules CRUD,
composite members CRUD, dependencies list/delete, dependency graph,
import/export, results, uptime, history, annotations list/delete,
correlated, percentiles, monitor_probe_status, SLA report, trigger-check.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_monitor(
    client: AsyncClient,
    token: str,
    name: str = "Mon",
    **extra,
) -> dict:
    body = {"name": name, "url": "https://example.com"}
    body.update(extra)
    resp = await client.post("/api/v1/monitors/", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_monitors_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/monitors/export", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_export_monitors_strips_runtime_fields(client: AsyncClient, user_token: str) -> None:
    await _make_monitor(client, user_token, name="Exp1")
    await _make_monitor(client, user_token, name="Exp2")
    resp = await client.get("/api/v1/monitors/export", headers=_auth(user_token))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    for it in items:
        assert "id" not in it
        assert "owner_id" not in it
        assert "created_at" not in it
        assert "last_status" not in it
        assert "name" in it
        assert "url" in it


@pytest.mark.asyncio
async def test_import_creates_new_monitors(client: AsyncClient, user_token: str) -> None:
    payload = [
        {"name": "Imp-A", "url": "https://a.example.com", "interval_seconds": 90},
        {"name": "Imp-B", "url": "https://b.example.com"},
    ]
    resp = await client.post("/api/v1/monitors/import", json=payload, headers=_auth(user_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2
    assert body["updated"] == 0
    assert body["errors"] == []


@pytest.mark.asyncio
async def test_import_updates_existing_by_name(client: AsyncClient, user_token: str) -> None:
    await _make_monitor(client, user_token, name="Existing", interval_seconds=60)
    payload = [{"name": "Existing", "url": "https://example.com", "interval_seconds": 120}]
    resp = await client.post("/api/v1/monitors/import", json=payload, headers=_auth(user_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 0
    assert body["updated"] == 1


@pytest.mark.asyncio
async def test_import_missing_name_returns_error(client: AsyncClient, user_token: str) -> None:
    payload = [{"url": "https://example.com"}]
    resp = await client.post("/api/v1/monitors/import", json=payload, headers=_auth(user_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 0
    assert len(body["errors"]) == 1
    assert "name" in body["errors"][0].lower()


@pytest.mark.asyncio
async def test_import_missing_url_returns_error(client: AsyncClient, user_token: str) -> None:
    payload = [{"name": "Bad"}]
    resp = await client.post("/api/v1/monitors/import", json=payload, headers=_auth(user_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 0
    assert len(body["errors"]) == 1
    assert "url" in body["errors"][0].lower()


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dependency_graph_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/monitors/graph", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}


@pytest.mark.asyncio
async def test_dependency_graph_nodes_and_edges(client: AsyncClient, user_token: str) -> None:
    parent = await _make_monitor(client, user_token, name="GraphParent")
    child = await _make_monitor(client, user_token, name="GraphChild")
    dep_resp = await client.post(
        f"/api/v1/monitors/{child['id']}/dependencies",
        json={"parent_id": parent["id"], "suppress_on_parent_down": False},
        headers=_auth(user_token),
    )
    assert dep_resp.status_code == 201

    resp = await client.get("/api/v1/monitors/graph", headers=_auth(user_token))
    assert resp.status_code == 200
    graph = resp.json()
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1
    edge = graph["edges"][0]
    assert edge["source"] == parent["id"]
    assert edge["target"] == child["id"]
    assert edge["suppress_on_parent_down"] is False


# ---------------------------------------------------------------------------
# Dependencies CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_dependencies_empty(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="DepEmpty")
    resp = await client.get(f"/api/v1/monitors/{m['id']}/dependencies", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_dependency_self_reference_rejected(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="SelfDep")
    resp = await client.post(
        f"/api/v1/monitors/{m['id']}/dependencies",
        json={"parent_id": m["id"]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_dependency_duplicate_409(client: AsyncClient, user_token: str) -> None:
    parent = await _make_monitor(client, user_token, name="P")
    child = await _make_monitor(client, user_token, name="C")
    first = await client.post(
        f"/api/v1/monitors/{child['id']}/dependencies",
        json={"parent_id": parent["id"]},
        headers=_auth(user_token),
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/monitors/{child['id']}/dependencies",
        json={"parent_id": parent["id"]},
        headers=_auth(user_token),
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_remove_dependency(client: AsyncClient, user_token: str) -> None:
    parent = await _make_monitor(client, user_token, name="DelP")
    child = await _make_monitor(client, user_token, name="DelC")
    create = await client.post(
        f"/api/v1/monitors/{child['id']}/dependencies",
        json={"parent_id": parent["id"]},
        headers=_auth(user_token),
    )
    dep_id = create.json()["id"]
    resp = await client.delete(
        f"/api/v1/monitors/{child['id']}/dependencies/{dep_id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 204

    # Subsequent delete returns 404
    resp2 = await client.delete(
        f"/api/v1/monitors/{child['id']}/dependencies/{dep_id}",
        headers=_auth(user_token),
    )
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_remove_dependency_unknown_404(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="DepUnknown")
    resp = await client.delete(
        f"/api/v1/monitors/{m['id']}/dependencies/{uuid.uuid4()}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Composite members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_composite_members_requires_composite_type(
    client: AsyncClient, user_token: str
) -> None:
    m = await _make_monitor(client, user_token, name="NotComp")
    resp = await client.get(
        f"/api/v1/monitors/{m['id']}/composite-members", headers=_auth(user_token)
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_composite_members_empty(client: AsyncClient, user_token: str) -> None:
    comp = await _make_monitor(client, user_token, name="CompEmpty", check_type="composite")
    resp = await client.get(
        f"/api/v1/monitors/{comp['id']}/composite-members", headers=_auth(user_token)
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_add_composite_member_target_not_composite_400(
    client: AsyncClient, user_token: str
) -> None:
    not_comp = await _make_monitor(client, user_token, name="NotComp2")
    member = await _make_monitor(client, user_token, name="Member")
    resp = await client.post(
        f"/api/v1/monitors/{not_comp['id']}/composite-members",
        json={"monitor_id": member["id"]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_add_composite_member_self_400(client: AsyncClient, user_token: str) -> None:
    comp = await _make_monitor(client, user_token, name="CompSelf", check_type="composite")
    resp = await client.post(
        f"/api/v1/monitors/{comp['id']}/composite-members",
        json={"monitor_id": comp["id"]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_add_composite_member_then_duplicate_409(
    client: AsyncClient, user_token: str
) -> None:
    comp = await _make_monitor(client, user_token, name="CompDup", check_type="composite")
    member = await _make_monitor(client, user_token, name="DupMember")
    first = await client.post(
        f"/api/v1/monitors/{comp['id']}/composite-members",
        json={"monitor_id": member["id"], "weight": 2, "role": "primary"},
        headers=_auth(user_token),
    )
    assert first.status_code == 201
    body = first.json()
    assert body["weight"] == 2
    assert body["role"] == "primary"
    second = await client.post(
        f"/api/v1/monitors/{comp['id']}/composite-members",
        json={"monitor_id": member["id"]},
        headers=_auth(user_token),
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_update_composite_member(client: AsyncClient, user_token: str) -> None:
    comp = await _make_monitor(client, user_token, name="CompUpd", check_type="composite")
    member = await _make_monitor(client, user_token, name="UpdMember")
    create = await client.post(
        f"/api/v1/monitors/{comp['id']}/composite-members",
        json={"monitor_id": member["id"], "weight": 1},
        headers=_auth(user_token),
    )
    member_id = create.json()["id"]
    upd = await client.patch(
        f"/api/v1/monitors/{comp['id']}/composite-members/{member_id}",
        json={"monitor_id": member["id"], "weight": 5, "role": "backup"},
        headers=_auth(user_token),
    )
    assert upd.status_code == 200
    assert upd.json()["weight"] == 5
    assert upd.json()["role"] == "backup"


@pytest.mark.asyncio
async def test_update_composite_member_unknown_404(client: AsyncClient, user_token: str) -> None:
    comp = await _make_monitor(client, user_token, name="CompU404", check_type="composite")
    member = await _make_monitor(client, user_token, name="X")
    resp = await client.patch(
        f"/api/v1/monitors/{comp['id']}/composite-members/{uuid.uuid4()}",
        json={"monitor_id": member["id"], "weight": 1},
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_remove_composite_member(client: AsyncClient, user_token: str) -> None:
    comp = await _make_monitor(client, user_token, name="CompRm", check_type="composite")
    member = await _make_monitor(client, user_token, name="RmMember")
    create = await client.post(
        f"/api/v1/monitors/{comp['id']}/composite-members",
        json={"monitor_id": member["id"]},
        headers=_auth(user_token),
    )
    member_id = create.json()["id"]
    resp = await client.delete(
        f"/api/v1/monitors/{comp['id']}/composite-members/{member_id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 204

    # Second delete → 404
    resp2 = await client.delete(
        f"/api/v1/monitors/{comp['id']}/composite-members/{member_id}",
        headers=_auth(user_token),
    )
    assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# SLO Rules CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slo_rule_create_quorum_down(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="SLOQ")
    resp = await client.post(
        f"/api/v1/monitors/{m['id']}/slo-rules",
        json={
            "rule_type": "quorum_down",
            "quorum_ratio": 0.6,
            "window_seconds": 300,
            "min_probes": 2,
            "cooldown_seconds": 60,
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["rule_type"] == "quorum_down"
    assert data["quorum_ratio"] == 0.6
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_slo_rule_list_after_create(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="SLOList")
    await client.post(
        f"/api/v1/monitors/{m['id']}/slo-rules",
        json={
            "rule_type": "quorum_slow",
            "p95_threshold_ms": 2000,
            "window_seconds": 300,
        },
        headers=_auth(user_token),
    )
    resp = await client.get(f"/api/v1/monitors/{m['id']}/slo-rules", headers=_auth(user_token))
    assert resp.status_code == 200
    rules = resp.json()
    assert len(rules) == 1
    assert rules[0]["rule_type"] == "quorum_slow"
    assert rules[0]["p95_threshold_ms"] == 2000


@pytest.mark.asyncio
async def test_slo_rule_update(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="SLOUpd")
    create = await client.post(
        f"/api/v1/monitors/{m['id']}/slo-rules",
        json={
            "rule_type": "quorum_down",
            "quorum_ratio": 0.5,
            "window_seconds": 300,
        },
        headers=_auth(user_token),
    )
    rule_id = create.json()["id"]
    upd = await client.patch(
        f"/api/v1/monitors/{m['id']}/slo-rules/{rule_id}",
        json={"enabled": False, "quorum_ratio": 0.8},
        headers=_auth(user_token),
    )
    assert upd.status_code == 200
    body = upd.json()
    assert body["enabled"] is False
    assert body["quorum_ratio"] == 0.8


@pytest.mark.asyncio
async def test_slo_rule_update_unknown_404(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="SLOUpd404")
    resp = await client.patch(
        f"/api/v1/monitors/{m['id']}/slo-rules/{uuid.uuid4()}",
        json={"enabled": False},
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_slo_rule_delete(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="SLODel")
    create = await client.post(
        f"/api/v1/monitors/{m['id']}/slo-rules",
        json={
            "rule_type": "quorum_down",
            "quorum_ratio": 0.5,
            "window_seconds": 300,
        },
        headers=_auth(user_token),
    )
    rule_id = create.json()["id"]
    resp = await client.delete(
        f"/api/v1/monitors/{m['id']}/slo-rules/{rule_id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 204

    # Second delete → 404
    resp2 = await client.delete(
        f"/api/v1/monitors/{m['id']}/slo-rules/{rule_id}",
        headers=_auth(user_token),
    )
    assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# Annotations list/delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_annotations(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="AnnList")
    now = datetime.now(UTC).isoformat()
    await client.post(
        f"/api/v1/monitors/{m['id']}/annotations",
        json={"content": "a1", "annotated_at": now},
        headers=_auth(user_token),
    )
    resp = await client.get(
        f"/api/v1/monitors/{m['id']}/annotations",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["content"] == "a1"


@pytest.mark.asyncio
async def test_delete_annotation(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="AnnDel")
    create = await client.post(
        f"/api/v1/monitors/{m['id']}/annotations",
        json={"content": "to_delete", "annotated_at": datetime.now(UTC).isoformat()},
        headers=_auth(user_token),
    )
    ann_id = create.json()["id"]
    resp = await client.delete(
        f"/api/v1/monitors/{m['id']}/annotations/{ann_id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_annotation_unknown_404(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="AnnDel404")
    resp = await client.delete(
        f"/api/v1/monitors/{m['id']}/annotations/{uuid.uuid4()}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Results / uptime / history / percentiles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_results_empty(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="Res")
    resp = await client.get(f"/api/v1/monitors/{m['id']}/results", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_results_with_since_filter(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="ResSince")
    # Use naive UTC iso (no +00:00 suffix that breaks query parsing without urlencode)
    since = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    resp = await client.get(
        f"/api/v1/monitors/{m['id']}/results?since={since}&limit=10",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_uptime_empty(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="Up")
    resp = await client.get(
        f"/api/v1/monitors/{m['id']}/uptime?period_hours=24",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime_percent" in data


@pytest.mark.asyncio
async def test_get_history(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="Hist")
    resp = await client.get(f"/api/v1/monitors/{m['id']}/history?days=7", headers=_auth(user_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_incidents_filter(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="Inc")
    # Just call all filter branches
    r1 = await client.get(
        f"/api/v1/monitors/{m['id']}/incidents",
        headers=_auth(user_token),
    )
    assert r1.status_code == 200

    r2 = await client.get(
        f"/api/v1/monitors/{m['id']}/incidents?resolved=true",
        headers=_auth(user_token),
    )
    assert r2.status_code == 200

    r3 = await client.get(
        f"/api/v1/monitors/{m['id']}/incidents?resolved=false",
        headers=_auth(user_token),
    )
    assert r3.status_code == 200


# ---------------------------------------------------------------------------
# SLA Report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sla_report_with_range(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="SLAReport")
    now = datetime.now(UTC)
    # Strip +00:00 so the query parser is happy with the raw URL string
    from_iso = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    to_iso = now.strftime("%Y-%m-%dT%H:%M:%S")
    resp = await client.get(
        f"/api/v1/monitors/{m['id']}/report?from={from_iso}&to={to_iso}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "incident_count" in data
    assert "total_downtime_seconds" in data
    assert "uptime_percent" in data


@pytest.mark.asyncio
async def test_sla_report_default_to(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="SLAReport2")
    from_iso = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    resp = await client.get(
        f"/api/v1/monitors/{m['id']}/report?from={from_iso}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Trigger-check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_check(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="Trig")
    resp = await client.post(
        f"/api/v1/monitors/{m['id']}/trigger-check",
        headers=_auth(user_token),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert data["monitor_id"] == m["id"]


# ---------------------------------------------------------------------------
# Correlated monitors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlated_empty(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="Corr")
    resp = await client.get(f"/api/v1/monitors/{m['id']}/correlated", headers=_auth(user_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Health state (superadmin only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_state_not_exists(client: AsyncClient, admin_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "HState", "url": "https://example.com"},
        headers=_auth(admin_token),
    )
    monitor_id = create.json()["id"]
    resp = await client.get(
        f"/api/v1/monitors/{monitor_id}/health-state",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is False
    assert data["sample_count_5m"] == 0


@pytest.mark.asyncio
async def test_health_state_requires_superadmin(client: AsyncClient, user_token: str) -> None:
    m = await _make_monitor(client, user_token, name="HStateUser")
    resp = await client.get(
        f"/api/v1/monitors/{m['id']}/health-state",
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Monitor probe status (superadmin)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_probe_status(client: AsyncClient, admin_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "MProbe", "url": "https://example.com"},
        headers=_auth(admin_token),
    )
    monitor_id = create.json()["id"]
    resp = await client.get(
        f"/api/v1/monitors/{monitor_id}/probes",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# List monitors with results (enriches sparkline, last_status, etc.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_monitors_filters_enabled(client: AsyncClient, user_token: str) -> None:
    await _make_monitor(client, user_token, name="Enabled1", enabled=True)
    await _make_monitor(client, user_token, name="Disabled1", enabled=False)
    resp = await client.get("/api/v1/monitors/?enabled=true", headers=_auth(user_token))
    assert resp.status_code == 200
    items = resp.json()
    for it in items:
        assert it["enabled"] is True


@pytest.mark.asyncio
async def test_list_monitors_group_filter(client: AsyncClient, user_token: str) -> None:
    grp = await client.post(
        "/api/v1/groups/",
        json={"name": "FilterGrp"},
        headers=_auth(user_token),
    )
    group_id = grp.json()["id"]
    await _make_monitor(client, user_token, name="InG1", group_id=group_id)
    await _make_monitor(client, user_token, name="OutG1")
    resp = await client.get(
        f"/api/v1/monitors/?group_id={group_id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    items = resp.json()
    assert all(it["group_id"] == group_id for it in items)


# Note: monitors/ list with CheckResult is not unit-testable on SQLite because
# the production code subtracts an offset-aware `now` from the DB column which
# SQLite returns as a naive datetime. The PostgreSQL test path exercises this.


# ---------------------------------------------------------------------------
# Update — runbook/scenario-variables edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_url_and_tag_ids(client: AsyncClient, user_token: str) -> None:
    """Exercise update_monitor branches for url stringification + tag updates."""
    m = await _make_monitor(client, user_token, name="UpdMisc")
    # Create a tag first
    tag_resp = await client.post(
        "/api/v1/tags/",
        json={"name": "tag1", "color": "#ff0000"},
        headers=_auth(user_token),
    )
    assert tag_resp.status_code == 201
    tag_id = tag_resp.json()["id"]

    upd = await client.patch(
        f"/api/v1/monitors/{m['id']}",
        json={"url": "https://updated.example.com", "tag_ids": [tag_id]},
        headers=_auth(user_token),
    )
    assert upd.status_code == 200
    # The URL is normalized with trailing slash
    assert upd.json()["url"].startswith("https://updated.example.com")
