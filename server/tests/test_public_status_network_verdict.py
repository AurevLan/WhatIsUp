"""Plan cap V2, étape 3b — network verdict counters on the public status page.

Decisions under test (see plan_cap_v2.md § 3b):
- Open incident + partition verdict → verdict category *and* reachability
  counters ("reachable from N of M observation points").
- Resolved incident + partition verdict → category only, no counters (a count
  computed today would misdescribe the moment the outage happened).
- Null / inconclusive verdict → nothing published at all.
- Never, under any verdict, does the public payload carry an ASN number, a
  carrier/operator name, or a country code — that identity stays
  authenticated-only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_group_and_monitor(
    client: AsyncClient, token: str, *, slug: str, monitor_name: str
) -> tuple[str, str]:
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={"name": slug, "public_slug": slug},
            headers=_auth(token),
        )
    ).json()
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": monitor_name,
                "url": "https://example.com",
                "group_id": grp["id"],
            },
            headers=_auth(token),
        )
    ).json()
    return grp["id"], mon["id"]


def _make_probe(
    db_session: AsyncSession,
    *,
    name: str,
    asn: int | None,
    asn_name: str | None,
    country: str | None,
) -> Probe:
    probe = Probe(
        id=uuid.uuid4(),
        name=name,
        location_name="Test",
        api_key_hash="x",
        is_active=True,
        asn=asn,
        asn_name=asn_name,
        country_code=country,
    )
    db_session.add(probe)
    return probe


def _make_result(
    db_session: AsyncSession, *, monitor_id: uuid.UUID, probe_id: uuid.UUID, status: CheckStatus
) -> None:
    db_session.add(
        CheckResult(
            id=uuid.uuid4(),
            monitor_id=monitor_id,
            probe_id=probe_id,
            checked_at=datetime.now(UTC),
            status=status,
        )
    )


async def _seed_partitioned_probes(db_session: AsyncSession, monitor_id: uuid.UUID) -> None:
    """Two probes UP on one carrier, one probe DOWN on another — the shape a
    network_partition_asn verdict is computed from."""
    up1 = _make_probe(
        db_session, name=f"up1-{monitor_id}", asn=15169, asn_name="GOOGLE", country="US"
    )
    up2 = _make_probe(
        db_session, name=f"up2-{monitor_id}", asn=15169, asn_name="GOOGLE", country="US"
    )
    down1 = _make_probe(
        db_session, name=f"down1-{monitor_id}", asn=6939, asn_name="HURRICANE", country="FR"
    )
    await db_session.flush()
    _make_result(db_session, monitor_id=monitor_id, probe_id=up1.id, status=CheckStatus.up)
    _make_result(db_session, monitor_id=monitor_id, probe_id=up2.id, status=CheckStatus.up)
    _make_result(db_session, monitor_id=monitor_id, probe_id=down1.id, status=CheckStatus.down)
    await db_session.flush()


def _make_incident(
    *,
    monitor_id: uuid.UUID,
    verdict: str | None,
    resolved: bool,
) -> Incident:
    now = datetime.now(UTC)
    return Incident(
        id=uuid.uuid4(),
        monitor_id=monitor_id,
        started_at=now - timedelta(hours=1),
        resolved_at=now if resolved else None,
        duration_seconds=3600 if resolved else None,
        scope=IncidentScope.geographic,
        affected_probe_ids=[],
        network_verdict=verdict,
        network_verdict_computed_at=now if verdict else None,
    )


@pytest.mark.asyncio
async def test_open_partition_incident_has_verdict_and_counters(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    _, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-open-partition", monitor_name="OpenPartitionMon"
    )
    await _seed_partitioned_probes(db_session, uuid.UUID(monitor_id))
    db_session.add(
        _make_incident(
            monitor_id=uuid.UUID(monitor_id),
            verdict="network_partition_asn",
            resolved=False,
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/public/pages/pub-open-partition/status")
    assert resp.status_code == 200
    incidents = resp.json()["incidents_30d"]
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc["network_verdict"] == "network_partition_asn"
    assert inc["reachable_probes"] == 2
    assert inc["total_probes"] == 3


@pytest.mark.asyncio
async def test_resolved_partition_incident_has_no_counters(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    _, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-resolved-partition", monitor_name="ResolvedPartitionMon"
    )
    # Fleet is currently fully healthy — proves the endpoint isn't silently
    # smuggling a live count in for a resolved incident.
    await _seed_partitioned_probes(db_session, uuid.UUID(monitor_id))
    db_session.add(
        _make_incident(
            monitor_id=uuid.UUID(monitor_id),
            verdict="network_partition_geo",
            resolved=True,
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/public/pages/pub-resolved-partition/status")
    assert resp.status_code == 200
    inc = resp.json()["incidents_30d"][0]
    assert inc["network_verdict"] == "network_partition_geo"
    assert "reachable_probes" not in inc
    assert "total_probes" not in inc


@pytest.mark.parametrize(
    ("verdict", "slug_suffix"),
    [(None, "null"), ("inconclusive", "inconclusive"), ("service_down", "service-down")],
)
@pytest.mark.asyncio
async def test_non_partition_verdicts_publish_nothing(
    client: AsyncClient,
    user_token: str,
    db_session: AsyncSession,
    verdict: str | None,
    slug_suffix: str,
) -> None:
    slug = f"pub-silent-{slug_suffix}"
    _, monitor_id = await _make_group_and_monitor(
        client, user_token, slug=slug, monitor_name="SilentMon"
    )
    db_session.add(
        _make_incident(monitor_id=uuid.UUID(monitor_id), verdict=verdict, resolved=False)
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/public/pages/{slug}/status")
    assert resp.status_code == 200
    inc = resp.json()["incidents_30d"][0]
    assert "network_verdict" not in inc
    assert "reachable_probes" not in inc
    assert "total_probes" not in inc


@pytest.mark.asyncio
async def test_public_status_never_leaks_operator_identity(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    """Watertight test — the whole point of the plan's decision #2.

    Whatever the verdict, the raw JSON text of the public payload must never
    contain an ASN number, a carrier/operator name, or a country code.
    """
    _, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-leakproof", monitor_name="LeakproofMon"
    )
    await _seed_partitioned_probes(db_session, uuid.UUID(monitor_id))
    for verdict, resolved in [
        ("network_partition_asn", False),
        ("network_partition_geo", True),
        ("service_down", False),
        ("inconclusive", False),
        (None, True),
    ]:
        db_session.add(
            _make_incident(monitor_id=uuid.UUID(monitor_id), verdict=verdict, resolved=resolved)
        )
    await db_session.commit()

    resp = await client.get("/api/v1/public/pages/pub-leakproof/status")
    assert resp.status_code == 200
    raw = resp.text

    # Neither the AS number, the carrier name, nor the country codes used to
    # seed the probes above may appear anywhere in the public payload.
    for forbidden in ("15169", "6939", "GOOGLE", "HURRICANE", '"US"', '"FR"'):
        assert forbidden not in raw, f"public payload leaked {forbidden!r}"
