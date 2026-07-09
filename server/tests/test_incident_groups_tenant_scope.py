"""Tenant scoping of the incident-groups REST payload (finding SA7).

Correlation groups span tenants (correlation runs globally on shared probes),
so a group legitimately visible to user A (it contains one of A's incidents)
must NOT leak B's monitor ids or the root-cause monitor name to A. These
tests cover the REST twin of the WS finding SA5:

* cross-tenant leak: A and B share no team; a group correlates their monitors;
  A must see the group but only their own incident refs, and a foreign
  root-cause monitor must be nulled (id AND name);
* superadmin keeps the full cross-tenant payload;
* team sharing: a member (non-owner) sees team monitors via
  ``build_access_filter`` — both in the payload and for the detail-route gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_PASSWORD
from whatisup.core.security import hash_password
from whatisup.models.incident import Incident, IncidentGroup, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.team import Team, TeamMembership, TeamRole
from whatisup.models.user import User


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _mk_user(db: AsyncSession, email: str) -> User:
    u = User(
        email=email,
        username=email.split("@")[0],
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _login(client: AsyncClient, user: User) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": user.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _mk_monitor(db: AsyncSession, owner_id, name: str, *, team_id=None) -> Monitor:
    m = Monitor(name=name, url="http://example.com", owner_id=owner_id, team_id=team_id)
    db.add(m)
    await db.flush()
    return m


async def _mk_group_with_incidents(
    db: AsyncSession,
    monitors: list[Monitor],
    *,
    root_cause_monitor_id=None,
) -> tuple[IncidentGroup, list[Incident]]:
    now = datetime.now(UTC)
    group = IncidentGroup(
        triggered_at=now,
        cause_probe_ids=["p1"],
        status="open",
        root_cause_monitor_id=root_cause_monitor_id,
        correlation_type="probe",
    )
    db.add(group)
    await db.flush()
    incidents = []
    for m in monitors:
        inc = Incident(
            monitor_id=m.id,
            started_at=now,
            scope=IncidentScope.global_,
            affected_probe_ids=["p1"],
            group_id=group.id,
        )
        db.add(inc)
        incidents.append(inc)
    await db.flush()
    return group, incidents


async def _cross_tenant_fixture(db: AsyncSession):
    """Two users without any common team; a group correlating their monitors.

    The root cause is B's monitor — the strongest leak vector (name included).
    """
    user_a = await _mk_user(db, "tenant-a@test.com")
    user_b = await _mk_user(db, "tenant-b@test.com")
    mon_a = await _mk_monitor(db, user_a.id, "A-api")
    mon_b = await _mk_monitor(db, user_b.id, "B-secret-backend")
    group, (inc_a, inc_b) = await _mk_group_with_incidents(
        db, [mon_a, mon_b], root_cause_monitor_id=mon_b.id
    )
    return user_a, user_b, mon_a, mon_b, group, inc_a, inc_b


# ── Cross-tenant leak (must FAIL pre-fix) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_list_does_not_leak_foreign_monitor_ids(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_a, _ub, mon_a, mon_b, group, inc_a, inc_b = await _cross_tenant_fixture(db_session)
    token_a = await _login(client, user_a)

    resp = await client.get("/api/v1/incident-groups/", headers=_auth(token_a))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    g = data[0]
    assert g["id"] == str(group.id)

    # Only A's incident/monitor may appear; B's ids must be absent.
    assert g["incident_ids"] == [str(inc_a.id)]
    assert [r["monitor_id"] for r in g["incident_refs"]] == [str(mon_a.id)]
    body = resp.text
    assert str(mon_b.id) not in body
    assert str(inc_b.id) not in body

    # Foreign root cause: id AND name nulled — keys stay present (frontend contract).
    assert "root_cause_monitor_id" in g
    assert "root_cause_monitor_name" in g
    assert g["root_cause_monitor_id"] is None
    assert g["root_cause_monitor_name"] is None
    assert "B-secret-backend" not in body


@pytest.mark.asyncio
async def test_detail_does_not_leak_foreign_monitor_ids(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_a, _ub, mon_a, mon_b, group, inc_a, inc_b = await _cross_tenant_fixture(db_session)
    token_a = await _login(client, user_a)

    resp = await client.get(f"/api/v1/incident-groups/{group.id}", headers=_auth(token_a))
    assert resp.status_code == 200
    g = resp.json()
    assert g["incident_ids"] == [str(inc_a.id)]
    assert [r["monitor_id"] for r in g["incident_refs"]] == [str(mon_a.id)]
    assert g["root_cause_monitor_id"] is None
    assert g["root_cause_monitor_name"] is None
    assert str(mon_b.id) not in resp.text
    assert "B-secret-backend" not in resp.text


@pytest.mark.asyncio
async def test_detail_forbidden_when_no_incident_in_scope(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A third tenant with no incident in the group gets 403, not a payload."""
    _ua, _ub, _ma, _mb, group, _ia, _ib = await _cross_tenant_fixture(db_session)
    outsider = await _mk_user(db_session, "tenant-c@test.com")
    token_c = await _login(client, outsider)

    resp = await client.get(f"/api/v1/incident-groups/{group.id}", headers=_auth(token_c))
    assert resp.status_code == 403


