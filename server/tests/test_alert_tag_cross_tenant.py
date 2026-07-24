"""F1 — tag_selector alert rules must not leak across tenants.

Tag names are a global shared pool (``Tag.name`` is unique across all users), so
a ``tag_selector`` rule that matched on tag-name intersection alone let any
authenticated user subscribe to another tenant's outages by putting a common tag
name (``prod``) in their rule. ``fire_alerts`` must only match a tag_selector
rule against a monitor its owner can actually access (owner or team member).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertChannel, AlertChannelType, AlertCondition, AlertRule
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.tag import Tag
from whatisup.models.team import Team, TeamMembership, TeamRole
from whatisup.models.user import User


async def _mk_user(db: AsyncSession, email: str) -> User:
    u = User(email=email, username=email.split("@")[0], hashed_password="x")
    db.add(u)
    await db.flush()
    return u


async def _mk_channel(db: AsyncSession, owner: User) -> AlertChannel:
    ch = AlertChannel(
        owner_id=owner.id,
        name="email",
        type=AlertChannelType.email,
        config={"to": "ops@x"},
    )
    db.add(ch)
    await db.flush()
    return ch


async def _mk_tag_rule(db: AsyncSession, owner: User, channel: AlertChannel) -> AlertRule:
    rule = AlertRule(
        owner_id=owner.id,
        condition=AlertCondition.any_down,
        tag_selector=["prod"],
        min_duration_seconds=0,
        digest_minutes=0,
        channels=[channel],
    )
    db.add(rule)
    await db.flush()
    return rule


async def _fire(db: AsyncSession, incident: Incident, monitor: Monitor) -> AsyncMock:
    with patch(
        "whatisup.services.incident_alerts.maybe_digest_or_dispatch",
        new_callable=AsyncMock,
    ) as mock_dispatch:
        from whatisup.services.incident_alerts import fire_alerts

        await fire_alerts(db, incident, monitor, event_type="incident_opened")
    return mock_dispatch


@pytest.mark.asyncio
async def test_tag_rule_does_not_match_other_tenant_monitor(service_db: AsyncSession) -> None:
    """Attacker's tag_selector=['prod'] rule must not fire on victim's monitor."""
    victim = await _mk_user(service_db, "victim@x")
    attacker = await _mk_user(service_db, "attacker@x")

    tag = Tag(name="prod")
    service_db.add(tag)
    await service_db.flush()

    monitor = Monitor(name="victim-mon", url="http://internal", owner_id=victim.id, tags=[tag])
    service_db.add(monitor)
    await service_db.flush()

    attacker_ch = await _mk_channel(service_db, attacker)
    await _mk_tag_rule(service_db, attacker, attacker_ch)

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(incident)
    await service_db.flush()

    mock_dispatch = await _fire(service_db, incident, monitor)
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_tag_rule_matches_own_monitor(service_db: AsyncSession) -> None:
    """The owner's own tag_selector rule still fires — no regression."""
    owner = await _mk_user(service_db, "owner@x")

    tag = Tag(name="prod")
    service_db.add(tag)
    await service_db.flush()

    monitor = Monitor(name="own-mon", url="http://ok", owner_id=owner.id, tags=[tag])
    service_db.add(monitor)
    await service_db.flush()

    ch = await _mk_channel(service_db, owner)
    await _mk_tag_rule(service_db, owner, ch)

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(incident)
    await service_db.flush()

    mock_dispatch = await _fire(service_db, incident, monitor)
    mock_dispatch.assert_awaited()


@pytest.mark.asyncio
async def test_tag_rule_matches_shared_team_monitor(service_db: AsyncSession) -> None:
    """A team member's tag_selector rule fires on a monitor shared with that team."""
    owner = await _mk_user(service_db, "towner@x")
    member = await _mk_user(service_db, "tmember@x")

    team = Team(name="ops", slug="ops")
    service_db.add(team)
    await service_db.flush()
    service_db.add(TeamMembership(team_id=team.id, user_id=member.id, role=TeamRole.viewer))
    await service_db.flush()

    tag = Tag(name="prod")
    service_db.add(tag)
    await service_db.flush()

    monitor = Monitor(
        name="team-mon", url="http://ok", owner_id=owner.id, team_id=team.id, tags=[tag]
    )
    service_db.add(monitor)
    await service_db.flush()

    ch = await _mk_channel(service_db, member)
    await _mk_tag_rule(service_db, member, ch)

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(incident)
    await service_db.flush()

    mock_dispatch = await _fire(service_db, incident, monitor)
    mock_dispatch.assert_awaited()
