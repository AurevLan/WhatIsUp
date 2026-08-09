"""Alert rule evaluation + channel dispatch for incidents.

``fire_alerts`` is the single entry point: caller hands an incident, monitor,
optional CheckResult and event type ("incident_opened" / "incident_resolved" /
"incident_renotify"); the function picks matching ``AlertRule`` rows and
dispatches via ``dispatch_alert`` / ``maybe_digest_or_dispatch``.

Web-push fan-out for monitor owners is handled here too — independent of rule
matching, so silenced rules don't suppress the owner's personal notification.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.models.alert import METRIC_CONDITIONS, AlertEvent, AlertEventStatus, AlertRule
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult
from whatisup.models.team import TeamMembership
from whatisup.services.alert import dispatch_alert, maybe_digest_or_dispatch
from whatisup.services.conditions import DispatchContext, get_handler
from whatisup.services.escalation import arm_escalation, cancel_escalation

logger = structlog.get_logger(__name__)


async def fire_alerts(
    db: AsyncSession,
    incident: Incident,
    monitor: Monitor,
    result: CheckResult | None = None,
    event_type: str = "incident_opened",
    extra_ctx: dict | None = None,
) -> None:
    """Evaluate alert rules for this monitor/group and dispatch matching ones.

    event_type values:
      - "incident_opened": new incident just opened
      - "incident_resolved": incident just resolved
      - "incident_renotify": incident still open, check for periodic re-notification
    """
    # F1: tag names are a global shared pool (Tag.name is unique across tenants),
    # so a tag_selector rule must be scoped to owners who can actually access the
    # monitor — otherwise any authenticated user could subscribe to another
    # tenant's outages by putting a common tag name (`prod`, …) in tag_selector.
    # "Can access" mirrors check_resource_access: the monitor owner plus every
    # member of the monitor's team.
    tag_owner_ids = {monitor.owner_id}
    if monitor.team_id is not None:
        member_ids = (
            (
                await db.execute(
                    select(TeamMembership.user_id).where(TeamMembership.team_id == monitor.team_id)
                )
            )
            .scalars()
            .all()
        )
        tag_owner_ids.update(member_ids)

    conditions = [AlertRule.monitor_id == monitor.id]
    if monitor.group_id:
        conditions.append(AlertRule.group_id == monitor.group_id)
    conditions.append(
        and_(
            AlertRule.tag_selector.isnot(None),
            AlertRule.owner_id.in_(tag_owner_ids),
        )
    )

    candidate_rules = (
        (
            await db.execute(
                select(AlertRule).where(or_(*conditions)).options(selectinload(AlertRule.channels))
            )
        )
        .scalars()
        .all()
    )

    monitor_tag_names = {t.name for t in (monitor.tags or [])}
    rules = [
        r
        for r in candidate_rules
        if r.monitor_id == monitor.id
        or (monitor.group_id is not None and r.group_id == monitor.group_id)
        or (
            r.tag_selector
            and r.owner_id in tag_owner_ids
            and monitor_tag_names.intersection(r.tag_selector)
        )
    ]

    # Web push + public status subscribers: outage-shaped notifications, so they
    # are for availability incidents only. Both say "this service went down" in
    # so many words, which a queue-depth threshold does not — and the public
    # subscribers are people outside the tenant, who have no business receiving
    # an internal application signal at all (C-4).
    if incident.alert_rule_id is None and event_type in ("incident_opened", "incident_resolved"):
        from whatisup.services.web_push import dispatch_web_push_for_incident

        await dispatch_web_push_for_incident(db, incident, monitor, event_type)

        # Abonnés de la page de statut publique. Branché ici et non sur chaque
        # site d'ouverture/résolution : `fire_alerts` est le point de passage
        # commun à tous les chemins (composite, ponctuel, promu, standard).
        # Indépendant des règles d'alerte — un abonné public n'en a aucune.
        from whatisup.services.status_subscription import notify_subscribers

        await notify_subscribers(db, monitor, resolved=event_type == "incident_resolved")

    # A resolved incident has no ladder to walk. Dropped here rather than only
    # in the loop so the state disappears at the moment of resolution, not up to
    # one tick later — and so a resolve that races a rung cannot page after it.
    if event_type == "incident_resolved":
        await cancel_escalation(db, incident.id)

    if not rules:
        return

    probe_names: dict[str, str] = {}
    if incident.affected_probe_ids:
        probe_uuids = []
        for pid in incident.affected_probe_ids:
            try:
                probe_uuids.append(uuid.UUID(pid))
            except ValueError:
                pass
        if probe_uuids:
            probes = (
                (await db.execute(select(Probe).where(Probe.id.in_(probe_uuids)))).scalars().all()
            )
            probe_names = {str(p.id): p.name for p in probes}

    ctx: dict = {
        "monitor_name": monitor.name,
        "monitor_url": monitor.url,
        "check_type": monitor.check_type,
        "probe_names": probe_names,
        **(extra_ctx or {}),
    }

    now = datetime.now(UTC)
    # C-4 — the two incident families never cross. A metric incident belongs to
    # exactly one rule and may only dispatch that rule (otherwise an `any_down`
    # rule on the same monitor would page "service down" for a queue-depth
    # threshold); conversely a metric rule is driven solely by
    # ``services/metric_alerts.py`` and must ignore every outage incident.
    metric_rule_id = incident.alert_rule_id

    for rule in rules:
        if not rule.enabled:
            continue

        if metric_rule_id is not None:
            if rule.id != metric_rule_id:
                continue
        elif rule.condition in METRIC_CONDITIONS:
            continue

        # H-10: min_duration_seconds — skip if incident too short for "opened" events
        if (
            event_type == "incident_opened"
            and rule.min_duration_seconds > 0
            and (now - incident.started_at).total_seconds() < rule.min_duration_seconds
        ):
            continue

        # H-11: renotify logic — only fire for renotify events if rule allows it
        if event_type == "incident_renotify":
            if not rule.renotify_after_minutes:
                continue
            if incident.acked_at is not None:
                continue
            # T1-04: skip renotify while a snooze window is still active.
            if incident.snooze_until is not None and incident.snooze_until > now:
                continue
            channel_ids = [c.id for c in rule.channels]
            if channel_ids:
                last_event = (
                    await db.execute(
                        select(AlertEvent)
                        .where(
                            AlertEvent.incident_id == incident.id,
                            AlertEvent.channel_id.in_(channel_ids),
                            AlertEvent.status == AlertEventStatus.sent,
                        )
                        .order_by(AlertEvent.sent_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if last_event:
                    minutes_since = (now - last_event.sent_at).total_seconds() / 60
                    if minutes_since < rule.renotify_after_minutes:
                        continue
            # Dispatch renotify directly (digest does not apply to renotify)
            for channel in rule.channels:
                await dispatch_alert(db, incident, channel, "incident_opened", ctx=ctx)
            continue

        # Storm protection: skip if too many alerts sent recently for this rule
        if rule.storm_window_seconds and rule.storm_max_alerts and event_type == "incident_opened":
            storm_cutoff = now - timedelta(seconds=rule.storm_window_seconds)
            channel_ids = [c.id for c in rule.channels]
            if channel_ids:
                recent_count = (
                    await db.execute(
                        select(func.count(AlertEvent.id)).where(
                            AlertEvent.incident_id == incident.id,
                            AlertEvent.status == AlertEventStatus.sent,
                            AlertEvent.sent_at >= storm_cutoff,
                        )
                    )
                ).scalar_one()
                if recent_count >= rule.storm_max_alerts:
                    logger.info(
                        "alert_storm_throttled",
                        rule_id=str(rule.id),
                        recent_count=recent_count,
                        storm_max=rule.storm_max_alerts,
                    )
                    continue

        # Per-condition logic lives in ``services/conditions``, next to the
        # preview it has to agree with — see that package's ``base.py`` for why.
        handler = get_handler(rule.condition)
        if handler is None:
            logger.warning("alert_condition_unhandled", condition=str(rule.condition))
            continue
        if event_type not in handler.fires_on:
            continue
        # Callers legitimately pass no CheckResult — the heartbeat checker, the
        # renotify loop and the C-4 metric evaluator all open or resolve
        # incidents without one, and a value-based condition simply cannot be
        # evaluated then. Before this guard existed, a single `ssl_expiry` rule
        # on a heartbeat monitor raised AttributeError inside a background loop.
        if result is None and handler.needs_check_result:
            continue

        decision = await handler.decide(
            DispatchContext(
                db=db,
                incident=incident,
                monitor=monitor,
                rule=rule,
                event_type=event_type,
                result=result,
                ctx=ctx,
            )
        )
        if not decision.fire:
            continue
        rule_ctx = {**ctx, **decision.ctx_extra} if decision.ctx_extra else ctx

        # B-1 — a rule carrying an escalation policy hands the incident to the
        # ladder instead of fanning out to its own channels. The ladder pages
        # different targets in order (L1, then L2 if nobody acked, then the
        # rotation), which is what `renotify` cannot do: it re-pages the same
        # channels. NULL policy keeps the historical behaviour untouched.
        #
        # Only on open: a resolution notice has nothing to escalate, and the
        # people already paged need to hear it on the channels they were paged
        # on — so it goes out through the normal fan-out.
        if (
            rule.escalation_policy_id is not None
            and event_type == "incident_opened"
            and await arm_escalation(db, incident, rule)
        ):
            continue

        for channel in rule.channels:
            await maybe_digest_or_dispatch(db, incident, channel, rule, event_type, ctx=rule_ctx)

    await db.flush()
