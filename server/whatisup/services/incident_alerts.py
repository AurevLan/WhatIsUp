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

from whatisup.models.alert import (
    METRIC_CONDITIONS,
    AlertCondition,
    AlertEvent,
    AlertEventStatus,
    AlertRule,
)
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult
from whatisup.models.team import TeamMembership
from whatisup.services.alert import dispatch_alert, maybe_digest_or_dispatch
from whatisup.services.alert_conditions import (
    above_baseline_matches,
    anomaly_matches,
    response_time_above_matches,
    schema_drift_matches,
    ssl_expiry_matches,
)

logger = structlog.get_logger(__name__)

#: Conditions whose verdict is read off a ``CheckResult``. They are unevaluable
#: when the caller has none (heartbeat, renotify, metric evaluator).
#: ``any_down`` / ``all_down`` are absent on purpose: they decide from the
#: incident's own scope, not from a result.
_RESULT_BACKED_CONDITIONS = frozenset(
    {
        AlertCondition.ssl_expiry,
        AlertCondition.response_time_above,
        AlertCondition.response_time_above_baseline,
        AlertCondition.anomaly_detection,
        AlertCondition.schema_drift,
    }
)


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

        # Every branch below reads `result`. Callers legitimately pass None —
        # the heartbeat checker, the renotify loop and the C-4 metric evaluator
        # all open or resolve incidents with no CheckResult in hand — and a
        # value-based condition simply cannot be evaluated without one. Before
        # this guard, a single `ssl_expiry` rule on a heartbeat monitor raised
        # AttributeError from inside the background loop.
        if result is None and rule.condition in _RESULT_BACKED_CONDITIONS:
            continue

        if rule.condition == AlertCondition.any_down:
            if event_type not in ("incident_opened", "incident_resolved"):
                continue
        elif rule.condition == AlertCondition.all_down:
            if incident.scope != IncidentScope.global_ and event_type == "incident_opened":
                continue
            if event_type not in ("incident_opened", "incident_resolved"):
                continue
        elif rule.condition == AlertCondition.ssl_expiry:
            if not ssl_expiry_matches(
                result.ssl_valid, result.ssl_days_remaining, monitor.ssl_expiry_warn_days
            ):
                continue
            if event_type != "incident_opened":
                continue
        elif rule.condition == AlertCondition.response_time_above:
            if not response_time_above_matches(result.response_time_ms, rule.threshold_value):
                continue
            if event_type != "incident_opened":
                continue
        elif rule.condition == AlertCondition.response_time_above_baseline:
            if event_type != "incident_opened":
                continue
            if rule.baseline_factor is None or result.response_time_ms is None:
                continue
            # 7-day rolling average — TODO: bucket by hour-of-week if needed
            baseline_cutoff = now - timedelta(days=7)
            baseline_row = (
                await db.execute(
                    select(func.avg(CheckResult.response_time_ms)).where(
                        CheckResult.monitor_id == monitor.id,
                        CheckResult.checked_at >= baseline_cutoff,
                        CheckResult.response_time_ms.isnot(None),
                    )
                )
            ).scalar_one_or_none()
            if not above_baseline_matches(
                result.response_time_ms, baseline_row, rule.baseline_factor
            ):
                continue

        elif rule.condition == AlertCondition.anomaly_detection:
            if event_type != "incident_opened":
                continue
            if result.response_time_ms is None:
                continue
            # zscore is pre-computed by process_check_result and injected into ctx
            if not anomaly_matches(ctx.get("zscore"), rule.anomaly_zscore_threshold):
                continue
            ctx = {**ctx, "response_time_ms": result.response_time_ms}

        elif rule.condition == AlertCondition.schema_drift:
            if event_type != "incident_opened":
                continue
            if not schema_drift_matches(result.schema_fingerprint, monitor.schema_baseline):
                continue
            ctx = {
                **ctx,
                "schema_fingerprint": result.schema_fingerprint,
                "schema_baseline": monitor.schema_baseline,
            }

        elif rule.condition in METRIC_CONDITIONS:
            # Matching already happened in ``services/metric_alerts.py``, which
            # is the only thing that can see the sample series and which encoded
            # its verdict by opening (or resolving) this very incident. Nothing
            # left to decide here; the values are in ``extra_ctx``.
            if event_type not in ("incident_opened", "incident_resolved"):
                continue

        for channel in rule.channels:
            await maybe_digest_or_dispatch(db, incident, channel, rule, event_type, ctx=ctx)

    await db.flush()