# ── Superadmin keeps the full payload ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_superadmin_sees_full_group(
    client: AsyncClient, db_session: AsyncSession, admin_token: str
) -> None:
    _ua, _ub, mon_a, mon_b, group, inc_a, inc_b = await _cross_tenant_fixture(db_session)

    resp = await client.get("/api/v1/incident-groups/", headers=_auth(admin_token))
    assert resp.status_code == 200
    g = next(x for x in resp.json() if x["id"] == str(group.id))
    assert set(g["incident_ids"]) == {str(inc_a.id), str(inc_b.id)}
    assert {r["monitor_id"] for r in g["incident_refs"]} == {str(mon_a.id), str(mon_b.id)}
    assert g["root_cause_monitor_id"] == str(mon_b.id)
    assert g["root_cause_monitor_name"] == "B-secret-backend"

    detail = await client.get(f"/api/v1/incident-groups/{group.id}", headers=_auth(admin_token))
    assert detail.status_code == 200
    assert detail.json()["root_cause_monitor_name"] == "B-secret-backend"


# ── Team sharing via build_access_filter ──────────────────────────────────────


@pytest.mark.asyncio
async def test_team_member_sees_team_monitors(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A team member (non-owner) sees the team's monitors in the payload.

    The pre-fix ``owner_id``-only check ignored team sharing entirely: the
    member would have been denied the group (or shown a stripped payload).
    """
    owner = await _mk_user(db_session, "team-owner@test.com")
    member = await _mk_user(db_session, "team-member@test.com")
    stranger = await _mk_user(db_session, "team-stranger@test.com")
    team = Team(name="sa7-team", slug="sa7-team")
    db_session.add(team)
    await db_session.flush()
    db_session.add(TeamMembership(user_id=member.id, team_id=team.id, role=TeamRole.viewer))

    mon_team = await _mk_monitor(db_session, owner.id, "Team-mon", team_id=team.id)
    mon_foreign = await _mk_monitor(db_session, stranger.id, "Stranger-mon")
    group, (inc_team, inc_foreign) = await _mk_group_with_incidents(
        db_session, [mon_team, mon_foreign], root_cause_monitor_id=mon_team.id
    )
    token_member = await _login(client, member)

    # List: group visible through team membership, foreign incident stripped.
    resp = await client.get("/api/v1/incident-groups/", headers=_auth(token_member))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    g = data[0]
    assert g["incident_ids"] == [str(inc_team.id)]
    assert [r["monitor_id"] for r in g["incident_refs"]] == [str(mon_team.id)]
    # Root cause is the team monitor → visible to the member.
    assert g["root_cause_monitor_id"] == str(mon_team.id)
    assert g["root_cause_monitor_name"] == "Team-mon"
    assert str(mon_foreign.id) not in resp.text
    assert str(inc_foreign.id) not in resp.text

    # Detail: the team-based gate grants access (owner_id-only would 403 here).
    detail = await client.get(f"/api/v1/incident-groups/{group.id}", headers=_auth(token_member))
    assert detail.status_code == 200
    assert detail.json()["root_cause_monitor_name"] == "Team-mon"


@pytest.mark.asyncio
async def test_group_fully_foreign_not_listed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A group with zero incidents in scope stays invisible in the list."""
    _ua, _ub, _ma, _mb, group, _ia, _ib = await _cross_tenant_fixture(db_session)
    outsider = await _mk_user(db_session, "tenant-d@test.com")
    # Give the outsider an unrelated monitor so the scope set is non-empty.
    await _mk_monitor(db_session, outsider.id, "D-mon")
    token_d = await _login(client, outsider)

    resp = await client.get("/api/v1/incident-groups/", headers=_auth(token_d))
    assert resp.status_code == 200
    assert all(g["id"] != str(group.id) for g in resp.json())
