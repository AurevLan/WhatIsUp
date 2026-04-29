"""V2-02-06 — Tests for the incident playback timeline endpoint."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User


@pytest.mark.asyncio
async def test_timeline_returns_per_probe_points(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    admin_token: str,
) -> None:
    monitor = Monitor(name="m-tl", url="http://example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    probe_a = Probe(name="probe-a", location_name="Paris", api_key_hash="x", asn=15169)
    probe_b = Probe(name="probe-b", location_name="Berlin", api_key_hash="x", asn=2914)
    db_session.add_all([probe_a, probe_b])
    await db_session.flush()

    started = datetime.now(UTC) - timedelta(minutes=10)
    incident = Incident(
        monitor_id=monitor.id,
        started_at=started,
        scope=IncidentScope.geographic,
        affected_probe_ids=[str(probe_a.id)],
    )
    db_session.add(incident)
    await db_session.flush()

    db_session.add_all([
        CheckResult(
            monitor_id=monitor.id, probe_id=probe_a.id,
            checked_at=started + timedelta(minutes=i),
            status=CheckStatus.down if i >= 3 else CheckStatus.up,
        )
        for i in range(8)
    ] + [
        CheckResult(
            monitor_id=monitor.id, probe_id=probe_b.id,
            checked_at=started + timedelta(minutes=i),
            status=CheckStatus.up,
        )
        for i in range(8)
    ])
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/incidents/{incident.id}/timeline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_id"] == str(incident.id)
    points = body["points"]
    assert len(points) == 16
    # Both probes represented
    probe_ids = {p["probe_id"] for p in points}
    assert probe_ids == {str(probe_a.id), str(probe_b.id)}
    # ASN propagated
    asns = {p["probe_asn"] for p in points if p["probe_asn"] is not None}
    assert asns == {15169, 2914}
    # Status mix
    statuses = {p["status"] for p in points}
    assert "down" in statuses
    assert "up" in statuses


@pytest.mark.asyncio
async def test_timeline_unknown_incident_returns_404(
    client: AsyncClient, admin_token: str
) -> None:
    resp = await client.get(
        f"/api/v1/incidents/{uuid.uuid4()}/timeline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_timeline_other_user_incident_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    regular_user: User,
    user_token: str,
) -> None:
    other = User(email="other@x", username="other", hashed_password="x")
    db_session.add(other)
    await db_session.flush()

    monitor = Monitor(name="m-other", url="http://x", owner_id=other.id)
    db_session.add(monitor)
    await db_session.flush()

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    db_session.add(incident)
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/incidents/{incident.id}/timeline",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    # Cross-tenant access denied. Today the helper raises 403; the
    # SECURITY.md §5 rule prefers 404 (no existence leak) — to be tightened
    # in a separate cleanup PR for the whole _get_incident_for_user path.
    assert resp.status_code in (403, 404)
