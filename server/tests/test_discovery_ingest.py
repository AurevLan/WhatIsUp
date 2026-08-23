"""Probe-facing discovery channel — heartbeat distribution + ingestion (plan D, D-1).

Two things D-0 left unbuilt: the heartbeat handing a probe its own enabled
``discovery_sources`` (and persisting ``discovery_capabilities`` it declares),
and ``POST /probes/discovery`` storing the snapshot it pushes back. Neither
does any reconciliation (D-2) — this module pins the D-1 contract only:
scope-binding (a probe only ever sees/writes its own sources, with no oracle
on rejection reason), upsert idempotence, ``status`` never touched by a push,
bounds (500 services, hints truncation), and server-side normalization.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.probe import Probe
from whatisup.models.user import User

# Low-cost hash — bcrypt rounds=4 makes tests fast (~10ms vs ~200ms at rounds=12)
_PROBE_A_KEY = "wiu_test_discovery_probe_a_key"
_PROBE_A_HEADERS = {"X-Probe-Api-Key": _PROBE_A_KEY}
_PROBE_B_KEY = "wiu_test_discovery_probe_b_key"
_PROBE_B_HEADERS = {"X-Probe-Api-Key": _PROBE_B_KEY}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _hash(key: str) -> str:
    return bcrypt.hashpw(key.encode(), bcrypt.gensalt(rounds=4)).decode()


@pytest_asyncio.fixture
async def probe_a(db_session: AsyncSession) -> Probe:
    probe = Probe(name="discovery-probe-a", location_name="A", api_key_hash=_hash(_PROBE_A_KEY))
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest_asyncio.fixture
async def probe_b(db_session: AsyncSession) -> Probe:
    probe = Probe(name="discovery-probe-b", location_name="B", api_key_hash=_hash(_PROBE_B_KEY))
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest_asyncio.fixture
async def source_on_a(
    db_session: AsyncSession, regular_user: User, probe_a: Probe
) -> DiscoverySource:
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=probe_a.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
        enabled=True,
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()
    return source


def _services_payload(n: int = 2) -> list[dict]:
    return [
        {"host": f"10.0.0.{i}", "port": 80, "proto": "tcp", "hints": {}} for i in range(1, n + 1)
    ]


# ── Heartbeat — discovery_sources distribution ───────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_returns_only_this_probes_enabled_sources(
    client: AsyncClient,
    db_session: AsyncSession,
    regular_user: User,
    probe_a: Probe,
    probe_b: Probe,
    source_on_a: DiscoverySource,
) -> None:
    # Disabled source on the same probe — must not be returned.
    disabled = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=probe_a.id,
        source_type="docker",
        params={},
        enabled=False,
    )
    # Enabled source on a *different* probe — must not leak into probe A's heartbeat.
    other_probe_source = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=probe_b.id,
        source_type="docker",
        params={},
        enabled=True,
    )
    db_session.add_all([disabled, other_probe_source])
    await db_session.flush()
    await db_session.commit()

    resp = await client.post("/api/v1/probes/heartbeat", json={}, headers=_PROBE_A_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    ids = {s["id"] for s in body["discovery_sources"]}
    assert ids == {str(source_on_a.id)}
    assert body["discovery_sources"][0]["source_type"] == "port_scan"
    assert body["discovery_sources"][0]["params"] == {"cidr": "10.0.0.0/24", "ports": [80]}


@pytest.mark.asyncio
async def test_heartbeat_probe_with_no_sources_gets_empty_list(
    client: AsyncClient, probe_a: Probe
) -> None:
    resp = await client.post("/api/v1/probes/heartbeat", json={}, headers=_PROBE_A_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["discovery_sources"] == []


# ── Heartbeat — discovery_capabilities persistence ───────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_persists_discovery_capabilities(
    client: AsyncClient, db_session: AsyncSession, probe_a: Probe
) -> None:
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={"discovery_capabilities": ["docker", "port_scan"]},
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 200

    await db_session.refresh(probe_a)
    assert probe_a.discovery_capabilities == ["docker", "port_scan"]


@pytest.mark.asyncio
async def test_heartbeat_without_field_does_not_clear_existing_capabilities(
    client: AsyncClient, db_session: AsyncSession, probe_a: Probe
) -> None:
    first = await client.post(
        "/api/v1/probes/heartbeat",
        json={"discovery_capabilities": ["docker"]},
        headers=_PROBE_A_HEADERS,
    )
    assert first.status_code == 200

    # Older-probe-shaped heartbeat: field entirely absent from the body.
    second = await client.post(
        "/api/v1/probes/heartbeat",
        json={"health": {"cpu_percent": 1.0}},
        headers=_PROBE_A_HEADERS,
    )
    assert second.status_code == 200

    await db_session.refresh(probe_a)
    assert probe_a.discovery_capabilities == ["docker"]


@pytest.mark.asyncio
async def test_heartbeat_explicit_empty_capabilities_clears(
    client: AsyncClient, db_session: AsyncSession, probe_a: Probe
) -> None:
    await client.post(
        "/api/v1/probes/heartbeat",
        json={"discovery_capabilities": ["docker"]},
        headers=_PROBE_A_HEADERS,
    )
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={"discovery_capabilities": []},
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 200
    await db_session.refresh(probe_a)
    assert probe_a.discovery_capabilities == []


@pytest.mark.asyncio
async def test_probe_out_exposes_discovery_capabilities(
    client: AsyncClient, admin_token: str, probe_a: Probe
) -> None:
    await client.post(
        "/api/v1/probes/heartbeat",
        json={"discovery_capabilities": ["docker"]},
        headers=_PROBE_A_HEADERS,
    )
    resp = await client.get(f"/api/v1/probes/{probe_a.id}", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["discovery_capabilities"] == ["docker"]


# ── POST /probes/discovery — accept + upsert ─────────────────────────────────


@pytest.mark.asyncio
async def test_push_discovery_accepted_and_stored(
    client: AsyncClient, db_session: AsyncSession, source_on_a: DiscoverySource
) -> None:
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source_on_a.id), "services": _services_payload(2)},
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 2}

    rows = (
        (
            await db_session.execute(
                select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.status for r in rows} == {"proposed"}


@pytest.mark.asyncio
async def test_push_discovery_upsert_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, source_on_a: DiscoverySource
) -> None:
    first = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source_on_a.id), "services": _services_payload(1)},
        headers=_PROBE_A_HEADERS,
    )
    assert first.status_code == 202

    rows = (
        (
            await db_session.execute(
                select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    first_last_seen = rows[0].last_seen_at

    second = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source_on_a.id),
            "services": [
                {"host": "10.0.0.1", "port": 80, "proto": "tcp", "hints": {"image": "nginx"}}
            ],
        },
        headers=_PROBE_A_HEADERS,
    )
    assert second.status_code == 202

    rows = (
        (
            await db_session.execute(
                select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
            )
        )
        .scalars()
        .all()
    )
    # Still exactly one row — same (source_id, normalized_target). SQLite
    # round-trips datetimes as naive, so strip tzinfo before comparing (the
    # column itself is `timezone=True` on PostgreSQL).
    assert len(rows) == 1

    def _naive(dt):
        return dt.replace(tzinfo=None) if dt.tzinfo else dt

    assert _naive(rows[0].last_seen_at) >= _naive(first_last_seen)
    assert rows[0].hints == {"image": "nginx"}


@pytest.mark.asyncio
async def test_push_discovery_never_overwrites_dismissed_status(
    client: AsyncClient, db_session: AsyncSession, source_on_a: DiscoverySource
) -> None:
    now = datetime.now(UTC)
    dismissed = DiscoveredService(
        source_id=source_on_a.id,
        host="10.0.0.1",
        port=80,
        proto="tcp",
        normalized_target="tcp://10.0.0.1:80",
        status="dismissed",
        first_seen_at=now,
        last_seen_at=now,
        status_changed_at=now,
    )
    db_session.add(dismissed)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source_on_a.id),
            "services": [{"host": "10.0.0.1", "port": 80, "proto": "tcp", "hints": {}}],
        },
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202

    await db_session.refresh(dismissed)
    assert dismissed.status == "dismissed"


@pytest.mark.asyncio
async def test_push_discovery_recomputes_normalized_target_server_side(
    client: AsyncClient, db_session: AsyncSession, source_on_a: DiscoverySource
) -> None:
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source_on_a.id),
            "services": [{"host": "MyHost.Example", "port": 80, "proto": "TCP", "hints": {}}],
        },
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202

    row = (
        await db_session.execute(
            select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
        )
    ).scalar_one()
    assert row.host == "myhost.example"
    assert row.normalized_target == "tcp://myhost.example:80"


@pytest.mark.asyncio
async def test_push_discovery_no_port_normalized_without_colon(
    client: AsyncClient, db_session: AsyncSession, source_on_a: DiscoverySource
) -> None:
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source_on_a.id),
            "services": [{"host": "10.0.0.9", "port": None, "proto": "docker", "hints": {}}],
        },
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202
    row = (
        await db_session.execute(
            select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
        )
    ).scalar_one()
    assert row.normalized_target == "docker://10.0.0.9"


# ── POST /probes/discovery — bounds ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_push_discovery_over_500_services_rejected(
    client: AsyncClient, source_on_a: DiscoverySource
) -> None:
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source_on_a.id), "services": _services_payload(501)},
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_push_discovery_hints_truncated_server_side(
    client: AsyncClient, db_session: AsyncSession, source_on_a: DiscoverySource
) -> None:
    oversized_hints = {f"key{i}": "x" * 400 for i in range(40)}
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source_on_a.id),
            "services": [
                {"host": "10.0.0.1", "port": 80, "proto": "tcp", "hints": oversized_hints}
            ],
        },
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202

    row = (
        await db_session.execute(
            select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
        )
    ).scalar_one()
    assert len(row.hints) == 32
    assert all(len(v) == 256 for v in row.hints.values())


@pytest.mark.asyncio
async def test_push_discovery_oversized_nested_hint_dropped(
    client: AsyncClient, db_session: AsyncSession, source_on_a: DiscoverySource
) -> None:
    """A non-string hint value can't be truncated without corrupting it — an
    oversized one (nested blob > 8 KB serialized) is dropped outright, while a
    legitimate probe-side labels dict passes through untouched."""
    labels = {"com.example.role": "web", "com.example.env": "prod"}
    hints = {
        "labels": labels,
        "huge_nested": {"payload": "x" * 20_000},
    }
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source_on_a.id),
            "services": [{"host": "10.0.0.1", "port": 80, "proto": "tcp", "hints": hints}],
        },
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202

    row = (
        await db_session.execute(
            select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
        )
    ).scalar_one()
    assert row.hints == {"labels": labels}


@pytest.mark.asyncio
async def test_push_discovery_duplicate_targets_in_one_payload(
    client: AsyncClient, db_session: AsyncSession, source_on_a: DiscoverySource
) -> None:
    """Two entries normalizing to the same target ("HOST" vs "host") must not
    trip uq_discovered_services_source_target into a 500 — first one wins."""
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source_on_a.id),
            "services": [
                {"host": "10.0.0.1", "port": 80, "proto": "tcp", "hints": {"first": "yes"}},
                {"host": "10.0.0.1", "port": 80, "proto": "TCP", "hints": {"first": "no"}},
            ],
        },
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1}

    row = (
        await db_session.execute(
            select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
        )
    ).scalar_one()
    assert row.hints == {"first": "yes"}


# ── POST /probes/discovery — scope-binding (no oracle) ───────────────────────


@pytest.mark.asyncio
async def test_push_discovery_unknown_source_same_response_as_accept(
    client: AsyncClient, db_session: AsyncSession, probe_a: Probe
) -> None:
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(uuid.uuid4()), "services": _services_payload(1)},
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0}


@pytest.mark.asyncio
async def test_push_discovery_disabled_source_rejected_same_shape(
    client: AsyncClient, db_session: AsyncSession, regular_user: User, probe_a: Probe
) -> None:
    disabled = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=probe_a.id,
        source_type="docker",
        params={},
        enabled=False,
    )
    db_session.add(disabled)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(disabled.id), "services": _services_payload(1)},
        headers=_PROBE_A_HEADERS,
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0}

    rows = (
        (
            await db_session.execute(
                select(DiscoveredService).where(DiscoveredService.source_id == disabled.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_push_discovery_other_probes_source_rejected_same_shape(
    client: AsyncClient, db_session: AsyncSession, probe_b: Probe, source_on_a: DiscoverySource
) -> None:
    """`source_on_a` belongs to probe A — probe B pushing to it is rejected."""
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source_on_a.id), "services": _services_payload(1)},
        headers=_PROBE_B_HEADERS,
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0}

    rows = (
        (
            await db_session.execute(
                select(DiscoveredService).where(DiscoveredService.source_id == source_on_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_push_discovery_requires_probe_auth(client: AsyncClient, source_on_a) -> None:
    resp = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source_on_a.id), "services": []},
        headers={"X-Probe-Api-Key": "wiu_totally_invalid_key_xxx"},
    )
    assert resp.status_code == 401
