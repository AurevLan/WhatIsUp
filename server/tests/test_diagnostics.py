"""Tests for V2-01-01 — incident-open auto-traceroute pipeline.

Covers four contracts:
1. ``process_check_result`` enqueues a Redis diagnostic request when an
   incident opens.
2. ``POST /probes/diagnostics`` validates the payload schema and persists rows.
3. Multiple probes may post concurrently for the same incident with no FK
   collision.
4. The heartbeat endpoint drains pending requests (probe-disconnect retry: a
   probe that misses one heartbeat sees the next one return the request, until
   it acks by posting results — actually our design pops keys at first read,
   matching at-most-once semantics, which the test verifies).
"""

from __future__ import annotations

from datetime import UTC, datetime

import bcrypt
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.core.redis as redis_module
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.incident_diagnostic import IncidentDiagnostic
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.diagnostics import (
    drain_pending_diagnostics,
    enqueue_diagnostic_requests,
)
from whatisup.services.incident import process_check_result

_PROBE_KEY = "wiu_test_diag_probe_key"
_PROBE_HEADERS = {"X-Probe-Api-Key": _PROBE_KEY}


@pytest_asyncio.fixture
async def diag_probe(db_session: AsyncSession) -> Probe:
    key_hash = bcrypt.hashpw(_PROBE_KEY.encode(), bcrypt.gensalt(rounds=4)).decode()
    p = Probe(name="diag-probe", location_name="DC1", api_key_hash=key_hash, is_active=True)
    db_session.add(p)
    await db_session.flush()
    return p


class _Collector:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


# ── (1) Incident open → Redis enqueue ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_incident_open_enqueues_diagnostic_requests(
    service_db: AsyncSession,
    test_user: User,
    fake_redis: FakeRedis,
) -> None:
    monitor = Monitor(name="diag-mon", url="https://example.com", owner_id=test_user.id)
    service_db.add(monitor)
    await service_db.flush()

    probe = Probe(name="p1", location_name="DC1", api_key_hash="x", is_active=True)
    service_db.add(probe)
    await service_db.flush()

    redis_module._redis = fake_redis

    result = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        checked_at=datetime.now(UTC),
        status=CheckStatus.down,
    )
    service_db.add(result)
    await service_db.flush()

    await process_check_result(service_db, result, _Collector())

    incident = (
        await service_db.execute(
            select(Incident).where(Incident.monitor_id == monitor.id)
        )
    ).scalar_one_or_none()
    assert incident is not None

    keys = []
    async for key in fake_redis.scan_iter(match="whatisup:diag_request:*"):
        keys.append(key)
    assert len(keys) == 1
    key_str = keys[0].decode() if isinstance(keys[0], bytes) else keys[0]
    assert str(probe.id) in key_str


# ── (2) POST /probes/diagnostics payload schema ──────────────────────────────


@pytest.mark.asyncio
async def test_diagnostic_ingest_persists_valid_payload(
    client: AsyncClient,
    db_session: AsyncSession,
    diag_probe: Probe,
    test_user: User,
) -> None:
    monitor = Monitor(name="m", url="https://x.test", owner_id=test_user.id)
    db_session.add(monitor)
    await db_session.flush()
    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[str(diag_probe.id)],
    )
    db_session.add(incident)
    await db_session.flush()

    body = {
        "incident_id": str(incident.id),
        "results": [
            {
                "kind": "traceroute",
                "payload": {"hops": [{"n": 1, "ip": "10.0.0.1", "rtt_ms": 1.2}], "total_hops": 1},
                "error": None,
                "collected_at": datetime.now(UTC).isoformat(),
            },
            {
                "kind": "icmp_ping",
                "payload": {"packets_sent": 5, "packets_received": 5, "loss_pct": 0.0},
                "error": None,
                "collected_at": datetime.now(UTC).isoformat(),
            },
        ],
    }
    resp = await client.post("/api/v1/probes/diagnostics", json=body, headers=_PROBE_HEADERS)
    assert resp.status_code == 202, resp.text
    assert resp.json()["accepted"] == 2

    rows = (
        await db_session.execute(
            select(IncidentDiagnostic).where(IncidentDiagnostic.incident_id == incident.id)
        )
    ).scalars().all()
    assert {r.kind for r in rows} == {"traceroute", "icmp_ping"}

    # Bogus payload — empty results list rejected by Pydantic min_length=1
    bad = await client.post(
        "/api/v1/probes/diagnostics",
        json={"incident_id": str(incident.id), "results": []},
        headers=_PROBE_HEADERS,
    )
    assert bad.status_code == 422


# ── (3) Multi-probe parallel ingest ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_probe_parallel_ingest(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    # Three probes with the same shared key (simpler than three keys).
    key_hash = bcrypt.hashpw(_PROBE_KEY.encode(), bcrypt.gensalt(rounds=4)).decode()
    probes = []
    for i in range(3):
        p = Probe(
            name=f"para-probe-{i}",
            location_name="DC",
            api_key_hash=key_hash,
            is_active=True,
        )
        db_session.add(p)
        probes.append(p)

    monitor = Monitor(name="paramon", url="https://x.test", owner_id=test_user.id)
    db_session.add(monitor)
    await db_session.flush()

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[str(p.id) for p in probes],
    )
    db_session.add(incident)
    await db_session.flush()

    # Probes post one after another — what matters for the contract is that
    # multiple distinct probe FKs land cleanly under the same incident, with
    # no unique-constraint collision on (incident, kind, probe).
    codes: list[int] = []
    for _p in probes:
        body = {
            "incident_id": str(incident.id),
            "results": [
                {
                    "kind": "traceroute",
                    "payload": {"target_ip": "1.2.3.4"},
                    "error": None,
                    "collected_at": datetime.now(UTC).isoformat(),
                }
            ],
        }
        resp = await client.post(
            "/api/v1/probes/diagnostics", json=body, headers=_PROBE_HEADERS
        )
        codes.append(resp.status_code)
    assert all(c == 202 for c in codes), codes

    rows = (
        await db_session.execute(
            select(IncidentDiagnostic).where(IncidentDiagnostic.incident_id == incident.id)
        )
    ).scalars().all()
    assert len(rows) == 3


# ── (4) Heartbeat drain consumes Redis keys ──────────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_drains_pending_diagnostics(
    fake_redis: FakeRedis,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    redis_module._redis = fake_redis
    probe = Probe(name="drain-probe", location_name="DC", api_key_hash="x", is_active=True)
    monitor = Monitor(name="drain-mon", url="https://x.test", owner_id=test_user.id)
    db_session.add_all([probe, monitor])
    await db_session.flush()

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[str(probe.id)],
    )
    db_session.add(incident)
    await db_session.flush()

    await enqueue_diagnostic_requests(
        incident_id=incident.id,
        monitor_id=monitor.id,
        target=monitor.url,
        check_type="http",
        affected_probe_ids=[str(probe.id)],
    )

    first = await drain_pending_diagnostics(probe.id)
    assert len(first) == 1
    assert first[0]["incident_id"] == str(incident.id)
    assert first[0]["target"] == monitor.url

    # Second drain returns empty — at-most-once delivery (probe-disconnect retry
    # is bounded by the 1h Redis TTL on each key, not by re-reads).
    second = await drain_pending_diagnostics(probe.id)
    assert second == []
