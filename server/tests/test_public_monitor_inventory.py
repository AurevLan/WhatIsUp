"""Plan cap V2, étape 5c — public name + stop publishing monitor inventory.

``GET /pages/{slug}/monitors`` is unauthenticated. Before this change it
published, per monitor: ``name`` (the operator's internal name), ``url``
(the full monitored URL), ``check_type``, ``tcp_port``, ``dns_record_type``,
and ``current_value`` (= ``latest.final_url``, the URL *after* redirection —
capable of revealing an internal hostname). None of that is anything a
visitor needs to know whether a service is up.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.result import CheckResult, CheckStatus


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_group(client: AsyncClient, token: str, *, name: str, slug: str) -> str:
    resp = await client.post(
        "/api/v1/groups/",
        json={"name": name, "public_slug": slug},
        headers=_auth(token),
    )
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_public_monitors_never_leaks_inventory(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    """No monitored URL, TCP port, DNS record type, or final (redirect) URL
    may ever appear in the raw JSON text of the public monitors payload —
    whatever the check type."""
    group_id = await _make_group(client, user_token, name="LeakGrp", slug="leak-inventory")

    # An HTTP monitor whose URL contains an internal-looking hostname.
    http_mon = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": "Storefront",
                "url": "https://nginx-front-02.internal.example.net/health",
                "group_id": group_id,
            },
            headers=_auth(token=user_token),
        )
    ).json()

    # A TCP monitor with a distinctive, non-default port.
    tcp_mon = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": "DB Replica",
                "url": "http://db-replica-07.internal.example.net",
                "check_type": "tcp",
                "tcp_port": 54321,
                "group_id": group_id,
            },
            headers=_auth(token=user_token),
        )
    ).json()

    # A DNS monitor with a distinctive record type + expected value.
    dns_mon = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": "MX Record",
                "url": "http://mail.example.net",
                "check_type": "dns",
                "dns_record_type": "TXT",
                "dns_expected_value": "v=spf1-super-secret-marker",
                "group_id": group_id,
            },
            headers=_auth(token=user_token),
        )
    ).json()

    # A check result whose final_url reveals a redirect target — the worst
    # leak named in the plan ("l'URL finale après redirection").
    db_session.add(
        CheckResult(
            id=uuid.uuid4(),
            monitor_id=uuid.UUID(http_mon["id"]),
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            final_url="https://redirect-target-secret.internal.example.net/",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/public/pages/leak-inventory/monitors")
    assert resp.status_code == 200
    raw = resp.text

    forbidden = [
        "nginx-front-02",
        "db-replica-07",
        "redirect-target-secret",
        "54321",
        "spf1-super-secret-marker",
        '"tcp_port"',
        '"dns_record_type"',
        '"current_value"',
        '"url"',
        '"check_type"',
    ]
    for needle in forbidden:
        assert needle not in raw, f"public monitors payload leaked {needle!r}"

    # Sanity: the endpoint still works and still names each monitor.
    names = {m["name"] for m in resp.json()}
    assert names == {"Storefront", "DB Replica", "MX Record"}
    del tcp_mon, dns_mon


@pytest.mark.asyncio
async def test_public_monitors_public_name_overrides_internal_name(
    client: AsyncClient, user_token: str
) -> None:
    """``public_name`` is published when set; otherwise ``name`` is the fallback
    — the exact repli the plan requires so nothing regresses for a monitor
    that never sets it."""
    group_id = await _make_group(client, user_token, name="NameGrp", slug="name-fallback")

    plain = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "nginx-front-02", "url": "https://example.com", "group_id": group_id},
            headers=_auth(user_token),
        )
    ).json()

    overridden = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": "nginx-front-03",
                "public_name": "Storefront",
                "url": "https://example.com",
                "group_id": group_id,
            },
            headers=_auth(user_token),
        )
    ).json()

    resp = await client.get("/api/v1/public/pages/name-fallback/monitors")
    assert resp.status_code == 200
    by_id = {m["id"]: m["name"] for m in resp.json()}

    assert by_id[plain["id"]] == "nginx-front-02"
    assert by_id[overridden["id"]] == "Storefront"
    assert "nginx-front-03" not in resp.text


@pytest.mark.asyncio
async def test_public_monitor_out_exposes_public_name(client: AsyncClient, user_token: str) -> None:
    """The authenticated MonitorOut round-trips public_name (create + patch)."""
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "M1", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    assert mon["public_name"] is None

    patched = (
        await client.patch(
            f"/api/v1/monitors/{mon['id']}",
            json={"public_name": "Nice Name"},
            headers=_auth(user_token),
        )
    ).json()
    assert patched["public_name"] == "Nice Name"
