"""Discovery sources + discovered services — model, CRUD, scoping (plan D, D-0).

Coverage mirrors what the module docstring in ``api/v1/discovery.py`` calls
out as load-bearing: owner/team scoping identical to ``oncall.py``, per-type
``params`` validation (bounded CIDR, bounded port list), the
``proposed -> accepted | dismissed`` state machine (with ``orphaned`` as an
alternate entry point and no transition out of a terminal state), the
``(source_id, normalized_target)`` uniqueness that the D-1 snapshot diff will
rely on, and that every mutation leaves an audit trail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.audit_log import AuditLog
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.team import Team, TeamMembership, TeamRole
from whatisup.models.user import User

TEST_PASSWORD = "TestPassword123!"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _audit_entries(db: AsyncSession, action: str) -> list[AuditLog]:
    rows = await db.execute(select(AuditLog).where(AuditLog.action == action))
    return list(rows.scalars().all())


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    """A second non-admin user sharing no team with `regular_user`."""
    u = User(
        email="d-stranger@test.com",
        username="d-stranger",
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def stranger_token(client: AsyncClient, stranger: User) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": stranger.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _register_probe(
    client: AsyncClient,
    admin_token: str,
    name: str = "probe-d0",
    *,
    visible_to: list[str] | None = None,
) -> str:
    """Register a probe and make it visible to the test's non-admin users.

    Targeting a probe with a discovery source requires the same visibility
    ``GET /probes/`` enforces (``assert_can_use_probe``): membership in a group
    the user can reach — a probe in no group is invisible to every regular
    user, in the API exactly as in the UI's probe picker. These tests are about
    params validation, source scoping and audit, not about probe tenancy (that
    lives in ``test_discovery_probe_group.py``), so by default the probe is
    granted to every non-superadmin user through a throwaway group. Pass
    ``visible_to=[]`` for the tenancy case itself.
    """
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": name, "location_name": "Paris"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    probe_id = resp.json()["id"]

    if visible_to is None:
        users = await client.get("/api/v1/admin/users", headers=_auth(admin_token))
        assert users.status_code == 200, users.text
        visible_to = [u["id"] for u in users.json() if not u["is_superadmin"]]

    if visible_to:
        grp = await client.post(
            "/api/v1/admin/probe-groups",
            json={"name": f"grp-{probe_id[:8]}"},
            headers=_auth(admin_token),
        )
        assert grp.status_code == 201, grp.text
        group_id = grp.json()["id"]
        members = await client.post(
            f"/api/v1/admin/probe-groups/{group_id}/probes",
            json={"probe_ids": [probe_id]},
            headers=_auth(admin_token),
        )
        assert members.status_code == 200, members.text
        granted = await client.post(
            f"/api/v1/admin/probe-groups/{group_id}/users",
            json={"user_ids": visible_to},
            headers=_auth(admin_token),
        )
        assert granted.status_code == 200, granted.text

    return probe_id


async def _create_source(
    client: AsyncClient,
    token: str,
    probe_id: str,
    source_type: str = "docker",
    params: dict | None = None,
    team_id: str | None = None,
):
    body: dict = {"probe_id": probe_id, "source_type": source_type, "params": params or {}}
    if team_id is not None:
        body["team_id"] = team_id
    return await client.post("/api/v1/discovery/sources/", json=body, headers=_auth(token))


# ── DiscoverySource — params validation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_create_docker_source_no_params_required(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(client, user_token, probe_id, "docker")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_type"] == "docker"
    assert body["params"] == {}
    assert body["enabled"] is True


@pytest.mark.asyncio
async def test_create_port_scan_source_valid_params(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [22, 80, 443]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["params"]["cidr"] == "10.0.0.0/24"
    assert body["params"]["ports"] == [22, 80, 443]


@pytest.mark.asyncio
async def test_create_port_scan_rejects_cidr_larger_than_24(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "port_scan",
        params={"cidr": "10.0.0.0/16", "ports": [80]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_port_scan_rejects_empty_ports(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client, user_token, probe_id, "port_scan", params={"cidr": "10.0.0.0/24", "ports": []}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_port_scan_rejects_port_out_of_range(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [0, 70000]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_port_scan_rejects_too_many_ports(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "port_scan",
        params={"cidr": "10.0.0.0/24", "ports": list(range(1, 70))},  # 69 > cap of 64
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_dns_zone_source_valid_params(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "dns_zone",
        params={"zone": "example.com", "resolver": "203.0.113.10"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["params"]["zone"] == "example.com"
    assert body["params"]["resolver"] == "203.0.113.10"
    # Default record types when omitted.
    assert set(body["params"]["record_types"]) == {"A", "AAAA", "CNAME"}


@pytest.mark.asyncio
async def test_create_dns_zone_source_custom_record_types(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "dns_zone",
        params={"zone": "example.com", "resolver": "203.0.113.10", "record_types": ["A"]},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["params"]["record_types"] == ["A"]


@pytest.mark.asyncio
async def test_create_dns_zone_normalizes_zone_casing_and_trailing_dot(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "dns_zone",
        params={"zone": "Example.COM.", "resolver": "203.0.113.10"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["params"]["zone"] == "example.com"


@pytest.mark.asyncio
async def test_create_dns_zone_rejects_hostname_resolver(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    """The resolver must be an IP literal — a hostname resolver would let the
    actual nameserver be picked adversarially at run time (plan D, D-4)."""
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "dns_zone",
        params={"zone": "example.com", "resolver": "ns1.example.com"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_dns_zone_rejects_invalid_zone(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "dns_zone",
        params={"zone": "not a domain!", "resolver": "203.0.113.10"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_dns_zone_rejects_bare_label_zone(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    """A single label ("localhost") is not a zone anyone can transfer."""
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "dns_zone",
        params={"zone": "localhost", "resolver": "203.0.113.10"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_dns_zone_rejects_unknown_record_type(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client,
        user_token,
        probe_id,
        "dns_zone",
        params={"zone": "example.com", "resolver": "203.0.113.10", "record_types": ["MX"]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_dns_zone_missing_zone_rejected(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(
        client, user_token, probe_id, "dns_zone", params={"resolver": "203.0.113.10"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_source_unknown_type_rejected(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await _create_source(client, user_token, probe_id, "kubernetes")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_source_extra_field_rejected(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={"probe_id": probe_id, "source_type": "docker", "params": {}, "bogus": 1},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


# ── DiscoverySource — probe binding ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_source_unknown_probe_404(client: AsyncClient, user_token: str) -> None:
    resp = await _create_source(client, user_token, str(uuid.uuid4()), "docker")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_source_inactive_probe_rejected(
    client: AsyncClient, admin_token: str, user_token: str, db_session: AsyncSession
) -> None:
    probe_id = await _register_probe(client, admin_token, "probe-inactive")
    resp = await client.patch(
        f"/api/v1/probes/{probe_id}",
        json={"is_active": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200

    resp = await _create_source(client, user_token, probe_id, "docker")
    assert resp.status_code == 400


# ── DiscoverySource — scoping ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cannot_target_a_probe_the_user_cannot_see(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    """A probe-targeted source needs the same visibility as a group-targeted one.

    `Probe` has no owner: membership in a group reachable through
    `user_probe_group_access` is its only tenancy, and probe UUIDs leak
    legitimately through monitor results — so without this check, knowing a
    UUID was enough to make another tenant's probe run a `docker` inventory
    (or an outbound scan) and to read the result.
    """
    probe_id = await _register_probe(client, admin_token, "probe-foreign", visible_to=[])

    resp = await _create_source(client, user_token, probe_id, "docker")

    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_patch_cannot_retarget_onto_an_invisible_probe(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    """The PATCH branch enforces it too, not just create."""
    mine = await _register_probe(client, admin_token, "probe-mine")
    foreign = await _register_probe(client, admin_token, "probe-foreign-patch", visible_to=[])
    source_id = (await _create_source(client, user_token, mine, "docker")).json()["id"]

    resp = await client.patch(
        f"/api/v1/discovery/sources/{source_id}",
        json={"probe_id": foreign},
        headers=_auth(user_token),
    )

    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_superadmin_may_target_any_probe(client: AsyncClient, admin_token: str) -> None:
    """Superadmin is exempt here as everywhere else."""
    probe_id = await _register_probe(client, admin_token, "probe-no-group", visible_to=[])

    resp = await _create_source(client, admin_token, probe_id, "docker")

    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_stranger_cannot_see_or_modify_others_source(
    client: AsyncClient, admin_token: str, user_token: str, stranger_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    created = (await _create_source(client, user_token, probe_id, "docker")).json()
    source_id = created["id"]

    listing = (await client.get("/api/v1/discovery/sources/", headers=_auth(stranger_token))).json()
    assert all(s["id"] != source_id for s in listing)

    # check_resource_access (deps.py) answers 403 for an existing-but-inaccessible
    # resource, same as oncall.py's schedules/policies — not the bare 404 silences.py
    # uses for its owner-only (no team dimension) resource.
    assert (
        await client.get(f"/api/v1/discovery/sources/{source_id}", headers=_auth(stranger_token))
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/discovery/sources/{source_id}",
            json={"enabled": False},
            headers=_auth(stranger_token),
        )
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/discovery/sources/{source_id}", headers=_auth(stranger_token))
    ).status_code == 403


@pytest.mark.asyncio
async def test_team_member_can_see_team_source(
    client: AsyncClient, admin_token: str, user_token: str, stranger_token: str, stranger: User
) -> None:
    probe_id = await _register_probe(client, admin_token)
    team_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Discovery Team", "slug": "discovery-team"},
        headers=_auth(user_token),
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    add_resp = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(stranger.id), "role": "viewer"},
        headers=_auth(user_token),
    )
    assert add_resp.status_code == 201

    created = (await _create_source(client, user_token, probe_id, "docker", team_id=team_id)).json()
    source_id = created["id"]

    resp = await client.get(f"/api/v1/discovery/sources/{source_id}", headers=_auth(stranger_token))
    assert resp.status_code == 200

    # A viewer may read but not delete (delete requires admin+ role on the team).
    resp = await client.delete(
        f"/api/v1/discovery/sources/{source_id}", headers=_auth(stranger_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_source_with_foreign_team_id_rejected(
    client: AsyncClient, admin_token: str, user_token: str, db_session: AsyncSession
) -> None:
    """team_id of a team the caller is NOT a member of → 403 (mirrors alerts.py SEC-A3)."""
    probe_id = await _register_probe(client, admin_token)

    other_user = User(
        email="other-owner-d0@test.com",
        username="other-owner-d0",
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(other_user)
    await db_session.flush()
    other_team = Team(name="Other Discovery Team", slug="other-discovery-team")
    db_session.add(other_team)
    await db_session.flush()
    db_session.add(
        TeamMembership(user_id=other_user.id, team_id=other_team.id, role=TeamRole.owner)
    )
    await db_session.flush()

    resp = await _create_source(client, user_token, probe_id, "docker", team_id=str(other_team.id))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_bypasses_scoping(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    created = (await _create_source(client, user_token, probe_id, "docker")).json()
    resp = await client.get(
        f"/api/v1/discovery/sources/{created['id']}", headers=_auth(admin_token)
    )
    assert resp.status_code == 200


# ── DiscoverySource — update ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_source_params_revalidated_against_existing_type(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    created = (
        await _create_source(
            client,
            user_token,
            probe_id,
            "port_scan",
            params={"cidr": "10.0.0.0/24", "ports": [80]},
        )
    ).json()

    ok = await client.patch(
        f"/api/v1/discovery/sources/{created['id']}",
        json={"params": {"cidr": "10.0.1.0/24", "ports": [443]}},
        headers=_auth(user_token),
    )
    assert ok.status_code == 200
    assert ok.json()["params"]["cidr"] == "10.0.1.0/24"

    bad = await client.patch(
        f"/api/v1/discovery/sources/{created['id']}",
        json={"params": {"cidr": "10.0.0.0/8", "ports": [443]}},
        headers=_auth(user_token),
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_update_source_cannot_change_source_type(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token)
    created = (await _create_source(client, user_token, probe_id, "docker")).json()
    resp = await client.patch(
        f"/api/v1/discovery/sources/{created['id']}",
        json={"source_type": "port_scan"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


# ── Audit log ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_log_on_source_lifecycle(
    client: AsyncClient, admin_token: str, user_token: str, db_session: AsyncSession
) -> None:
    probe_id = await _register_probe(client, admin_token)
    created = (await _create_source(client, user_token, probe_id, "docker")).json()
    source_id = created["id"]

    assert len(await _audit_entries(db_session, "discovery_source.create")) >= 1

    await client.patch(
        f"/api/v1/discovery/sources/{source_id}",
        json={"enabled": False},
        headers=_auth(user_token),
    )
    assert len(await _audit_entries(db_session, "discovery_source.update")) >= 1

    await client.delete(f"/api/v1/discovery/sources/{source_id}", headers=_auth(user_token))
    assert len(await _audit_entries(db_session, "discovery_source.delete")) >= 1


# ── DiscoverySource — delete cascades services ────────────────────────────────


@pytest_asyncio.fixture
async def owned_source(
    db_session: AsyncSession, regular_user: User, admin_token: str, client: AsyncClient
) -> DiscoverySource:
    probe_id = await _register_probe(client, admin_token, "probe-owned-source")
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=uuid.UUID(probe_id),
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
    )
    db_session.add(source)
    await db_session.flush()
    return source


def _make_service(
    source: DiscoverySource,
    host: str = "10.0.0.5",
    port: int = 80,
    status_: str = "proposed",
) -> DiscoveredService:
    now = datetime.now(UTC)
    return DiscoveredService(
        source_id=source.id,
        host=host,
        port=port,
        proto="tcp",
        normalized_target=f"tcp://{host}:{port}",
        status=status_,
        first_seen_at=now,
        last_seen_at=now,
        status_changed_at=now,
    )


@pytest.mark.asyncio
async def test_delete_source_cascades_services(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    service_id = service.id

    resp = await client.delete(
        f"/api/v1/discovery/sources/{owned_source.id}", headers=_auth(user_token)
    )
    assert resp.status_code == 204

    remaining = (
        await db_session.execute(
            select(DiscoveredService).where(DiscoveredService.id == service_id)
        )
    ).scalar_one_or_none()
    assert remaining is None


# ── DiscoveredService — uniqueness ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unique_source_normalized_target(
    db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    db_session.add(_make_service(owned_source))
    await db_session.flush()

    db_session.add(_make_service(owned_source))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── DiscoveredService — state machine ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_accept_from_proposed(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept", headers=_auth(user_token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert len(await _audit_entries(db_session, "discovery_service.accept")) >= 1


@pytest.mark.asyncio
async def test_dismiss_from_proposed(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/dismiss", headers=_auth(user_token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"
    assert len(await _audit_entries(db_session, "discovery_service.dismiss")) >= 1


@pytest.mark.asyncio
async def test_accept_from_orphaned_ok(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source, status_="orphaned")
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept", headers=_auth(user_token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_dismiss_already_dismissed_rejected(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source, status_="dismissed")
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/dismiss", headers=_auth(user_token)
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_accept_already_accepted_rejected(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source, status_="accepted")
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept", headers=_auth(user_token)
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_stranger_cannot_accept_others_service(
    client: AsyncClient,
    stranger_token: str,
    db_session: AsyncSession,
    owned_source: DiscoverySource,
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept", headers=_auth(stranger_token)
    )
    assert resp.status_code == 403


# ── DiscoveredService — listing ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_services_filters_by_source_and_status(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    proposed = _make_service(owned_source, host="10.0.0.1")
    dismissed = _make_service(owned_source, host="10.0.0.2", status_="dismissed")
    db_session.add_all([proposed, dismissed])
    await db_session.flush()
    await db_session.commit()

    resp = await client.get(
        "/api/v1/discovery/services/",
        params={"source_id": str(owned_source.id), "status": "proposed"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["host"] == "10.0.0.1"


@pytest.mark.asyncio
async def test_list_services_scoped_to_owner(
    client: AsyncClient,
    stranger_token: str,
    db_session: AsyncSession,
    owned_source: DiscoverySource,
) -> None:
    db_session.add(_make_service(owned_source))
    await db_session.flush()
    await db_session.commit()

    resp = await client.get("/api/v1/discovery/services/", headers=_auth(stranger_token))
    assert resp.status_code == 200
    assert resp.json() == []

    # Even naming the source explicitly, a stranger is rejected (403, same as
    # the source endpoints) rather than getting an empty peek.
    resp = await client.get(
        "/api/v1/discovery/services/",
        params={"source_id": str(owned_source.id)},
        headers=_auth(stranger_token),
    )
    assert resp.status_code == 403
