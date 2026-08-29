"""Purge of `discovered_services` (terminal states) and `alert_events` (audit hardening, 2026-08).

Neither table had any retention at all before this. The properties worth
pinning:

* `discovered_services`: only `dismissed`/`orphaned` age out — a `proposed`
  row is a decision nobody made yet, and an `accepted` row is the provenance
  of a live monitor. Cut on `status_changed_at`, not `last_seen_at`.
* `alert_events`: a plain time cutoff on `sent_at`, same "0 = keep forever"
  convention as every other retention knob.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.core.database as db_mod
from tests.test_background_services import _FactoryStub
from whatisup.models.alert import AlertChannel, AlertChannelType, AlertEvent, AlertEventStatus
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.user import User
from whatisup.services.retention import purge_old_alert_events, purge_old_discovered_services

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db(service_db: AsyncSession, monkeypatch):
    """Point the retention job's own session factory at the test session."""
    monkeypatch.setattr(db_mod, "_async_session_factory", _FactoryStub(service_db))
    return service_db


# ── discovered_services ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def source(db: AsyncSession, test_user: User, test_probe: Probe) -> DiscoverySource:
    s = DiscoverySource(owner_id=test_user.id, probe_id=test_probe.id, source_type="port_scan")
    db.add(s)
    await db.flush()
    return s


def _service(
    source_id, *, status: str, status_changed_at: datetime, target: str
) -> DiscoveredService:
    return DiscoveredService(
        source_id=source_id,
        host="10.0.0.1",
        port=443,
        proto="tcp",
        normalized_target=target,
        status=status,
        status_changed_at=status_changed_at,
    )


async def _count_services(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(DiscoveredService))).scalar_one()


async def test_purge_drops_only_terminal_states_past_the_horizon(
    db: AsyncSession, source: DiscoverySource
):
    now = datetime.now(UTC)
    old = now - timedelta(days=120)
    recent = now - timedelta(days=1)
    db.add_all(
        [
            _service(source.id, status="dismissed", status_changed_at=old, target="tcp://a:1"),
            _service(source.id, status="orphaned", status_changed_at=old, target="tcp://b:2"),
            _service(source.id, status="dismissed", status_changed_at=recent, target="tcp://c:3"),
            # Terminal-looking age, but not a terminal status — must survive.
            _service(source.id, status="proposed", status_changed_at=old, target="tcp://d:4"),
            _service(source.id, status="accepted", status_changed_at=old, target="tcp://e:5"),
        ]
    )
    await db.flush()

    assert await purge_old_discovered_services(90) == 2
    remaining = {
        s.normalized_target for s in (await db.execute(select(DiscoveredService))).scalars().all()
    }
    assert remaining == {"tcp://c:3", "tcp://d:4", "tcp://e:5"}


async def test_a_proposed_row_never_disappears_on_its_own(
    db: AsyncSession, source: DiscoverySource
):
    """A pending decision must survive however old it is."""
    ancient = datetime.now(UTC) - timedelta(days=3650)
    db.add(_service(source.id, status="proposed", status_changed_at=ancient, target="tcp://old:1"))
    await db.flush()

    assert await purge_old_discovered_services(1) == 0
    assert await _count_services(db) == 1


async def test_discovered_services_retention_zero_keeps_forever(
    db: AsyncSession, source: DiscoverySource
):
    ancient = datetime.now(UTC) - timedelta(days=3650)
    db.add(_service(source.id, status="orphaned", status_changed_at=ancient, target="tcp://old:1"))
    await db.flush()

    assert await purge_old_discovered_services(0) == 0
    assert await _count_services(db) == 1


# ── alert_events ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def incident_and_channel(
    db: AsyncSession, test_user: User, test_monitor: Monitor
) -> tuple[Incident, AlertChannel]:
    incident = Incident(
        monitor_id=test_monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    channel = AlertChannel(
        owner_id=test_user.id,
        name="chan",
        type=AlertChannelType.webhook,
        config={"url": "https://example.com/hook"},
    )
    db.add_all([incident, channel])
    await db.flush()
    return incident, channel


def _event(incident_id, channel_id, *, sent_at: datetime) -> AlertEvent:
    return AlertEvent(
        incident_id=incident_id,
        channel_id=channel_id,
        sent_at=sent_at,
        status=AlertEventStatus.sent,
    )


async def _count_events(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(AlertEvent))).scalar_one()


async def test_purge_drops_alert_events_past_the_horizon(
    db: AsyncSession, incident_and_channel: tuple[Incident, AlertChannel]
):
    incident, channel = incident_and_channel
    now = datetime.now(UTC)
    db.add_all(
        [
            _event(incident.id, channel.id, sent_at=now - timedelta(days=120)),
            _event(incident.id, channel.id, sent_at=now - timedelta(days=91)),
            _event(incident.id, channel.id, sent_at=now - timedelta(days=89)),
            _event(incident.id, channel.id, sent_at=now - timedelta(hours=1)),
        ]
    )
    await db.flush()

    assert await purge_old_alert_events(90) == 2
    assert await _count_events(db) == 2


async def test_alert_events_retention_zero_keeps_forever(
    db: AsyncSession, incident_and_channel: tuple[Incident, AlertChannel]
):
    incident, channel = incident_and_channel
    db.add(_event(incident.id, channel.id, sent_at=datetime.now(UTC) - timedelta(days=3650)))
    await db.flush()

    assert await purge_old_alert_events(0) == 0
    assert await _count_events(db) == 1
