"""Timed escalation ladders (plan V2, B-1).

``renotify`` re-pages the *same* channels on a timer. An escalation ladder pages
*different* targets in order — L1, then L2 if nobody acknowledged, then the
on-call rotation — which is the gap this closes.

How a ladder runs
─────────────────
``fire_alerts`` arms one when a matching rule carries an ``escalation_policy_id``
(see ``arm_escalation``). From then on a background loop walks it: each tick
picks the states whose ``next_fire_at`` has come, pages that rung, and schedules
the next one ``delay_minutes`` later — counted from *this* rung firing, which is
what lets a rung be inserted mid-ladder without shifting everything above it.

Why a rung that reaches nobody must not wait
────────────────────────────────────────────
A level can resolve to no one: an empty rotation, a departed user, a schedule
someone disabled. If such a rung consumed its delay like any other, a
three-rung ladder with a broken middle would take twice as long to reach the
person who *is* reachable — at exactly the moment that matters. So an
unreachable rung is logged and skipped **immediately**, without spending its
delay.

And why an empty ladder falls back
──────────────────────────────────
If the *whole* ladder reaches nobody, the incident falls back to the rule's own
channels. Attaching an escalation policy must never make an alert quieter than
attaching none — that would turn a configuration mistake into silence, which is
the one outcome an on-call tool may not produce.

Stopping
────────
Acknowledged, resolved, snoozed, silenced or inside a maintenance window: the
ladder stops and its state row goes away. The checks are delegated to the
existing helpers rather than reimplemented — ``dispatch_alert`` already refuses
silenced incidents, and duplicating that logic here is how the two would drift.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.core.config import get_settings
from whatisup.models.alert import AlertChannel, AlertRule
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.oncall import (
    EscalationLevel,
    EscalationPolicy,
    EscalationState,
    EscalationTargetType,
)
from whatisup.services.oncall import OnCallTarget, contacts_for_user, resolve_schedule_targets

logger = structlog.get_logger(__name__)


async def _ladder(db: AsyncSession, policy_id: uuid.UUID) -> list[EscalationLevel]:
    return list(
        (
            await db.execute(
                select(EscalationLevel)
                .where(EscalationLevel.policy_id == policy_id)
                .order_by(EscalationLevel.position)
            )
        )
        .scalars()
        .all()
    )


async def arm_escalation(
    db: AsyncSession,
    incident: Incident,
    rule: AlertRule,
    *,
    now: datetime | None = None,
) -> bool:
    """Start this incident on ``rule``'s ladder. True when a ladder was armed.

    Idempotent: an incident already escalating keeps the state it has. Several
    rules can match one incident, and the first one to arm owns the ladder —
    re-arming would restart it from L1 and page the first rung again.
    """
    now = now or datetime.now(UTC)
    if rule.escalation_policy_id is None:
        return False

    # Explicit pre-check rather than leaning on the unique constraint alone: the
    # IntegrityError path below has to roll back, and a bare `db.rollback()`
    # here would discard everything uncommitted in the session — including the
    # incident `fire_alerts` may have just created.
    already = (
        await db.execute(
            select(EscalationState.id).where(EscalationState.incident_id == incident.id).limit(1)
        )
    ).scalar_one_or_none()
    if already is not None:
        return True

    policy = (
        await db.execute(
            select(EscalationPolicy).where(EscalationPolicy.id == rule.escalation_policy_id)
        )
    ).scalar_one_or_none()
    if policy is None or not policy.enabled:
        return False

    levels = await _ladder(db, policy.id)
    if not levels:
        # A policy with no rungs is a configuration in progress, not an
        # instruction to stay silent: let the caller fan out to its channels.
        logger.warning(
            "escalation_policy_has_no_levels",
            policy_id=str(policy.id),
            incident_id=str(incident.id),
        )
        return False

    state = EscalationState(
        incident_id=incident.id,
        policy_id=policy.id,
        rule_id=rule.id,
        next_position=0,
        repeats_done=0,
        # The first rung's own delay still applies: `delay_minutes = 0` on L1
        # means "page immediately", anything else means "wait first".
        next_fire_at=now + timedelta(minutes=max(levels[0].delay_minutes, 0)),
    )
    # Nested transaction so a lost race rolls back *only* this insert. The
    # unique constraint stays the real guarantee — the pre-check above cannot
    # cover two replicas arming at the same instant.
    try:
        async with db.begin_nested():
            db.add(state)
            await db.flush()
    except IntegrityError:
        # Another rule matched the same incident first. Its ladder stands.
        return True

    logger.info(
        "escalation_armed",
        incident_id=str(incident.id),
        policy_id=str(policy.id),
        rungs=len(levels),
        first_fire_at=state.next_fire_at.isoformat(),
    )
    return True


async def _targets_for_level(
    db: AsyncSession, level: EscalationLevel, now: datetime
) -> tuple[list[AlertChannel], list[OnCallTarget]]:
    """Resolve one rung into things that can actually be delivered to."""
    if level.target_type is EscalationTargetType.channel:
        channel = (
            await db.execute(select(AlertChannel).where(AlertChannel.id == level.target_channel_id))
        ).scalar_one_or_none()
        return ([channel] if channel else []), []

    if level.target_type is EscalationTargetType.schedule:
        return [], await resolve_schedule_targets(db, level.target_schedule_id, now)

    return [], await contacts_for_user(db, level.target_user_id)


async def _page(
    db: AsyncSession,
    incident: Incident,
    monitor: Monitor,
    level: EscalationLevel,
    channels: list[AlertChannel],
    people: list[OnCallTarget],
) -> int:
    """Deliver one rung. Returns how many deliveries were attempted."""
    from whatisup.services.alert import dispatch_alert

    ctx = {
        "monitor_name": monitor.name,
        "monitor_url": monitor.url,
        "check_type": monitor.check_type,
        "escalation_level": level.position,
        "escalation_target": level.target_type.value,
    }

    sent = 0
    for channel in channels:
        await dispatch_alert(db, incident, channel, "incident_opened", ctx=ctx)
        sent += 1

    # A person is reached through the channel that carries their handle; the
    # transport itself is the one dispatch_alert already drives, so nothing new
    # is invented here.
    for target in people:
        if target.via_channel_id is None:
            # email / push — autonomous transports.
            await _page_person_directly(db, incident, monitor, target, ctx)
            sent += 1
            continue
        channel = (
            await db.execute(select(AlertChannel).where(AlertChannel.id == target.via_channel_id))
        ).scalar_one_or_none()
        if channel is None:
            logger.warning(
                "escalation_contact_channel_missing",
                incident_id=str(incident.id),
                user_id=str(target.user_id),
                method=target.method.value,
            )
            continue
        await dispatch_alert(
            db, incident, channel, "incident_opened", ctx={**ctx, "to": target.value}
        )
        sent += 1
    return sent


async def _page_person_directly(
    db: AsyncSession,
    incident: Incident,
    monitor: Monitor,
    target: OnCallTarget,
    ctx: dict,
) -> None:
    """Email / web push — transports that need no carrier channel."""
    from whatisup.services.web_push import dispatch_web_push_for_incident

    if target.method.value == "push":
        await dispatch_web_push_for_incident(db, incident, monitor, "incident_opened")
        return

    from whatisup.services.channels import CHANNEL_REGISTRY

    handler = CHANNEL_REGISTRY.get("email")
    if handler is None:
        return
    try:
        await handler.send(
            incident,
            None,
            "incident_opened",
            {**ctx, "monitor_name": monitor.name},
            {"to": [target.value]},
            get_settings(),
        )
    except Exception as exc:  # noqa: BLE001 - one unreachable person must not stop the ladder
        logger.warning(
            "escalation_direct_page_failed",
            incident_id=str(incident.id),
            user_id=str(target.user_id),
            method=target.method.value,
            error=type(exc).__name__,
        )


async def _should_stop(db: AsyncSession, incident: Incident, monitor: Monitor, now: datetime):
    """Reason to stop escalating, or None. Delegates rather than reimplements."""
    from whatisup.services.maintenance import is_in_maintenance

    if incident.resolved_at is not None:
        return "resolved"
    if incident.acked_at is not None:
        return "acknowledged"
    snooze = incident.snooze_until
    if snooze is not None:
        if snooze.tzinfo is None:  # SQLite hands back naive datetimes
            snooze = snooze.replace(tzinfo=UTC)
        if snooze > now:
            return "snoozed"
    if await is_in_maintenance(db, monitor.id, monitor.group_id):
        return "maintenance"
    return None


async def _fallback_to_rule_channels(
    db: AsyncSession, incident: Incident, monitor: Monitor, rule_id: uuid.UUID | None
) -> None:
    """Page the rule's own channels when the whole ladder reached nobody.

    Attaching a policy must never make an alert quieter than attaching none.
    """
    if rule_id is None:
        return
    rule = (
        await db.execute(
            select(AlertRule)
            .where(AlertRule.id == rule_id)
            .options(selectinload(AlertRule.channels))
        )
    ).scalar_one_or_none()
    if rule is None or not rule.channels:
        return

    from whatisup.services.alert import dispatch_alert

    logger.warning(
        "escalation_ladder_reached_nobody_falling_back",
        incident_id=str(incident.id),
        rule_id=str(rule_id),
        channels=len(rule.channels),
    )
    ctx = {
        "monitor_name": monitor.name,
        "monitor_url": monitor.url,
        "check_type": monitor.check_type,
        "escalation_fallback": True,
    }
    for channel in rule.channels:
        await dispatch_alert(db, incident, channel, "incident_opened", ctx=ctx)


async def _advance(db: AsyncSession, state: EscalationState, levels, now: datetime) -> bool:
    """Move to the next rung, replaying the ladder if the policy repeats.

    Returns False when the ladder is finished for good — the caller then drops
    the state and lets ``renotify`` take over, which is the historical behaviour
    for an incident nobody acknowledges.
    """
    state.next_position += 1
    if state.next_position < len(levels):
        state.next_fire_at = now + timedelta(
            minutes=max(levels[state.next_position].delay_minutes, 0)
        )
        return True

    policy = await db.get(EscalationPolicy, state.policy_id)
    if policy is not None and state.repeats_done < policy.repeat_count:
        state.repeats_done += 1
        state.next_position = 0
        state.next_fire_at = now + timedelta(minutes=max(levels[0].delay_minutes, 0))
        return True
    return False


async def run_due_escalations(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Fire every rung whose turn has come. Returns how many rungs fired.

    Capped per tick (``escalation_max_states_per_run``), oldest-due first —
    after a prolonged Redis outage or a leader-election gap, every rung whose
    ``next_fire_at`` came due while nobody ran this loop shows up at once.
    Ordering by ``next_fire_at`` ascending and capping the batch means the
    most overdue rungs fire first and get a fresh (future) ``next_fire_at``
    from ``_advance``/deletion, so whatever doesn't fit this tick is simply
    the next-most-overdue batch next tick — nothing is skipped.
    """
    now = now or datetime.now(UTC)
    settings = get_settings()
    max_per_run = settings.escalation_max_states_per_run

    states = list(
        (
            await db.execute(
                select(EscalationState)
                .where(EscalationState.next_fire_at <= now)
                .options(selectinload(EscalationState.incident))
                .order_by(EscalationState.next_fire_at.asc())
                .limit(max_per_run)
            )
        )
        .scalars()
        .all()
    )
    if not states:
        return 0
    if len(states) >= max_per_run:
        logger.warning(
            "escalation_run_capped",
            max_per_run=max_per_run,
            hint="backlog exceeds the per-tick cap — remainder deferred to next tick",
        )

    fired = 0
    for state in states:
        try:
            fired += await _run_one(db, state, now)
            await db.commit()
        except Exception:
            # Commit per state, for the same reason as the renotify loop: one
            # failing incident must not roll back the pages already delivered
            # for the others in this tick.
            await db.rollback()
            logger.exception("escalation_state_failed", incident_id=str(state.incident_id))
    return fired


