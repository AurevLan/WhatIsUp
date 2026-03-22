#!/usr/bin/env python3
"""
WhatIsUp — Script de recette complet
Teste toutes les routes API contre le serveur Docker live.

Usage:
    python tests/recette.py
    ADMIN_EMAIL=admin@local ADMIN_PASSWORD=xxx python tests/recette.py
    python tests/recette.py --base-url http://localhost:8000

Options d'authentification (dans l'ordre de priorité):
    1. Variables d'env: ADMIN_EMAIL + ADMIN_PASSWORD
    2. Flags: --email / --password
    3. Défaut: recette@test.local / RecettePass1! (créé par create_test_user.sql)
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

BASE = os.getenv("RECETTE_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "recette@test.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "RecettePass1!")

# ── ANSI colors ───────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class Results:
    passed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

results = Results()
_section = ""


def section(name: str) -> None:
    global _section
    _section = name
    print(f"\n{CYAN}{BOLD}{'─'*60}{RESET}")
    print(f"{CYAN}{BOLD}  {name}{RESET}")
    print(f"{CYAN}{'─'*60}{RESET}")


def ok(label: str) -> None:
    results.passed.append(f"{_section} › {label}")
    print(f"  {GREEN}✓{RESET} {label}")


def fail(label: str, detail: str = "") -> None:
    results.failed.append((f"{_section} › {label}", detail))
    msg = f"  {RED}✗{RESET} {label}"
    if detail:
        msg += f"  {DIM}({detail}){RESET}"
    print(msg)


def skip(label: str, reason: str = "") -> None:
    results.skipped.append(f"{_section} › {label}")
    msg = f"  {YELLOW}·{RESET} {label} {DIM}[skip]{RESET}"
    if reason:
        msg += f" {DIM}— {reason}{RESET}"
    print(msg)


def check(label: str, response: httpx.Response, expected: int | list[int], *, store: dict | None = None, key: str | None = None) -> Any:
    """Assert status code and optionally store a field from JSON response."""
    expected_list = [expected] if isinstance(expected, int) else expected
    if response.status_code in expected_list:
        ok(label)
        if store is not None and key is not None:
            try:
                data = response.json()
                val = data[key] if isinstance(data, dict) else data
                store[key] = val
                return val
            except Exception:
                pass
        try:
            return response.json()
        except Exception:
            return None
    else:
        try:
            detail = response.json().get("detail", response.text[:120])
        except Exception:
            detail = response.text[:120]
        fail(label, f"HTTP {response.status_code} — {detail}")
        return None


# ── HTTP client (initialised in main after arg parsing) ──────────────────────

client: httpx.Client = None  # type: ignore
probe_client: httpx.Client = None  # type: ignore

TOKEN: str | None = None
PROBE_KEY: str | None = None

# Shared IDs collected during tests
IDS: dict[str, Any] = {}


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def probe_headers() -> dict:
    return {"X-Probe-Api-Key": PROBE_KEY} if PROBE_KEY else {}


# ══════════════════════════════════════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_health() -> None:
    section("Health")
    r = client.get("/api/health")
    check("GET /api/health", r, 200)
    if r.status_code == 200:
        data = r.json()
        if data.get("services", {}).get("db") == "ok":
            ok("DB connection healthy")
        else:
            fail("DB connection healthy", str(data))
        if data.get("services", {}).get("redis") == "ok":
            ok("Redis connection healthy")
        else:
            fail("Redis connection healthy", str(data))


def test_auth() -> None:
    global TOKEN
    section("Authentication")

    # Login
    r = client.post("/api/v1/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    data = check("POST /auth/login", r, 200)
    if data is None:
        fail("Cannot proceed — login failed")
        return

    TOKEN = data["access_token"]
    refresh = data["refresh_token"]

    # /me
    r = client.get("/api/v1/auth/me", headers=auth_headers())
    me_data = check("GET /auth/me", r, 200)
    if me_data:
        if me_data.get("is_superadmin"):
            ok("User is superadmin")
        else:
            fail("User is superadmin", "recette user is not superadmin")

    # Refresh
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    new_data = check("POST /auth/refresh", r, 200)
    if new_data:
        TOKEN = new_data["access_token"]

    # OIDC config
    r = client.get("/api/v1/auth/oidc/config")
    check("GET /auth/oidc/config", r, 200)

    # Register (should be disabled → 403, or 422 if validation runs first)
    r = client.post("/api/v1/auth/register", json={"email": "x@x.com", "username": "recette_noop", "password": "Disabled1!"})
    check("POST /auth/register (disabled → 403)", r, [403, 422])


def test_monitors() -> None:
    section("Monitors")

    # Create
    r = client.post("/api/v1/monitors/", headers=auth_headers(), json={
        "name": "Recette HTTP Monitor",
        "url": "https://httpbin.org/get",
        "check_type": "http",
        "interval_seconds": 60,
        "network_scope": "all",
    })
    data = check("POST /monitors/ (create)", r, 201)
    if data:
        IDS["monitor_id"] = data["id"]

    if "monitor_id" not in IDS:
        skip("Monitor sub-tests", "create failed")
        return

    mid = IDS["monitor_id"]

    # List
    r = client.get("/api/v1/monitors/", headers=auth_headers())
    check("GET /monitors/ (list)", r, 200)

    # Get by ID
    r = client.get(f"/api/v1/monitors/{mid}", headers=auth_headers())
    check("GET /monitors/{id}", r, 200)

    # Patch — including network_scope
    r = client.patch(f"/api/v1/monitors/{mid}", headers=auth_headers(), json={
        "name": "Recette HTTP Monitor (updated)",
        "network_scope": "external",
    })
    data = check("PATCH /monitors/{id} (update + network_scope)", r, 200)
    if data and data.get("network_scope") == "external":
        ok("network_scope field round-trips correctly")
    elif data:
        fail("network_scope field round-trips correctly", f"got {data.get('network_scope')!r}")

    # Revert scope
    client.patch(f"/api/v1/monitors/{mid}", headers=auth_headers(), json={"network_scope": "all"})

    # Results
    r = client.get(f"/api/v1/monitors/{mid}/results", headers=auth_headers())
    check("GET /monitors/{id}/results", r, 200)

    # Uptime
    r = client.get(f"/api/v1/monitors/{mid}/uptime", headers=auth_headers())
    check("GET /monitors/{id}/uptime", r, 200)

    # History
    r = client.get(f"/api/v1/monitors/{mid}/history", headers=auth_headers())
    check("GET /monitors/{id}/history", r, 200)

    # Probes per monitor
    r = client.get(f"/api/v1/monitors/{mid}/probes", headers=auth_headers())
    check("GET /monitors/{id}/probes", r, 200)

    # Trigger check
    r = client.post(f"/api/v1/monitors/{mid}/trigger-check", headers=auth_headers())
    check("POST /monitors/{id}/trigger-check", r, [200, 202])

    # Incidents
    r = client.get(f"/api/v1/monitors/{mid}/incidents", headers=auth_headers())
    check("GET /monitors/{id}/incidents", r, 200)

    # SLO
    r = client.get(f"/api/v1/monitors/{mid}/slo", headers=auth_headers())
    check("GET /monitors/{id}/slo", r, [200, 404])

    # Report (requires ?from= query param)
    r = client.get(f"/api/v1/monitors/{mid}/report", headers=auth_headers(),
                   params={"from": "2026-01-01T00:00:00Z"})
    check("GET /monitors/{id}/report", r, 200)

    # Annotations CRUD
    r = client.post(f"/api/v1/monitors/{mid}/annotations", headers=auth_headers(), json={
        "content": "Recette annotation",
        "annotated_at": "2026-01-01T00:00:00Z",
    })
    ann = check("POST /monitors/{id}/annotations", r, 201)
    if ann:
        IDS["annotation_id"] = ann["id"]
        r2 = client.get(f"/api/v1/monitors/{mid}/annotations", headers=auth_headers())
        check("GET /monitors/{id}/annotations", r2, 200)
        r3 = client.delete(f"/api/v1/monitors/{mid}/annotations/{ann['id']}", headers=auth_headers())
        check("DELETE /monitors/{id}/annotations/{id}", r3, 204)

    # DNS baseline (HTTP monitor → 400 bad request type)
    r = client.post(f"/api/v1/monitors/{mid}/dns-baseline/accept", headers=auth_headers())
    check("POST /monitors/{id}/dns-baseline/accept (HTTP monitor → 400)", r, [200, 400, 404])

    # Schema baseline accept (HTTP monitor → 400 bad request type)
    r = client.post(f"/api/v1/monitors/{mid}/schema-baseline/accept", headers=auth_headers())
    check("POST /monitors/{id}/schema-baseline/accept (HTTP monitor → 400)", r, [200, 400, 404])

    # Composite members (HTTP monitor → 400)
    r = client.get(f"/api/v1/monitors/{mid}/composite-members", headers=auth_headers())
    check("GET /monitors/{id}/composite-members (HTTP → 400)", r, [200, 400])

    # Bulk action (pause then re-enable the current monitor)
    r = client.post("/api/v1/monitors/bulk", headers=auth_headers(), json={
        "ids": [mid],
        "action": "pause",
    })
    bulk_data = check("POST /monitors/bulk (pause)", r, 200)
    if bulk_data and bulk_data.get("affected", 0) == 1:
        ok("Bulk pause: 1 monitor affected")
    # Re-enable
    client.post("/api/v1/monitors/bulk", headers=auth_headers(), json={"ids": [mid], "action": "enable"})


def test_groups() -> None:
    section("Monitor Groups")

    r = client.post("/api/v1/groups/", headers=auth_headers(), json={
        "name": "Recette Group",
        "description": "Test group",
    })
    data = check("POST /groups/ (create)", r, 201)
    if data:
        IDS["group_id"] = data["id"]

    r = client.get("/api/v1/groups/", headers=auth_headers())
    check("GET /groups/ (list)", r, 200)

    if "group_id" not in IDS:
        skip("Group sub-tests", "create failed")
        return

    gid = IDS["group_id"]

    r = client.get(f"/api/v1/groups/{gid}", headers=auth_headers())
    check("GET /groups/{id}", r, 200)

    r = client.get(f"/api/v1/groups/{gid}/monitors", headers=auth_headers())
    check("GET /groups/{id}/monitors", r, 200)

    r = client.patch(f"/api/v1/groups/{gid}", headers=auth_headers(), json={"name": "Recette Group (updated)"})
    check("PATCH /groups/{id}", r, 200)

    # Assign monitor to group
    if "monitor_id" in IDS:
        client.patch(f"/api/v1/monitors/{IDS['monitor_id']}", headers=auth_headers(), json={"group_id": gid})
        ok("Monitor assigned to group")


def test_probes() -> None:
    global PROBE_KEY
    section("Probes")

    # List (user endpoint)
    r = client.get("/api/v1/probes/", headers=auth_headers())
    check("GET /probes/ (user endpoint)", r, 200)

    # Stats
    r = client.get("/api/v1/probes/stats", headers=auth_headers())
    check("GET /probes/stats", r, 200)

    # Register
    r = client.post("/api/v1/probes/register", headers=auth_headers(), json={
        "name": "Recette-Probe",
        "location_name": "Test Lab",
        "latitude": 47.9,
        "longitude": 1.9,
        "network_type": "external",
    })
    data = check("POST /probes/register", r, 201)
    if data:
        IDS["probe_id"] = data["id"]
        IDS["probe_api_key"] = data["api_key"]
        PROBE_KEY = data["api_key"]

    if "probe_id" not in IDS:
        skip("Probe sub-tests", "register failed")
        return

    pid = IDS["probe_id"]

    # Get by ID
    r = client.get(f"/api/v1/probes/{pid}", headers=auth_headers())
    check("GET /probes/{id}", r, 200)

    # Patch
    r = client.patch(f"/api/v1/probes/{pid}", headers=auth_headers(), json={"location_name": "Test Lab (updated)"})
    check("PATCH /probes/{id}", r, 200)

    # Heartbeat (probe auth)
    r = probe_client.get("/api/v1/probes/heartbeat", headers=probe_headers())
    hb_data = check("GET /probes/heartbeat (probe auth)", r, 200)
    if hb_data:
        monitors = hb_data.get("monitors", [])
        ok(f"Heartbeat returns {len(monitors)} monitors")
        # Validate network_scope filter: external probe should only see 'all' or 'external' monitors
        bad = [m for m in monitors if m.get("network_scope") not in (None, "all", "external")]
        if bad:
            fail("network_scope filter on heartbeat", f"{len(bad)} monitors have wrong scope")
        else:
            ok("network_scope filter: external probe sees only all/external monitors")

    # Push result
    if "monitor_id" in IDS:
        r = probe_client.post("/api/v1/probes/results", headers=probe_headers(), json={
            "monitor_id": IDS["monitor_id"],
            "checked_at": "2026-01-01T00:00:00Z",
            "status": "up",
            "response_time_ms": 120,
        })
        check("POST /probes/results (push result)", r, 202)

    # Incident timeline
    r = client.get(f"/api/v1/probes/{pid}/incident-timeline", headers=auth_headers())
    check("GET /probes/{id}/incident-timeline", r, 200)


def test_alerts() -> None:
    section("Alerts")

    # Channels
    r = client.post("/api/v1/alerts/channels", headers=auth_headers(), json={
        "name": "Recette Webhook",
        "type": "webhook",
        "config": {"url": "https://httpbin.org/post"},
    })
    ch_data = check("POST /alerts/channels (create webhook)", r, 201)
    if ch_data:
        IDS["channel_id"] = ch_data["id"]

    r = client.get("/api/v1/alerts/channels", headers=auth_headers())
    check("GET /alerts/channels", r, 200)

    if "channel_id" not in IDS:
        skip("Alert sub-tests", "channel create failed")
        return

    cid = IDS["channel_id"]

    # Rules
    if "monitor_id" in IDS:
        r = client.post("/api/v1/alerts/rules", headers=auth_headers(), json={
            "monitor_id": IDS["monitor_id"],
            "condition": "any_down",
            "min_duration_seconds": 0,
            "channel_ids": [cid],
        })
        rule = check("POST /alerts/rules (create)", r, 201)
        if rule:
            IDS["rule_id"] = rule["id"]

    r = client.get("/api/v1/alerts/rules", headers=auth_headers())
    check("GET /alerts/rules", r, 200)

    if "rule_id" in IDS:
        rid = IDS["rule_id"]

        # Patch rule
        r = client.patch(f"/api/v1/alerts/rules/{rid}", headers=auth_headers(), json={"enabled": False})
        check("PATCH /alerts/rules/{id}", r, 200)

        # Simulate
        r = client.post(f"/api/v1/alerts/rules/{rid}/simulate", headers=auth_headers())
        check("POST /alerts/rules/{id}/simulate", r, 200)

        # Delete rule
        r = client.delete(f"/api/v1/alerts/rules/{rid}", headers=auth_headers())
        check("DELETE /alerts/rules/{id}", r, 204)

    # Alert events
    r = client.get("/api/v1/alerts/events", headers=auth_headers())
    check("GET /alerts/events", r, 200)

    # Telegram resolve (invalid token → expect 400/422/502)
    r = client.post("/api/v1/alerts/telegram/resolve", headers=auth_headers(), json={"bot_token": "invalid:token"})
    check("POST /alerts/telegram/resolve (bad token → 400/502)", r, [400, 422, 502, 503])

    # Delete channel
    r = client.delete(f"/api/v1/alerts/channels/{cid}", headers=auth_headers())
    check("DELETE /alerts/channels/{id}", r, 204)


def test_admin() -> None:
    section("Admin — Users")

    r = client.get("/api/v1/admin/users", headers=auth_headers())
    check("GET /admin/users", r, 200)

    # Create user
    r = client.post("/api/v1/admin/users", headers=auth_headers(), json={
        "email": "recette_sub@example.com",
        "username": "recette_sub",
        "password": "RecettePass1!",
        "full_name": "Recette Sub",
        "can_create_monitors": True,
    })
    udata = check("POST /admin/users (create)", r, 201)
    if udata:
        IDS["sub_user_id"] = udata["id"]

    if "sub_user_id" in IDS:
        uid = IDS["sub_user_id"]

        r = client.patch(f"/api/v1/admin/users/{uid}", headers=auth_headers(), json={"can_create_monitors": False})
        check("PATCH /admin/users/{id} (update permissions)", r, 200)

    # Admin monitors list
    r = client.get("/api/v1/admin/monitors", headers=auth_headers())
    check("GET /admin/monitors", r, 200)

    section("Admin — Probe Groups")

    r = client.post("/api/v1/admin/probe-groups", headers=auth_headers(), json={
        "name": "Recette ProbeGroup",
        "description": "Test probe group",
    })
    pg_data = check("POST /admin/probe-groups (create)", r, 201)
    if pg_data:
        IDS["probe_group_id"] = pg_data["id"]

    r = client.get("/api/v1/admin/probe-groups", headers=auth_headers())
    check("GET /admin/probe-groups", r, 200)

    if "probe_group_id" in IDS:
        pgid = IDS["probe_group_id"]

        # Add probe to group
        if "probe_id" in IDS:
            r = client.post(f"/api/v1/admin/probe-groups/{pgid}/probes", headers=auth_headers(), json={"probe_ids": [str(IDS["probe_id"])]})
            check("POST /admin/probe-groups/{id}/probes", r, 200)

        # Add user to group
        if "sub_user_id" in IDS:
            r = client.post(f"/api/v1/admin/probe-groups/{pgid}/users", headers=auth_headers(), json={"user_ids": [str(IDS["sub_user_id"])]})
            check("POST /admin/probe-groups/{id}/users", r, 200)

            r = client.delete(f"/api/v1/admin/probe-groups/{pgid}/users/{IDS['sub_user_id']}", headers=auth_headers())
            check("DELETE /admin/probe-groups/{id}/users/{user_id}", r, 204)

        if "probe_id" in IDS:
            r = client.delete(f"/api/v1/admin/probe-groups/{pgid}/probes/{IDS['probe_id']}", headers=auth_headers())
            check("DELETE /admin/probe-groups/{id}/probes/{probe_id}", r, 204)

        r = client.patch(f"/api/v1/admin/probe-groups/{pgid}", headers=auth_headers(), json={"name": "Recette PG (updated)"})
        check("PATCH /admin/probe-groups/{id}", r, 200)

        r = client.delete(f"/api/v1/admin/probe-groups/{pgid}", headers=auth_headers())
        check("DELETE /admin/probe-groups/{id}", r, 204)

    # Delete sub user
    if "sub_user_id" in IDS:
        r = client.delete(f"/api/v1/admin/users/{IDS['sub_user_id']}", headers=auth_headers())
        check("DELETE /admin/users/{id}", r, 204)


def test_maintenance() -> None:
    section("Maintenance Windows")

    monitor_id_for_mw = IDS.get("monitor_id")
    if not monitor_id_for_mw:
        skip("Maintenance Windows", "no monitor_id")
        return
    r = client.post("/api/v1/maintenance/", headers=auth_headers(), json={
        "name": "Recette Maintenance",
        "monitor_id": str(monitor_id_for_mw),
        "starts_at": "2026-12-01T00:00:00Z",
        "ends_at": "2026-12-02T00:00:00Z",
        "suppress_alerts": True,
    })
    mw = check("POST /maintenance/ (create)", r, 201)
    if mw:
        IDS["mw_id"] = mw["id"]

    r = client.get("/api/v1/maintenance/", headers=auth_headers())
    check("GET /maintenance/ (list)", r, 200)

    if "mw_id" in IDS:
        mwid = IDS["mw_id"]
        r = client.patch(f"/api/v1/maintenance/{mwid}", headers=auth_headers(), json={
            "name": "Updated MW",
            "monitor_id": str(monitor_id_for_mw),
            "starts_at": "2026-12-01T00:00:00Z",
            "ends_at": "2026-12-02T00:00:00Z",
        })
        check("PATCH /maintenance/{id}", r, 200)
        r = client.delete(f"/api/v1/maintenance/{mwid}", headers=auth_headers())
        check("DELETE /maintenance/{id}", r, 204)


def test_audit() -> None:
    section("Audit")
    r = client.get("/api/v1/audit/", headers=auth_headers())
    check("GET /audit/ (list)", r, 200)


def test_api_keys() -> None:
    section("API Keys")

    r = client.get("/api/v1/api-keys/", headers=auth_headers())
    check("GET /api-keys/ (list)", r, 200)

    r = client.post("/api/v1/api-keys/", headers=auth_headers(), json={"name": "Recette Key"})
    key_data = check("POST /api-keys/ (create)", r, 201)
    if key_data:
        IDS["api_key_id"] = key_data["id"]

    if "api_key_id" in IDS:
        r = client.delete(f"/api/v1/api-keys/{IDS['api_key_id']}", headers=auth_headers())
        check("DELETE /api-keys/{id}", r, 204)


def test_templates() -> None:
    section("Templates")

    r = client.get("/api/v1/templates/", headers=auth_headers())
    check("GET /templates/ (list)", r, 200)

    r = client.post("/api/v1/templates/", headers=auth_headers(), json={
        "name": "Recette Template",
        "check_type": "http",
        "monitor_config": {"interval_seconds": 30, "timeout_seconds": 5},
    })
    tpl = check("POST /templates/ (create)", r, 201)
    if tpl:
        IDS["template_id"] = tpl["id"]

    if "template_id" in IDS:
        tid = IDS["template_id"]
        r = client.get(f"/api/v1/templates/{tid}", headers=auth_headers())
        check("GET /templates/{id}", r, 200)

        r = client.patch(f"/api/v1/templates/{tid}", headers=auth_headers(), json={"name": "Recette TPL (updated)"})
        check("PATCH /templates/{id}", r, 200)

        r = client.delete(f"/api/v1/templates/{tid}", headers=auth_headers())
        check("DELETE /templates/{id}", r, 204)


def test_status() -> None:
    section("Status")
    r = client.get("/api/v1/status/monitors", headers=auth_headers())
    check("GET /status/monitors", r, 200)

    if "monitor_id" in IDS:
        r = client.get(f"/api/v1/status/monitors/{IDS['monitor_id']}", headers=auth_headers())
        check("GET /status/monitors/{id}", r, 200)


def test_ping() -> None:
    section("Ping / Heartbeat monitors")

    # Create heartbeat monitor
    r = client.post("/api/v1/monitors/", headers=auth_headers(), json={
        "name": "Recette Heartbeat",
        "url": "http://heartbeat",
        "check_type": "heartbeat",
        "heartbeat_slug": "recette-hb-test",
        "heartbeat_interval_seconds": 3600,
        "heartbeat_grace_seconds": 300,
    })
    hb = check("POST /monitors/ (heartbeat type)", r, 201)
    if hb:
        IDS["hb_monitor_id"] = hb["id"]

        r = client.post("/api/v1/ping/recette-hb-test")
        check("POST /ping/{slug}", r, 200)

        r = client.get("/api/v1/ping/recette-hb-test")
        check("GET /ping/{slug} (status)", r, 200)

        client.delete(f"/api/v1/monitors/{hb['id']}", headers=auth_headers())


def test_incident_groups() -> None:
    section("Incident Groups")
    r = client.get("/api/v1/incident-groups/", headers=auth_headers())
    check("GET /incident-groups/ (list)", r, 200)


def test_metrics() -> None:
    section("Custom Metrics")
    if "monitor_id" not in IDS:
        skip("Custom metrics", "no monitor")
        return

    mid = IDS["monitor_id"]
    r = client.post(f"/api/v1/metrics/{mid}", headers=auth_headers(), json={
        "metric_name": "recette_metric",
        "value": 42.0,
        "unit": "ms",
    })
    check("POST /metrics/{monitor_id} (push)", r, [201, 202])

    r = client.get(f"/api/v1/metrics/{mid}", headers=auth_headers())
    check("GET /metrics/{monitor_id} (list)", r, 200)


def test_public_pages() -> None:
    section("Public Status Pages")
    # Create a group with public_slug
    r = client.post("/api/v1/groups/", headers=auth_headers(), json={
        "name": "Recette Public Group",
        "public_slug": "recette-public-test",
    })
    pub_group = check("POST /groups/ (with public_slug)", r, 201)
    if pub_group:
        slug = pub_group.get("public_slug")
        if slug:
            r = client.get(f"/api/v1/public/pages/{slug}")
            check("GET /public/pages/{slug}", r, 200)

            r = client.get(f"/api/v1/public/pages/{slug}/monitors")
            check("GET /public/pages/{slug}/monitors", r, 200)

            r = client.get(f"/api/v1/public/pages/{slug}/status")
            check("GET /public/pages/{slug}/status", r, 200)

        client.delete(f"/api/v1/groups/{pub_group['id']}", headers=auth_headers())


def test_cleanup() -> None:
    section("Cleanup")

    # Delete monitor
    if "monitor_id" in IDS:
        r = client.delete(f"/api/v1/monitors/{IDS['monitor_id']}", headers=auth_headers())
        check("DELETE /monitors/{id} (cleanup)", r, 204)

    # Delete group
    if "group_id" in IDS:
        r = client.delete(f"/api/v1/groups/{IDS['group_id']}", headers=auth_headers())
        check("DELETE /groups/{id} (cleanup)", r, 204)

    # Delete probe
    if "probe_id" in IDS:
        r = client.delete(f"/api/v1/probes/{IDS['probe_id']}", headers=auth_headers())
        check("DELETE /probes/{id} (cleanup)", r, 204)

    ok("Cleanup complete")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def print_summary() -> None:
    total = len(results.passed) + len(results.failed) + len(results.skipped)
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  RÉSULTATS DE RECETTE{RESET}")
    print(f"{'═'*60}")
    print(f"  {GREEN}✓ Passés   : {len(results.passed)}{RESET}")
    print(f"  {RED}✗ Échoués  : {len(results.failed)}{RESET}")
    print(f"  {YELLOW}· Ignorés  : {len(results.skipped)}{RESET}")
    print(f"  Total    : {total}")
    if results.failed:
        print(f"\n{RED}{BOLD}  ÉCHECS DÉTAILLÉS :{RESET}")
        for label, detail in results.failed:
            print(f"  {RED}✗{RESET} {label}")
            if detail:
                print(f"    {DIM}→ {detail}{RESET}")
    print(f"{'═'*60}\n")


def main() -> int:
    global BASE, ADMIN_EMAIL, ADMIN_PASSWORD, client, probe_client

    parser = argparse.ArgumentParser(description="WhatIsUp recette tests")
    parser.add_argument("--base-url", default=BASE)
    parser.add_argument("--email", default=ADMIN_EMAIL)
    parser.add_argument("--password", default=ADMIN_PASSWORD)
    args = parser.parse_args()

    BASE = args.base_url
    ADMIN_EMAIL = args.email
    ADMIN_PASSWORD = args.password
    _headers = {"Connection": "close"}
    client = httpx.Client(base_url=BASE, timeout=15, headers=_headers)
    probe_client = httpx.Client(base_url=BASE, timeout=15, headers=_headers)

    print(f"\n{BOLD}WhatIsUp — Recette API{RESET}")
    print(f"{DIM}Cible : {BASE}  ·  Utilisateur : {ADMIN_EMAIL}{RESET}")
    print(f"{DIM}Démarrage : {time.strftime('%Y-%m-%d %H:%M:%S')}{RESET}")

    # Check server is up
    try:
        r = client.get("/api/health", timeout=5)
        if r.status_code != 200:
            print(f"\n{RED}Serveur non disponible ({r.status_code}). Vérifiez que Docker est lancé.{RESET}")
            return 1
    except Exception as e:
        print(f"\n{RED}Impossible de joindre le serveur : {e}{RESET}")
        print(f"{DIM}Lancez d'abord : docker compose --env-file .env up -d{RESET}")
        return 1

    test_health()
    test_auth()
    if TOKEN is None:
        print(f"\n{RED}Authentification échouée — impossible de continuer.{RESET}")
        print_summary()
        return 1

    test_monitors()
    test_groups()
    test_probes()
    test_alerts()
    test_admin()
    test_maintenance()
    test_audit()
    test_api_keys()
    test_templates()
    test_status()
    test_ping()
    test_incident_groups()
    test_metrics()
    test_public_pages()
    test_cleanup()

    print_summary()
    return 1 if results.failed else 0


if __name__ == "__main__":
    sys.exit(main())
