"""Reconciliation + pre-filled proposals (plan D, D-2).

Coverage:

- matching: a discovered target already monitored by its owner/team is
  linked (`accepted` + `monitor_id`) instead of surfacing as a proposal, and
  never matches across tenants;
- idempotence: two identical pushes leave exactly the same rows/states, no
  duplicates;
- state transitions on disappearance/reappearance: `proposed` -> deleted,
  `accepted` -> `orphaned` -> `accepted`, `dismissed` untouched either way;
- `check_type` deduction from the observed port;
- accept() actually creating a `Monitor` through the CRUD path (audit log),
  applying overrides, and applying an `AlertMatrixTemplate` when asked;
- an already-linked (`orphaned`, matched) service re-affirms its link on
  accept without creating a second `Monitor`.
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
from sqlalchemy.orm import selectinload

from whatisup.core.security import hash_password
from whatisup.models.alert import AlertChannel, AlertChannelType, AlertRule
from whatisup.models.alert_matrix_template import AlertMatrixTemplate
from whatisup.models.audit_log import AuditLog
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.user import User
from whatisup.services.discovery import (
    deduce_check_type,
    default_monitor_fields,
    dismissal_fingerprint,
)

TEST_PASSWORD = "TestPassword123!"
_PROBE_KEY = "wiu_test_reconcile_probe_key"
_PROBE_HEADERS = {"X-Probe-Api-Key": _PROBE_KEY}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _hash(key: str) -> str:
    return bcrypt.hashpw(key.encode(), bcrypt.gensalt(rounds=4)).decode()


async def _audit_entries(db: AsyncSession, action: str) -> list[AuditLog]:
    rows = await db.execute(select(AuditLog).where(AuditLog.action == action))
    return list(rows.scalars().all())


@pytest_asyncio.fixture
async def probe(db_session: AsyncSession) -> Probe:
    p = Probe(name="reconcile-probe", location_name="Paris", api_key_hash=_hash(_PROBE_KEY))
    db_session.add(p)
    await db_session.flush()
    return p


@pytest_asyncio.fixture
async def source(db_session: AsyncSession, regular_user: User, probe: Probe) -> DiscoverySource:
    s = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=probe.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
        enabled=True,
    )
    db_session.add(s)
    await db_session.flush()
    await db_session.commit()
    return s


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    u = User(
        email="d2-stranger@test.com",
        username="d2-stranger",
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


async def _push(client: AsyncClient, source_id: uuid.UUID, services: list[dict]):
    return await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source_id), "services": services},
        headers=_PROBE_HEADERS,
    )


async def _services_of(db: AsyncSession, source_id: uuid.UUID) -> list[DiscoveredService]:
    rows = await db.execute(
        select(DiscoveredService).where(DiscoveredService.source_id == source_id)
    )
    return list(rows.scalars().all())


# ── Matching against existing monitors ───────────────────────────────────────


@pytest.mark.asyncio
async def test_matched_target_auto_accepted_not_proposed(
    client: AsyncClient, db_session: AsyncSession, regular_user: User, source: DiscoverySource
) -> None:
    monitor = Monitor(
        name="already-monitored",
        url="http://10.0.0.5",
        owner_id=regular_user.id,
        check_type="tcp",
        tcp_port=80,
    )
    db_session.add(monitor)
    await db_session.flush()
    await db_session.commit()

    resp = await _push(
        client, source.id, [{"host": "10.0.0.5", "port": 80, "proto": "tcp", "hints": {}}]
    )
    assert resp.status_code == 202

    rows = await _services_of(db_session, source.id)
    assert len(rows) == 1
    assert rows[0].status == "accepted"
    assert rows[0].monitor_id == monitor.id


@pytest.mark.asyncio
async def test_unmatched_target_stays_proposed(
    client: AsyncClient, db_session: AsyncSession, source: DiscoverySource
) -> None:
    resp = await _push(
        client, source.id, [{"host": "10.0.0.6", "port": 80, "proto": "tcp", "hints": {}}]
    )
    assert resp.status_code == 202

    rows = await _services_of(db_session, source.id)
    assert len(rows) == 1
    assert rows[0].status == "proposed"
    assert rows[0].monitor_id is None


@pytest.mark.asyncio
async def test_other_owners_monitor_never_matched(
    client: AsyncClient,
    db_session: AsyncSession,
    stranger: User,
    source: DiscoverySource,
) -> None:
    """`source` belongs to `regular_user` — a monitor owned by `stranger` at the
    exact same target must never be matched (cross-tenant leak)."""
    monitor = Monitor(
        name="strangers-monitor",
        url="http://10.0.0.7",
        owner_id=stranger.id,
        check_type="tcp",
        tcp_port=80,
    )
    db_session.add(monitor)
    await db_session.flush()
    await db_session.commit()

    resp = await _push(
        client, source.id, [{"host": "10.0.0.7", "port": 80, "proto": "tcp", "hints": {}}]
    )
    assert resp.status_code == 202

    rows = await _services_of(db_session, source.id)
    assert rows[0].status == "proposed"
    assert rows[0].monitor_id is None


@pytest.mark.asyncio
async def test_non_matchable_check_types_never_collide(
    client: AsyncClient, db_session: AsyncSession, regular_user: User, source: DiscoverySource
) -> None:
    """A `dns`/`ping`/`heartbeat` monitor has no real network target to match
    against — must never falsely claim a discovered port 80/443 service."""
    for check_type, url in (
        # Same host as the pushed target on purpose: without the exclusion,
        # falling through to the scheme's default port (80) would falsely
        # match it.
        ("dns", "http://10.0.0.8"),
        ("ping", "http://10.0.0.8"),
        ("heartbeat", ""),
    ):
        db_session.add(
            Monitor(
                name=f"non-matchable-{check_type}",
                url=url,
                owner_id=regular_user.id,
                check_type=check_type,
                heartbeat_slug=f"hb-{check_type}" if check_type == "heartbeat" else None,
                heartbeat_token="tok" if check_type == "heartbeat" else None,
            )
        )
    await db_session.flush()
    await db_session.commit()

    resp = await _push(
        client, source.id, [{"host": "10.0.0.8", "port": 80, "proto": "tcp", "hints": {}}]
    )
    assert resp.status_code == 202

    rows = await _services_of(db_session, source.id)
    assert rows[0].status == "proposed"
    assert rows[0].monitor_id is None


# ── Idempotence ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_double_push_idempotent(
    client: AsyncClient, db_session: AsyncSession, regular_user: User, source: DiscoverySource
) -> None:
    monitor = Monitor(
        name="idem-monitor",
        url="http://10.0.0.9",
        owner_id=regular_user.id,
        check_type="tcp",
        tcp_port=80,
    )
    db_session.add(monitor)
    await db_session.flush()
    await db_session.commit()

    services = [
        {"host": "10.0.0.9", "port": 80, "proto": "tcp", "hints": {}},
        {"host": "10.0.0.10", "port": 80, "proto": "tcp", "hints": {}},
    ]
    first = await _push(client, source.id, services)
    assert first.status_code == 202
    second = await _push(client, source.id, services)
    assert second.status_code == 202

    rows = await _services_of(db_session, source.id)
    assert len(rows) == 2
    by_target = {r.normalized_target: r for r in rows}
    assert by_target["tcp://10.0.0.9:80"].status == "accepted"
    assert by_target["tcp://10.0.0.9:80"].monitor_id == monitor.id
    assert by_target["tcp://10.0.0.10:80"].status == "proposed"


# ── Disappearance / reappearance ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proposed_service_deleted_when_missing_from_snapshot(
    client: AsyncClient, db_session: AsyncSession, source: DiscoverySource
) -> None:
    first = await _push(
        client,
        source.id,
        [
            {"host": "10.0.0.20", "port": 80, "proto": "tcp", "hints": {}},
            {"host": "10.0.0.21", "port": 80, "proto": "tcp", "hints": {}},
        ],
    )
    assert first.status_code == 202
    assert len(await _services_of(db_session, source.id)) == 2

    # Next snapshot only reports .21 — .20 vanished and was never acted on.
    second = await _push(
        client, source.id, [{"host": "10.0.0.21", "port": 80, "proto": "tcp", "hints": {}}]
    )
    assert second.status_code == 202

    rows = await _services_of(db_session, source.id)
    assert {r.host for r in rows} == {"10.0.0.21"}


@pytest.mark.asyncio
async def test_accepted_service_orphaned_then_reaccepted_on_reappearance(
    client: AsyncClient, db_session: AsyncSession, regular_user: User, source: DiscoverySource
) -> None:
    monitor = Monitor(
        name="flaky-monitor",
        url="http://10.0.0.30",
        owner_id=regular_user.id,
        check_type="tcp",
        tcp_port=80,
    )
    db_session.add(monitor)
    await db_session.flush()
    now = datetime.now(UTC)
    service = DiscoveredService(
        source_id=source.id,
        monitor_id=monitor.id,
        host="10.0.0.30",
        port=80,
        proto="tcp",
        normalized_target="tcp://10.0.0.30:80",
        status="accepted",
        first_seen_at=now,
        last_seen_at=now,
        status_changed_at=now,
    )
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    # Snapshot without the target: monitor is still real, so it orphans
    # rather than disappearing.
    empty_push = await _push(client, source.id, [])
    assert empty_push.status_code == 202
    await db_session.refresh(service)
    assert service.status == "orphaned"
    assert service.monitor_id == monitor.id

    # Target comes back — flips back to accepted, same monitor link.
    reappear_push = await _push(
        client, source.id, [{"host": "10.0.0.30", "port": 80, "proto": "tcp", "hints": {}}]
    )
    assert reappear_push.status_code == 202
    await db_session.refresh(service)
    assert service.status == "accepted"
    assert service.monitor_id == monitor.id


@pytest.mark.asyncio
async def test_dismissed_survives_disappearance_and_reappearance(
    client: AsyncClient, db_session: AsyncSession, source: DiscoverySource
) -> None:
    now = datetime.now(UTC)
    service = DiscoveredService(
        source_id=source.id,
        host="10.0.0.40",
        port=80,
        proto="tcp",
        normalized_target="tcp://10.0.0.40:80",
        status="dismissed",
        first_seen_at=now,
        last_seen_at=now,
        status_changed_at=now,
    )
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    empty_push = await _push(client, source.id, [])
    assert empty_push.status_code == 202
    await db_session.refresh(service)
    assert service.status == "dismissed"

    reappear_push = await _push(
        client, source.id, [{"host": "10.0.0.40", "port": 80, "proto": "tcp", "hints": {}}]
    )
    assert reappear_push.status_code == 202
    await db_session.refresh(service)
    assert service.status == "dismissed"


# ── Dismissed drift re-proposition (plan D, D-4) ─────────────────────────────


@pytest.mark.asyncio
async def test_dismissed_fingerprint_unchanged_keeps_dismissed(
    client: AsyncClient, user_token: str, db_session: AsyncSession, source: DiscoverySource
) -> None:
    hints = {"image": "nginx:1.25", "container_name": "web-1"}
    push = await _push(
        client, source.id, [{"host": "10.0.0.50", "port": 8080, "proto": "tcp", "hints": hints}]
    )
    assert push.status_code == 202
    service = (await _services_of(db_session, source.id))[0]

    dismiss = await client.post(
        f"/api/v1/discovery/services/{service.id}/dismiss",
        json={"reason": "decommissioned"},
        headers=_auth(user_token),
    )
    assert dismiss.status_code == 200
    assert dismiss.json()["dismissed_fingerprint"] is not None

    # Re-push with the exact same stable hints — the refusal must hold.
    second = await _push(
        client, source.id, [{"host": "10.0.0.50", "port": 8080, "proto": "tcp", "hints": hints}]
    )
    assert second.status_code == 202
    await db_session.refresh(service)
    assert service.status == "dismissed"
    assert service.dismissed_reason == "decommissioned"


@pytest.mark.asyncio
async def test_dismissed_reopens_when_image_changes(
    client: AsyncClient, user_token: str, db_session: AsyncSession, source: DiscoverySource
) -> None:
    push = await _push(
        client,
        source.id,
        [{"host": "10.0.0.51", "port": 8080, "proto": "tcp", "hints": {"image": "nginx:1.25"}}],
    )
    assert push.status_code == 202
    service = (await _services_of(db_session, source.id))[0]

    dismiss = await client.post(
        f"/api/v1/discovery/services/{service.id}/dismiss",
        json={"reason": "not needed"},
        headers=_auth(user_token),
    )
    assert dismiss.status_code == 200

    # Same target, different image — a redeploy changed what's actually there.
    second = await _push(
        client,
        source.id,
        [{"host": "10.0.0.51", "port": 8080, "proto": "tcp", "hints": {"image": "postgres:16"}}],
    )
    assert second.status_code == 202
    await db_session.refresh(service)
    assert service.status == "proposed"
    assert service.dismissed_reason is None
    assert service.dismissed_fingerprint is None


@pytest.mark.asyncio
async def test_dismissed_ignores_volatile_hint_drift(
    client: AsyncClient, user_token: str, db_session: AsyncSession, source: DiscoverySource
) -> None:
    """`http_status` is not in the stable fingerprint subset — it churns on
    its own and must never reopen a dismissed service by itself."""
    push = await _push(
        client,
        source.id,
        [
            {
                "host": "10.0.0.52",
                "port": 8080,
                "proto": "tcp",
                "hints": {"image": "nginx:1.25", "http_status": 200},
            }
        ],
    )
    assert push.status_code == 202
    service = (await _services_of(db_session, source.id))[0]

    dismiss = await client.post(
        f"/api/v1/discovery/services/{service.id}/dismiss", headers=_auth(user_token)
    )
    assert dismiss.status_code == 200

    second = await _push(
        client,
        source.id,
        [
            {
                "host": "10.0.0.52",
                "port": 8080,
                "proto": "tcp",
                "hints": {"image": "nginx:1.25", "http_status": 500},
            }
        ],
    )
    assert second.status_code == 202
    await db_session.refresh(service)
    assert service.status == "dismissed"


@pytest.mark.asyncio
async def test_dismissed_pre_d4_never_reopened(
    client: AsyncClient, db_session: AsyncSession, source: DiscoverySource
) -> None:
    """A row dismissed before this column existed has `dismissed_fingerprint`
    NULL — the reconciler must never re-propose it based on a baseline that
    was never actually captured."""
    now = datetime.now(UTC)
    service = DiscoveredService(
        source_id=source.id,
        host="10.0.0.53",
        port=8080,
        proto="tcp",
        normalized_target="tcp://10.0.0.53:8080",
        status="dismissed",
        hints={"image": "nginx:1.25"},
        dismissed_fingerprint=None,
        first_seen_at=now,
        last_seen_at=now,
        status_changed_at=now,
    )
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    push = await _push(
        client,
        source.id,
        [{"host": "10.0.0.53", "port": 8080, "proto": "tcp", "hints": {"image": "postgres:16"}}],
    )
    assert push.status_code == 202
    await db_session.refresh(service)
    assert service.status == "dismissed"


# ── check_type deduction ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("port", "proto", "expected"),
    [
        (80, "tcp", "http"),
        (443, "tcp", "http"),
        (8080, "tcp", "http"),
        (25, "tcp", "smtp"),
        (465, "tcp", "smtp"),
        (587, "tcp", "smtp"),
        (53, "tcp", "dns"),
        (53, "udp", "dns"),
        (5432, "tcp", "tcp"),
        (6379, "tcp", "tcp"),
        (22, "tcp", "tcp"),
        (161, "udp", "udp"),
        (None, "tcp", "tcp"),
    ],
)
def test_deduce_check_type(port: int | None, proto: str, expected: str) -> None:
    assert deduce_check_type(port, proto) == expected


# ── dismissal_fingerprint (plan D, D-4) ──────────────────────────────────────


def test_dismissal_fingerprint_stable_across_key_order() -> None:
    a = dismissal_fingerprint({"image": "nginx:1.25", "container_name": "web-1"})
    b = dismissal_fingerprint({"container_name": "web-1", "image": "nginx:1.25"})
    assert a == b


def test_dismissal_fingerprint_changes_with_stable_key() -> None:
    a = dismissal_fingerprint({"image": "nginx:1.25"})
    b = dismissal_fingerprint({"image": "postgres:16"})
    assert a != b


def test_dismissal_fingerprint_ignores_non_stable_keys() -> None:
    a = dismissal_fingerprint({"image": "nginx:1.25", "http_status": 200, "labels": {"x": "y"}})
    b = dismissal_fingerprint({"image": "nginx:1.25", "http_status": 500, "labels": {}})
    assert a == b


def test_dismissal_fingerprint_of_empty_hints_is_deterministic() -> None:
    """`port_scan` never reports any of the stable keys — its dismissals
    always hash the same empty subset, which is the correct behaviour (no
    baseline ever drifts) rather than an error case."""
    assert dismissal_fingerprint({}) == dismissal_fingerprint({})
    assert dismissal_fingerprint({}) == dismissal_fingerprint({"http_status": 200})


# ── accept() creates a Monitor via the CRUD path ─────────────────────────────


@pytest_asyncio.fixture
async def owned_source(
    db_session: AsyncSession, regular_user: User, probe: Probe
) -> DiscoverySource:
    s = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=probe.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
    )
    db_session.add(s)
    await db_session.flush()
    return s


def _make_service(
    source: DiscoverySource,
    host: str = "10.0.0.50",
    port: int | None = 80,
    proto: str = "tcp",
    status_: str = "proposed",
    hints: dict | None = None,
    monitor_id: uuid.UUID | None = None,
) -> DiscoveredService:
    now = datetime.now(UTC)
    target = f"{proto}://{host}:{port}" if port is not None else f"{proto}://{host}"
    return DiscoveredService(
        source_id=source.id,
        monitor_id=monitor_id,
        host=host,
        port=port,
        proto=proto,
        normalized_target=target,
        hints=hints or {},
        status=status_,
        first_seen_at=now,
        last_seen_at=now,
        status_changed_at=now,
    )


@pytest.mark.asyncio
async def test_accept_creates_monitor_with_deduced_check_type(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source, host="10.0.0.51", port=443, proto="tcp")
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept", headers=_auth(user_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["monitor_id"] is not None

    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.id == uuid.UUID(body["monitor_id"])))
    ).scalar_one()
    assert monitor.check_type == "http"
    assert monitor.url.startswith("https://")
    assert len(await _audit_entries(db_session, "monitor.create")) >= 1


@pytest.mark.asyncio
async def test_accept_applies_caller_overrides(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source, host="10.0.0.52", port=80)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept",
        json={"name": "custom-name", "check_type": "tcp", "interval_seconds": 120},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.id == uuid.UUID(body["monitor_id"])))
    ).scalar_one()
    assert monitor.name == "custom-name"
    assert monitor.check_type == "tcp"
    assert monitor.tcp_port == 80
    assert monitor.interval_seconds == 120


@pytest.mark.asyncio
async def test_accept_forbidden_without_can_create_monitors(
    client: AsyncClient,
    user_token: str,
    db_session: AsyncSession,
    regular_user: User,
    owned_source: DiscoverySource,
) -> None:
    regular_user.can_create_monitors = False
    await db_session.flush()

    service = _make_service(owned_source, host="10.0.0.53")
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept", headers=_auth(user_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_accept_already_linked_service_reaffirms_without_new_monitor(
    client: AsyncClient,
    user_token: str,
    db_session: AsyncSession,
    regular_user: User,
    owned_source: DiscoverySource,
) -> None:
    monitor = Monitor(
        name="preexisting",
        url="http://10.0.0.54",
        owner_id=regular_user.id,
        check_type="tcp",
        tcp_port=80,
    )
    db_session.add(monitor)
    await db_session.flush()

    service = _make_service(
        owned_source, host="10.0.0.54", status_="orphaned", monitor_id=monitor.id
    )
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    monitors_before = (await db_session.execute(select(Monitor))).scalars().all()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept", headers=_auth(user_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["monitor_id"] == str(monitor.id)

    monitors_after = (await db_session.execute(select(Monitor))).scalars().all()
    assert len(monitors_after) == len(monitors_before)


# ── Prefilled proposal on list ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_services_exposes_suggested_fields(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(
        owned_source,
        host="10.0.0.60",
        port=443,
        hints={
            "container_name": "web-1",
            "labels": {
                "com.docker.compose.project": "shop",
                "com.docker.compose.service": "web",
            },
        },
    )
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.get(
        "/api/v1/discovery/services/",
        params={"source_id": str(owned_source.id)},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["suggested_check_type"] == "http"
    assert body["suggested_name"] == "web-1"
    assert body["suggested_group"] == "shop"
    assert "web" in body["suggested_tags"]
    assert any(t.startswith("discovery:") for t in body["suggested_tags"])


# ── AlertMatrixTemplate application on accept ─────────────────────────────────


@pytest.mark.asyncio
async def test_accept_applies_alert_matrix_template(
    client: AsyncClient,
    user_token: str,
    db_session: AsyncSession,
    regular_user: User,
    owned_source: DiscoverySource,
) -> None:
    channel = AlertChannel(
        owner_id=regular_user.id,
        name="ops-email",
        type=AlertChannelType.email,
        config={"to": "ops@example.com"},
    )
    db_session.add(channel)
    template = AlertMatrixTemplate(
        name="standard",
        check_type="http",
        rows=[{"condition": "any_down", "min_duration_seconds": 30}],
        is_system=True,
    )
    db_session.add(template)
    await db_session.flush()

    service = _make_service(owned_source, host="10.0.0.61", port=80)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept",
        json={
            "alert_matrix_template_id": str(template.id),
            "alert_channel_ids": [str(channel.id)],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    monitor_id = uuid.UUID(body["monitor_id"])

    rules = (
        (
            await db_session.execute(
                select(AlertRule)
                .where(AlertRule.monitor_id == monitor_id)
                .options(selectinload(AlertRule.channels))
            )
        )
        .scalars()
        .all()
    )
    assert len(rules) == 1
    assert rules[0].condition == "any_down"
    assert rules[0].min_duration_seconds == 30
    assert [c.id for c in rules[0].channels] == [channel.id]


# ── default_monitor_fields ────────────────────────────────────────────────────


def test_default_monitor_fields_tcp_port_field() -> None:
    class _FakeSource:
        source_type = "port_scan"
        team_id = None

    service = DiscoveredService(
        host="10.0.0.70",
        port=5432,
        proto="tcp",
        normalized_target="tcp://10.0.0.70:5432",
        hints={},
    )
    fields = default_monitor_fields(service, _FakeSource())
    assert fields["check_type"] == "tcp"
    assert fields["tcp_port"] == 5432
    assert fields["url"] == "http://10.0.0.70"


def test_default_monitor_fields_https_port() -> None:
    class _FakeSource:
        source_type = "docker"
        team_id = None

    service = DiscoveredService(
        host="10.0.0.71",
        port=443,
        proto="tcp",
        normalized_target="tcp://10.0.0.71:443",
        hints={},
    )
    fields = default_monitor_fields(service, _FakeSource())
    assert fields["check_type"] == "http"
    assert fields["url"] == "https://10.0.0.71"
