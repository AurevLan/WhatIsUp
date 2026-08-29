"""Discovery sources targeting a ProbeGroup (plan E, E-2).

Covers what the plan calls out as load-bearing: distribution by source_type
(docker fan-out to every capable member vs. port_scan/dns_zone to the sticky
elected member only), the push-scope check extended to group membership
(``_probe_may_push``), initial election + re-election on a dead/removed
probe (``services/discovery_election.py``), the fail-visible capacity gate
at creation, cross-tenant refusal via ``user_probe_group_access``, and the
DB-level exclusivity/elected-requires-group CHECK constraints.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.discovery import DiscoverySource
from whatisup.models.probe import Probe
from whatisup.models.probe_group import ProbeGroup, probe_group_members, user_probe_group_access
from whatisup.models.user import User
from whatisup.services.discovery_election import run_discovery_elections

_PROBE_A_KEY = "wiu_group_probe_a_key"
_PROBE_B_KEY = "wiu_group_probe_b_key"
_PROBE_C_KEY = "wiu_group_probe_c_key"
_PROBE_OUTSIDER_KEY = "wiu_group_probe_outsider_key"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _hash(key: str) -> str:
    # Low-cost hash — bcrypt rounds=4 keeps tests fast (mirrors test_discovery_ingest.py).
    return bcrypt.hashpw(key.encode(), bcrypt.gensalt(rounds=4)).decode()


async def _register_probe(client: AsyncClient, admin_token: str, name: str) -> str:
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": name, "location_name": "Paris"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def group_probe_a(db_session: AsyncSession) -> Probe:
    """Declares docker + port_scan, alive."""
    probe = Probe(
        name="group-probe-a",
        location_name="A",
        api_key_hash=_hash(_PROBE_A_KEY),
        discovery_capabilities=["docker", "port_scan"],
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest_asyncio.fixture
async def group_probe_b(db_session: AsyncSession) -> Probe:
    """Declares docker only, alive."""
    probe = Probe(
        name="group-probe-b",
        location_name="B",
        api_key_hash=_hash(_PROBE_B_KEY),
        discovery_capabilities=["docker"],
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest_asyncio.fixture
async def group_probe_c(db_session: AsyncSession) -> Probe:
    """Declares port_scan only, alive — the second electable candidate."""
    probe = Probe(
        name="group-probe-c",
        location_name="C",
        api_key_hash=_hash(_PROBE_C_KEY),
        discovery_capabilities=["port_scan"],
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest_asyncio.fixture
async def probe_group(
    db_session: AsyncSession, group_probe_a: Probe, group_probe_b: Probe, group_probe_c: Probe
) -> ProbeGroup:
    group = ProbeGroup(name="target-group")
    db_session.add(group)
    await db_session.flush()
    for probe in (group_probe_a, group_probe_b, group_probe_c):
        await db_session.execute(
            insert(probe_group_members).values(probe_group_id=group.id, probe_id=probe.id)
        )
    await db_session.commit()
    return group


@pytest_asyncio.fixture
async def group_visible(
    db_session: AsyncSession, probe_group: ProbeGroup, regular_user: User
) -> ProbeGroup:
    """`probe_group`, granted to `regular_user` via `user_probe_group_access`."""
    await db_session.execute(
        insert(user_probe_group_access).values(
            user_id=regular_user.id, probe_group_id=probe_group.id
        )
    )
    await db_session.commit()
    return probe_group


# ── Create — capacity gate + tenancy ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_group_source_success(
    client: AsyncClient, user_token: str, group_visible: ProbeGroup
) -> None:
    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={"probe_group_id": str(group_visible.id), "source_type": "docker", "params": {}},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["probe_group_id"] == str(group_visible.id)
    assert body["probe_id"] is None
    assert body["group_capable_probe_count"] == 2  # group_probe_a + group_probe_b


@pytest.mark.asyncio
async def test_create_group_source_refused_without_capable_probe(
    client: AsyncClient, user_token: str, db_session: AsyncSession, regular_user: User
) -> None:
    probe = Probe(name="capless-probe", location_name="X", api_key_hash=_hash("wiu_capless_key"))
    db_session.add(probe)
    await db_session.flush()
    group = ProbeGroup(name="capless-group")
    db_session.add(group)
    await db_session.flush()
    await db_session.execute(
        insert(probe_group_members).values(probe_group_id=group.id, probe_id=probe.id)
    )
    await db_session.execute(
        insert(user_probe_group_access).values(user_id=regular_user.id, probe_group_id=group.id)
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={"probe_group_id": str(group.id), "source_type": "docker", "params": {}},
        headers=_auth(user_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_group_source_cross_tenant_refused(
    client: AsyncClient, user_token: str, probe_group: ProbeGroup
) -> None:
    """`probe_group` exists but was never granted to `regular_user`."""
    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={"probe_group_id": str(probe_group.id), "source_type": "docker", "params": {}},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_group_source_unknown_group_404(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={"probe_group_id": str(uuid.uuid4()), "source_type": "docker", "params": {}},
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_group_source_superadmin_bypasses_tenancy(
    client: AsyncClient, admin_token: str, probe_group: ProbeGroup
) -> None:
    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={"probe_group_id": str(probe_group.id), "source_type": "docker", "params": {}},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_create_source_both_targets_rejected(
    client: AsyncClient, user_token: str, admin_token: str
) -> None:
    probe_id = await _register_probe(client, admin_token, "solo-probe-both")
    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={
            "probe_id": probe_id,
            "probe_group_id": str(uuid.uuid4()),
            "source_type": "docker",
            "params": {},
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_source_no_target_rejected(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={"source_type": "docker", "params": {}},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


# ── Capacity gate is fail-visible, not just fail-closed ──────────────────────


@pytest.mark.asyncio
async def test_group_capable_probe_count_drops_after_probes_removed(
    client: AsyncClient,
    user_token: str,
    db_session: AsyncSession,
    group_visible: ProbeGroup,
    group_probe_a: Probe,
    group_probe_b: Probe,
) -> None:
    created = (
        await client.post(
            "/api/v1/discovery/sources/",
            json={"probe_group_id": str(group_visible.id), "source_type": "docker", "params": {}},
            headers=_auth(user_token),
        )
    ).json()
    assert created["group_capable_probe_count"] == 2

    # Both docker-capable members leave the group — the docker source can no
    # longer run anywhere, and a GET must say so rather than staying silent.
    group_visible.probes = [
        p for p in group_visible.probes if p.id not in {group_probe_a.id, group_probe_b.id}
    ]
    await db_session.flush()
    await db_session.commit()

    resp = await client.get(f"/api/v1/discovery/sources/{created['id']}", headers=_auth(user_token))
    assert resp.status_code == 200
    assert resp.json()["group_capable_probe_count"] == 0


# ── GET /discovery/probe-groups/ ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_probe_groups_only_shows_visible(
    client: AsyncClient, user_token: str, db_session: AsyncSession, group_visible: ProbeGroup
) -> None:
    hidden = ProbeGroup(name="hidden-group")
    db_session.add(hidden)
    await db_session.flush()
    await db_session.commit()

    resp = await client.get("/api/v1/discovery/probe-groups/", headers=_auth(user_token))
    assert resp.status_code == 200
    names = {g["name"] for g in resp.json()}
    assert group_visible.name in names
    assert "hidden-group" not in names


@pytest.mark.asyncio
async def test_list_probe_groups_superadmin_sees_all(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    group = ProbeGroup(name="admin-only-visible-group")
    db_session.add(group)
    await db_session.flush()
    await db_session.commit()

    resp = await client.get("/api/v1/discovery/probe-groups/", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert "admin-only-visible-group" in {g["name"] for g in resp.json()}


@pytest.mark.asyncio
async def test_list_probe_groups_exposes_capability_union_and_count(
    client: AsyncClient, user_token: str, group_visible: ProbeGroup
) -> None:
    resp = await client.get("/api/v1/discovery/probe-groups/", headers=_auth(user_token))
    row = next(g for g in resp.json() if g["id"] == str(group_visible.id))
    assert set(row["capabilities"]) == {"docker", "port_scan"}
    assert row["probe_count"] == 3


# ── Heartbeat distribution: docker fan-out vs. elected-only ──────────────────


@pytest.mark.asyncio
async def test_group_docker_source_fans_out_to_every_capable_member(
    client: AsyncClient,
    db_session: AsyncSession,
    regular_user: User,
    group_probe_a: Probe,
    group_probe_b: Probe,
    group_probe_c: Probe,
    probe_group: ProbeGroup,
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id, probe_group_id=probe_group.id, source_type="docker", params={}
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    resp_a = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": _PROBE_A_KEY}
    )
    resp_b = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": _PROBE_B_KEY}
    )
    resp_c = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": _PROBE_C_KEY}
    )

    assert {s["id"] for s in resp_a.json()["discovery_sources"]} == {str(source.id)}
    assert {s["id"] for s in resp_b.json()["discovery_sources"]} == {str(source.id)}
    # group_probe_c never declared docker — must not receive it, even as a member.
    assert resp_c.json()["discovery_sources"] == []


@pytest.mark.asyncio
async def test_group_port_scan_source_served_only_to_elected(
    client: AsyncClient,
    db_session: AsyncSession,
    regular_user: User,
    group_probe_a: Probe,
    group_probe_b: Probe,
    group_probe_c: Probe,
    probe_group: ProbeGroup,
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_group_id=probe_group.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    # Before any election, elected_probe_id is NULL — nobody is served.
    resp_a_before = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": _PROBE_A_KEY}
    )
    assert resp_a_before.json()["discovery_sources"] == []

    changed = await run_discovery_elections(db_session)
    assert changed == 1
    await db_session.refresh(source)
    assert source.elected_probe_id in {group_probe_a.id, group_probe_c.id}

    key_by_probe = {group_probe_a.id: _PROBE_A_KEY, group_probe_c.id: _PROBE_C_KEY}
    other_id = group_probe_c.id if source.elected_probe_id == group_probe_a.id else group_probe_a.id

    resp_elected = await client.post(
        "/api/v1/probes/heartbeat",
        json={},
        headers={"X-Probe-Api-Key": key_by_probe[source.elected_probe_id]},
    )
    assert {s["id"] for s in resp_elected.json()["discovery_sources"]} == {str(source.id)}

    resp_other = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": key_by_probe[other_id]}
    )
    assert resp_other.json()["discovery_sources"] == []

    # group_probe_b is a member but never declared port_scan.
    resp_b = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": _PROBE_B_KEY}
    )
    assert resp_b.json()["discovery_sources"] == []


# ── push_discovery scope — extended to group membership ──────────────────────


@pytest.mark.asyncio
async def test_push_discovery_group_docker_accepted_from_capable_member(
    client: AsyncClient,
    db_session: AsyncSession,
    regular_user: User,
    group_probe_a: Probe,
    probe_group: ProbeGroup,
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id, probe_group_id=probe_group.id, source_type="docker", params={}
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source.id),
            "services": [{"host": "10.0.0.1", "port": 80, "proto": "tcp", "hints": {}}],
        },
        headers={"X-Probe-Api-Key": _PROBE_A_KEY},
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1}


@pytest.mark.asyncio
async def test_push_discovery_group_docker_rejected_from_incapable_member(
    client: AsyncClient,
    db_session: AsyncSession,
    regular_user: User,
    group_probe_c: Probe,
    probe_group: ProbeGroup,
) -> None:
    """`group_probe_c` is a member of the group but never declared `docker`."""
    source = DiscoverySource(
        owner_id=regular_user.id, probe_group_id=probe_group.id, source_type="docker", params={}
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/probes/discovery",
        json={
            "source_id": str(source.id),
            "services": [{"host": "10.0.0.1", "port": 80, "proto": "tcp", "hints": {}}],
        },
        headers={"X-Probe-Api-Key": _PROBE_C_KEY},
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0}


@pytest.mark.asyncio
async def test_push_discovery_group_port_scan_rejected_from_non_elected_member(
    client: AsyncClient,
    db_session: AsyncSession,
    regular_user: User,
    group_probe_a: Probe,
    group_probe_c: Probe,
    probe_group: ProbeGroup,
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_group_id=probe_group.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
        elected_probe_id=group_probe_a.id,
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    rejected = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source.id), "services": []},
        headers={"X-Probe-Api-Key": _PROBE_C_KEY},
    )
    assert rejected.status_code == 202
    assert rejected.json() == {"accepted": 0}
    await db_session.refresh(source)
    assert source.last_scan_at is None  # scope-rejected, never touched bookkeeping

    accepted = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source.id), "services": []},
        headers={"X-Probe-Api-Key": _PROBE_A_KEY},
    )
    assert accepted.status_code == 202
    assert accepted.json() == {"accepted": 0}
    await db_session.refresh(source)
    assert source.last_scan_at is not None  # legitimate push (0 services this time)


@pytest.mark.asyncio
async def test_push_discovery_non_member_probe_rejected(
    client: AsyncClient, db_session: AsyncSession, regular_user: User, probe_group: ProbeGroup
) -> None:
    outsider = Probe(
        name="outsider-probe",
        location_name="Z",
        api_key_hash=_hash(_PROBE_OUTSIDER_KEY),
        discovery_capabilities=["docker"],
    )
    db_session.add(outsider)
    await db_session.flush()
    source = DiscoverySource(
        owner_id=regular_user.id, probe_group_id=probe_group.id, source_type="docker", params={}
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/probes/discovery",
        json={"source_id": str(source.id), "services": []},
        headers={"X-Probe-Api-Key": _PROBE_OUTSIDER_KEY},
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0}


# ── Election — initial pick + re-election ────────────────────────────────────


@pytest.mark.asyncio
async def test_election_initial_pick_among_capable_probes(
    db_session: AsyncSession,
    regular_user: User,
    group_probe_a: Probe,
    group_probe_b: Probe,
    group_probe_c: Probe,
    probe_group: ProbeGroup,
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_group_id=probe_group.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    changed = await run_discovery_elections(db_session)
    assert changed == 1
    await db_session.refresh(source)
    # group_probe_b never declared port_scan — never eligible.
    assert source.elected_probe_id in {group_probe_a.id, group_probe_c.id}


@pytest.mark.asyncio
async def test_election_docker_source_never_gets_an_elected_probe(
    db_session: AsyncSession, regular_user: User, probe_group: ProbeGroup
) -> None:
    """Election only concerns port_scan/dns_zone — docker fans out."""
    source = DiscoverySource(
        owner_id=regular_user.id, probe_group_id=probe_group.id, source_type="docker", params={}
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    changed = await run_discovery_elections(db_session)
    assert changed == 0
    await db_session.refresh(source)
    assert source.elected_probe_id is None


@pytest.mark.asyncio
async def test_election_reelects_when_elected_probe_goes_stale(
    db_session: AsyncSession,
    regular_user: User,
    group_probe_a: Probe,
    group_probe_c: Probe,
    probe_group: ProbeGroup,
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_group_id=probe_group.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    await run_discovery_elections(db_session)
    await db_session.refresh(source)
    first = source.elected_probe_id
    other = group_probe_c.id if first == group_probe_a.id else group_probe_a.id

    stale = await db_session.get(Probe, first)
    stale.last_seen_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.flush()
    await db_session.commit()

    changed = await run_discovery_elections(db_session)
    await db_session.refresh(source)
    assert changed == 1
    assert source.elected_probe_id == other


@pytest.mark.asyncio
async def test_election_reelects_when_probe_leaves_group(
    db_session: AsyncSession,
    regular_user: User,
    group_probe_a: Probe,
    group_probe_c: Probe,
    probe_group: ProbeGroup,
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_group_id=probe_group.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    await run_discovery_elections(db_session)
    await db_session.refresh(source)
    first = source.elected_probe_id
    other = group_probe_c.id if first == group_probe_a.id else group_probe_a.id

    await db_session.execute(
        delete(probe_group_members).where(
            probe_group_members.c.probe_group_id == probe_group.id,
            probe_group_members.c.probe_id == first,
        )
    )
    await db_session.commit()
    # `probe_group.probes` is a lazy="selectin" collection cached on the
    # already-loaded ORM instance `elect_for_source` will fetch via
    # `db.get()` — a raw-table delete alone would leave that cache stale.
    await db_session.refresh(probe_group, attribute_names=["probes"])

    changed = await run_discovery_elections(db_session)
    await db_session.refresh(source)
    assert changed == 1
    assert source.elected_probe_id == other


@pytest.mark.asyncio
async def test_election_no_candidate_leaves_source_unelected(
    db_session: AsyncSession, regular_user: User, group_probe_b: Probe
) -> None:
    """A group with zero capable-and-alive members: elected_probe_id stays
    NULL (fail-visible via `group_capable_probe_count`, not a crash)."""
    group = ProbeGroup(name="no-port-scan-group")
    db_session.add(group)
    await db_session.flush()
    await db_session.execute(
        insert(probe_group_members).values(probe_group_id=group.id, probe_id=group_probe_b.id)
    )
    await db_session.commit()

    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_group_id=group.id,
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()

    changed = await run_discovery_elections(db_session)
    assert changed == 0
    await db_session.refresh(source)
    assert source.elected_probe_id is None


# ── Model — CHECK constraints ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_constraint_rejects_both_targets(
    db_session: AsyncSession, regular_user: User, group_probe_a: Probe, probe_group: ProbeGroup
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=group_probe_a.id,
        probe_group_id=probe_group.id,
        source_type="docker",
        params={},
    )
    db_session.add(source)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_check_constraint_rejects_neither_target(
    db_session: AsyncSession, regular_user: User
) -> None:
    source = DiscoverySource(owner_id=regular_user.id, source_type="docker", params={})
    db_session.add(source)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_check_constraint_elected_requires_group(
    db_session: AsyncSession, regular_user: User, group_probe_a: Probe
) -> None:
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=group_probe_a.id,
        elected_probe_id=group_probe_a.id,
        source_type="docker",
        params={},
    )
    db_session.add(source)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── PATCH — targeting mode stays immutable ───────────────────────────────────


@pytest.mark.asyncio
async def test_patch_cannot_switch_probe_source_to_group_target(
    client: AsyncClient,
    user_token: str,
    admin_token: str,
    group_visible: ProbeGroup,
) -> None:
    probe_id = await _register_probe(client, admin_token, "solo-probe-patch")
    # Targeting a probe directly needs the same visibility as targeting a
    # group (`assert_can_use_probe`): put it in the group the user can already
    # reach, so this test stays about the immutable targeting mode.
    await client.post(
        f"/api/v1/admin/probe-groups/{group_visible.id}/probes",
        json={"probe_ids": [probe_id]},
        headers=_auth(admin_token),
    )
    created = (
        await client.post(
            "/api/v1/discovery/sources/",
            json={"probe_id": probe_id, "source_type": "docker", "params": {}},
            headers=_auth(user_token),
        )
    ).json()

    resp = await client.patch(
        f"/api/v1/discovery/sources/{created['id']}",
        json={"probe_group_id": str(group_visible.id)},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_cannot_switch_group_source_to_probe_target(
    client: AsyncClient, user_token: str, admin_token: str, group_visible: ProbeGroup
) -> None:
    created = (
        await client.post(
            "/api/v1/discovery/sources/",
            json={"probe_group_id": str(group_visible.id), "source_type": "docker", "params": {}},
            headers=_auth(user_token),
        )
    ).json()
    probe_id = await _register_probe(client, admin_token, "solo-probe-patch-2")

    resp = await client.patch(
        f"/api/v1/discovery/sources/{created['id']}",
        json={"probe_id": probe_id},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422