async def _run_one(db: AsyncSession, state: EscalationState, now: datetime) -> int:
    incident = state.incident
    if incident is None:
        await db.delete(state)
        return 0

    monitor = await db.get(Monitor, incident.monitor_id)
    if monitor is None or not monitor.enabled:
        await db.delete(state)
        return 0

    stop = await _should_stop(db, incident, monitor, now)
    if stop is not None:
        logger.info(
            "escalation_stopped",
            incident_id=str(incident.id),
            reason=stop,
            at_position=state.next_position,
        )
        await db.delete(state)
        return 0

    levels = await _ladder(db, state.policy_id)
    if not levels:
        await db.delete(state)
        return 0

    fired = 0
    reached_anyone = False
    # Walk forward while rungs resolve to nobody: an unreachable rung must not
    # spend its delay, or a broken middle would double the time to the person
    # who is actually reachable.
    while state.next_position < len(levels):
        level = levels[state.next_position]
        channels, people = await _targets_for_level(db, level, now)
        if not channels and not people:
            logger.warning(
                "escalation_level_reaches_nobody",
                incident_id=str(incident.id),
                position=level.position,
                target_type=level.target_type.value,
            )
            if not await _advance(db, state, levels, now):
                break
            continue

        sent = await _page(db, incident, monitor, level, channels, people)
        state.last_fired_at = now
        fired += 1
        reached_anyone = reached_anyone or sent > 0
        logger.info(
            "escalation_level_fired",
            incident_id=str(incident.id),
            position=level.position,
            target_type=level.target_type.value,
            deliveries=sent,
        )
        if not await _advance(db, state, levels, now):
            await db.delete(state)
        break
    else:
        # Ran off the end without firing anything.
        await db.delete(state)

    if not reached_anyone and fired == 0:
        await _fallback_to_rule_channels(db, incident, monitor, state.rule_id)

    await db.flush()
    return fired


async def cancel_escalation(db: AsyncSession, incident_id: uuid.UUID) -> None:
    """Drop a ladder outright — used when an incident resolves or is acked."""
    await db.execute(delete(EscalationState).where(EscalationState.incident_id == incident_id))


async def check_escalations() -> None:
    """Background-loop entry point (see lifespan in main.py)."""
    from whatisup.core.database import get_session_factory

    async with get_session_factory()() as db:
        await run_due_escalations(db)
