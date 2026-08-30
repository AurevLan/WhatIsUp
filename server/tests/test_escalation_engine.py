"""Escalation ladders (plan V2, B-1).

An on-call engine is judged on what it does when things are misconfigured, not
when they are right. Half of this file is about ladders that reach nobody —
because the failure that matters is not "paged the wrong person", it is "paged
nobody and said nothing", and the operator finds out the next morning.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertChannel, AlertChannelType, AlertCondition, AlertRule
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.oncall import (
    EscalationLevel,
    EscalationPolicy,
    EscalationState,
    EscalationTargetType,
    OnCallParticipant,
    OnCallSchedule,
)
from whatisup.models.user import User
from whatisup.services.escalation import arm_escalation, cancel_escalation, run_due_escalations

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def sent(monkeypatch) -> list[dict]:
    """Capture dispatches instead of performing them."""
    calls: list[dict] = []

    async def _fake_dispatch(db, incident, channel, event_type="incident_opened", ctx=None):
        calls.append(
            {
                "incident_id": incident.id,
                "channel": getattr(channel, "name", None),
                "ctx": ctx or {},
            }
        )

    import whatisup.services.alert as alert_mod

    monkeypatch.setattr(alert_mod, "dispatch_alert", _fake_dispatch)
    return calls


async def _channel(db: AsyncSession, owner: User, name: str) -> AlertChannel:
    channel = AlertChannel(owner_id=owner.id, name=name, type=AlertChannelType.webhook, config={})
    db.add(channel)
    await db.flush()
    return channel


async def _incident(db: AsyncSession, monitor: Monitor) -> Incident:
    inc = Incident(
        monitor_id=monitor.id,
        started_at=NOW,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    db.add(inc)
    await db.flush()
    return inc


async def _policy(db: AsyncSession, owner: User, *, repeat: int = 0) -> EscalationPolicy:
    policy = EscalationPolicy(owner_id=owner.id, name="ladder", repeat_count=repeat)
    db.add(policy)
    await db.flush()
    return policy


async def _level(db: AsyncSession, policy, position, delay, **target) -> EscalationLevel:
    level = EscalationLevel(policy_id=policy.id, position=position, delay_minutes=delay, **target)
    db.add(level)
    await db.flush()
    return level


async def _rule(db: AsyncSession, owner: User, monitor: Monitor, policy, channels=()) -> AlertRule:
    rule = AlertRule(
        owner_id=owner.id,
        monitor_id=monitor.id,
        condition=AlertCondition.any_down,
        escalation_policy_id=policy.id if policy else None,
        channels=list(channels),
    )
    db.add(rule)
    await db.flush()
    return rule


async def _states(db: AsyncSession) -> int:
    return (await db.execute(select(func.count(EscalationState.id)))).scalar_one()


# ── Arming ────────────────────────────────────────────────────────────────────


async def test_arming_schedules_the_first_rung(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor
):
    policy = await _policy(service_db, test_user)
    channel = await _channel(service_db, test_user, "ops")
    await _level(
        service_db,
        policy,
        0,
        5,
        target_type=EscalationTargetType.channel,
        target_channel_id=channel.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)

    assert await arm_escalation(service_db, incident, rule, now=NOW) is True
    state = (await service_db.execute(select(EscalationState))).scalar_one()
    # L1's own delay applies: 0 means "page now", 5 means "wait first".
    assert state.next_fire_at.replace(tzinfo=UTC) == NOW + timedelta(minutes=5)
    assert state.next_position == 0


async def test_a_policy_with_no_rungs_does_not_swallow_the_alert(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor
):
    """A ladder under construction is not an instruction to stay silent."""
    policy = await _policy(service_db, test_user)
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)

    # False → fire_alerts falls through to the rule's own channels.
    assert await arm_escalation(service_db, incident, rule, now=NOW) is False
    assert await _states(service_db) == 0


async def test_a_disabled_policy_is_ignored(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor
):
    policy = await _policy(service_db, test_user)
    policy.enabled = False
    channel = await _channel(service_db, test_user, "ops")
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.channel,
        target_channel_id=channel.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)
    assert await arm_escalation(service_db, incident, rule, now=NOW) is False


async def test_arming_twice_keeps_the_first_ladder(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor
):
    """Two rules matching one incident must not restart it from L1."""
    policy = await _policy(service_db, test_user)
    channel = await _channel(service_db, test_user, "ops")
    await _level(
        service_db,
        policy,
        0,
        5,
        target_type=EscalationTargetType.channel,
        target_channel_id=channel.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)

    await arm_escalation(service_db, incident, rule, now=NOW)
    await arm_escalation(service_db, incident, rule, now=NOW + timedelta(minutes=1))
    assert await _states(service_db) == 1


# ── Walking the ladder ────────────────────────────────────────────────────────


async def test_rungs_fire_in_order_with_their_delays(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor, sent: list
):
    policy = await _policy(service_db, test_user)
    l1 = await _channel(service_db, test_user, "l1")
    l2 = await _channel(service_db, test_user, "l2")
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.channel,
        target_channel_id=l1.id,
    )
    await _level(
        service_db,
        policy,
        1,
        10,
        target_type=EscalationTargetType.channel,
        target_channel_id=l2.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)
    await arm_escalation(service_db, incident, rule, now=NOW)

    assert await run_due_escalations(service_db, now=NOW) == 1
    assert [c["channel"] for c in sent] == ["l1"]

    # Too early for L2.
    assert await run_due_escalations(service_db, now=NOW + timedelta(minutes=5)) == 0
    assert await run_due_escalations(service_db, now=NOW + timedelta(minutes=10)) == 1
    assert [c["channel"] for c in sent] == ["l1", "l2"]

    # Ladder exhausted: the state is gone and renotify takes over.
    assert await _states(service_db) == 0


async def test_a_rung_that_reaches_nobody_does_not_spend_its_delay(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor, sent: list
):
    """A broken middle must not double the time to the reachable person."""
    policy = await _policy(service_db, test_user)
    empty_rota = OnCallSchedule(owner_id=test_user.id, name="empty", start_at=NOW, timezone="UTC")
    service_db.add(empty_rota)
    await service_db.flush()
    l3 = await _channel(service_db, test_user, "l3")

    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.schedule,
        target_schedule_id=empty_rota.id,
    )
    await _level(
        service_db,
        policy,
        1,
        30,
        target_type=EscalationTargetType.channel,
        target_channel_id=l3.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)
    await arm_escalation(service_db, incident, rule, now=NOW)

    # One tick: the empty rung is skipped and L2 fires in the same pass rather
    # than waiting out its 30 minutes.
    assert await run_due_escalations(service_db, now=NOW) == 1
    assert [c["channel"] for c in sent] == ["l3"]


async def test_a_ladder_reaching_nobody_falls_back_to_the_rule_channels(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor, sent: list
):
    """Attaching a policy must never make an alert quieter than attaching none."""
    policy = await _policy(service_db, test_user)
    empty_rota = OnCallSchedule(owner_id=test_user.id, name="empty", start_at=NOW, timezone="UTC")
    service_db.add(empty_rota)
    await service_db.flush()
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.schedule,
        target_schedule_id=empty_rota.id,
    )

    fallback = await _channel(service_db, test_user, "fallback")
    rule = await _rule(service_db, test_user, test_monitor, policy, channels=[fallback])
    incident = await _incident(service_db, test_monitor)
    await arm_escalation(service_db, incident, rule, now=NOW)

    await run_due_escalations(service_db, now=NOW)
    assert [c["channel"] for c in sent] == ["fallback"]
    assert sent[0]["ctx"].get("escalation_fallback") is True


async def test_a_schedule_rung_pages_whoever_is_on_call(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor, sent: list
):
    person = User(email="dev@example.com", username="dev", hashed_password="x")
    service_db.add(person)
    await service_db.flush()

    rota = OnCallSchedule(owner_id=test_user.id, name="rota", start_at=NOW, timezone="UTC")
    service_db.add(rota)
    await service_db.flush()
    service_db.add(OnCallParticipant(schedule_id=rota.id, user_id=person.id, position=0))
    await service_db.flush()

    policy = await _policy(service_db, test_user)
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.schedule,
        target_schedule_id=rota.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)
    await arm_escalation(service_db, incident, rule, now=NOW)

    # No contact rows: the engine falls back to the account email, so the
    # person named by the rotation is reachable rather than silently skipped.
    assert await run_due_escalations(service_db, now=NOW) == 1
    assert await _states(service_db) == 0


async def test_repeat_count_replays_the_whole_ladder(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor, sent: list
):
    policy = await _policy(service_db, test_user, repeat=1)
    channel = await _channel(service_db, test_user, "ops")
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.channel,
        target_channel_id=channel.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)
    await arm_escalation(service_db, incident, rule, now=NOW)

    await run_due_escalations(service_db, now=NOW)
    # Still armed for one more pass.
    assert await _states(service_db) == 1
    await run_due_escalations(service_db, now=NOW + timedelta(minutes=1))
    assert len(sent) == 2
    assert await _states(service_db) == 0


# ── Stopping ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acked_at", NOW),
        ("resolved_at", NOW),
        ("snooze_until", NOW + timedelta(hours=1)),
    ],
)
async def test_the_ladder_stops(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor, sent: list, field, value
):
    policy = await _policy(service_db, test_user)
    channel = await _channel(service_db, test_user, "ops")
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.channel,
        target_channel_id=channel.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)
    await arm_escalation(service_db, incident, rule, now=NOW)

    setattr(incident, field, value)
    await service_db.flush()

    assert await run_due_escalations(service_db, now=NOW) == 0
    assert sent == []
    assert await _states(service_db) == 0


async def test_cancelling_drops_the_ladder(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor
):
    policy = await _policy(service_db, test_user)
    channel = await _channel(service_db, test_user, "ops")
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.channel,
        target_channel_id=channel.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)
    await arm_escalation(service_db, incident, rule, now=NOW)

    await cancel_escalation(service_db, incident.id)
    assert await _states(service_db) == 0


async def test_a_paused_monitor_stops_escalating(
    service_db: AsyncSession, test_user: User, test_monitor: Monitor, sent: list
):
    policy = await _policy(service_db, test_user)
    channel = await _channel(service_db, test_user, "ops")
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.channel,
        target_channel_id=channel.id,
    )
    rule = await _rule(service_db, test_user, test_monitor, policy)
    incident = await _incident(service_db, test_monitor)
    await arm_escalation(service_db, incident, rule, now=NOW)

    test_monitor.enabled = False
    await service_db.flush()

    assert await run_due_escalations(service_db, now=NOW) == 0
    assert sent == []


# ── Per-tick batch cap (architecture hardening) ────────────────────────────────


async def test_run_due_escalations_caps_batch_and_defers_the_rest(
    service_db: AsyncSession, test_user: User, sent: list, monkeypatch
):
    """A backlog bigger than the per-tick cap must not be dropped: the most
    overdue rungs (lowest ``next_fire_at``) fire this tick, and the rest fire
    on the next one — nothing is skipped."""
    from whatisup.core.config import get_settings

    monkeypatch.setattr(get_settings(), "escalation_max_states_per_run", 2)

    policy = await _policy(service_db, test_user)
    channel = await _channel(service_db, test_user, "ops")
    await _level(
        service_db,
        policy,
        0,
        0,
        target_type=EscalationTargetType.channel,
        target_channel_id=channel.id,
    )

    incidents = []
    for i in range(3):
        monitor = Monitor(name=f"mon-{i}", url=f"http://example.com/{i}", owner_id=test_user.id)
        service_db.add(monitor)
        await service_db.flush()
        rule = await _rule(service_db, test_user, monitor, policy)
        incident = await _incident(service_db, monitor)
        # Distinct, increasing next_fire_at so processing order is deterministic.
        await arm_escalation(service_db, incident, rule, now=NOW + timedelta(seconds=i))
        incidents.append(incident)

    assert await _states(service_db) == 3

    # Cap of 2: only the two most-overdue rungs fire this tick.
    fired = await run_due_escalations(service_db, now=NOW + timedelta(minutes=5))
    assert fired == 2
    assert await _states(service_db) == 1  # the third rung is still pending, not lost

    # Next tick drains what's left.
    fired = await run_due_escalations(service_db, now=NOW + timedelta(minutes=5))
    assert fired == 1
    assert await _states(service_db) == 0
    assert len(sent) == 3
