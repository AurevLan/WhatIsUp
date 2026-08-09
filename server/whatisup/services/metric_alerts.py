"""Alerting on pushed application metrics (plan V2, C-4).

Until this module, ``custom_metrics`` was write-and-look-at: an application could
push ``queue_depth`` every ten seconds and draw a graph, but no alert condition
could see the series, so nothing ever fired. The three conditions added in C-4
(``metric_above`` / ``metric_below`` / ``metric_absent``) are evaluated here.

Why a background loop rather than the ingestion endpoint
────────────────────────────────────────────────────────
Firing an alert means an outbound HTTP call to a channel. Doing that inside
``POST /metrics/{monitor_id}`` would put a third-party webhook's latency on the
push path, so a slow Slack would throttle the agent — and C-1's batch ingestion
would make that worse, not better. The loop's interval is therefore the
worst-case alerting delay, and that is a deliberate trade (see
``metric_alerts_interval_seconds``).

Why these incidents are a separate population
─────────────────────────────────────────────
The alert pipeline is anchored on ``Incident``, so a metric breach has to open
one. It is tagged with ``Incident.alert_rule_id`` and every query meaning "is
this monitor down?" filters it out — see ``IS_AVAILABILITY_INCIDENT``. Without
that split an open metric incident would be picked up by ``process_check_result``
as *the* open incident and a real outage would open none.

Sustained breach, without any stored state
──────────────────────────────────────────
``min_duration_seconds`` is honoured by *asking the samples*, not by remembering
anything between runs: the breach started right after the most recent sample that
contradicts the condition, and it counts as sustained once that start is at least
``min_duration_seconds`` old. The incident's ``started_at`` is backdated to it,
which is both truthful for MTTD and what makes ``fire_alerts``' own
``min_duration_seconds`` gate pass instead of silently swallowing the very alert
it was asked to delay.

Asymmetry on purpose: silence never resolves
────────────────────────────────────────────
``metric_above`` / ``metric_below`` open on evidence and resolve on evidence. If
the agent stops pushing while an incident is open, the incident stays open — a
metric that went quiet is not a metric that recovered, and auto-resolving on
silence is how a monitoring system tells you everything is fine right when it has
stopped being able to tell.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.models.alert import METRIC_CONDITIONS, AlertCondition, AlertRule
from whatisup.models.custom_metric import CustomMetric
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.services.alert_conditions import (
    DEFAULT_METRIC_WINDOW_SECONDS,
    metric_above_matches,
    metric_absent_matches,
    metric_below_matches,
)
from whatisup.services.maintenance import is_in_maintenance

logger = structlog.get_logger(__name__)

#: How far back "has this series ever existed?" looks when deciding whether an
#: absence is worth paging about. Unbounded, the question would scan every
#: partition of ``custom_metrics`` (C-2) on every run for every silent metric.
#: It also gives the right product answer: a name nobody has written in a month
#: is a decommissioned metric, not one that just stopped.
EVER_PUSHED_HORIZON = timedelta(days=30)


def _window_seconds(rule: AlertRule) -> int:
    return rule.metric_window_seconds or DEFAULT_METRIC_WINDOW_SECONDS


def _matches(condition: AlertCondition, value: float | None, rule: AlertRule, ever: bool) -> bool:
    if condition is AlertCondition.metric_above:
        return metric_above_matches(value, rule.threshold_value)
    if condition is AlertCondition.metric_below:
        return metric_below_matches(value, rule.threshold_value)
    return metric_absent_matches(value, ever)


async def _latest_sample(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    metric_name: str,
    cutoff: datetime,
    now: datetime,
) -> tuple[float, datetime] | None:
    """Most recent sample inside ``[cutoff, now]``, or None when the series is stale."""
    row = (
        await db.execute(
            select(CustomMetric.value, CustomMetric.pushed_at)
            .where(
                CustomMetric.monitor_id == monitor_id,
                CustomMetric.metric_name == metric_name,
                CustomMetric.pushed_at >= cutoff,
                # Bounded above as well: a client is free to send a pushed_at in
                # the future, and one such row would otherwise pin this query's
                # answer forever.
                CustomMetric.pushed_at <= now,
            )
            .order_by(CustomMetric.pushed_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    pushed_at = row.pushed_at
    if pushed_at.tzinfo is None:  # SQLite hands back naive datetimes
        pushed_at = pushed_at.replace(tzinfo=UTC)
    return float(row.value), pushed_at


async def _ever_pushed(db: AsyncSession, monitor_id: uuid.UUID, metric_name: str, now: datetime):
    """True when the series was written at least once inside the horizon.

    This is the guard that keeps a typo in ``metric_name`` from paging forever:
    a series nobody ever wrote is not a series that stopped reporting.
    """
    return (
        await db.execute(
            select(CustomMetric.id)
            .where(
                CustomMetric.monitor_id == monitor_id,
                CustomMetric.metric_name == metric_name,
                CustomMetric.pushed_at >= now - EVER_PUSHED_HORIZON,
                CustomMetric.pushed_at <= now,
            )
            .limit(1)
        )
    ).first() is not None


async def _sustained_since(
    db: AsyncSession,
    rule: AlertRule,
    monitor_id: uuid.UUID,
    now: datetime,
) -> datetime | None:
    """When the current breach started, or None if it has not lasted long enough.

    ``now`` when the rule asks for no minimum duration. Otherwise: find the most
    recent sample that *contradicts* the condition, take the first breaching
    sample after it, and require that one to be at least ``min_duration_seconds``
    old.

    The obvious cheaper test — "every sample in the last ``min_duration`` breaches"
    — is wrong: it passes the moment a single breaching sample lands inside an
    otherwise empty range, so a 60 s minimum would page on the first bad value
    from an agent that pushes every 5 min. Anchoring on the last good sample
    instead measures the breach, not the sampling.

    Lookback is bounded at ``min_duration + window``: samples are at most one
    freshness window apart by construction, so that range always contains either
    a contradicting sample or a breaching one old enough to decide.

    ``metric_absent`` never comes here — its "samples" are the absence of rows,
    so the caller folds ``min_duration_seconds`` into the window instead.
    """
    if rule.min_duration_seconds <= 0:
        return now

    horizon = now - timedelta(seconds=rule.min_duration_seconds + _window_seconds(rule))
    if rule.condition is AlertCondition.metric_above:
        contradicts = CustomMetric.value <= rule.threshold_value
    else:
        contradicts = CustomMetric.value >= rule.threshold_value

    in_range = (
        CustomMetric.monitor_id == monitor_id,
        CustomMetric.metric_name == rule.metric_name,
        CustomMetric.pushed_at >= horizon,
        CustomMetric.pushed_at <= now,
    )

    last_ok = (
        await db.execute(select(func.max(CustomMetric.pushed_at)).where(*in_range, contradicts))
    ).scalar_one_or_none()

    breach_q = select(func.min(CustomMetric.pushed_at)).where(*in_range, ~contradicts)
    if last_ok is not None:
        breach_q = breach_q.where(CustomMetric.pushed_at > last_ok)
    first_breach = (await db.execute(breach_q)).scalar_one_or_none()

    if first_breach is None:
        return None
    if first_breach.tzinfo is None:  # SQLite hands back naive datetimes
        first_breach = first_breach.replace(tzinfo=UTC)
    if (now - first_breach).total_seconds() < rule.min_duration_seconds:
        return None
    return first_breach


async def _open_incident_for_rule(
    db: AsyncSession, monitor_id: uuid.UUID, rule_id: uuid.UUID
) -> Incident | None:
    return (
        await db.execute(
            select(Incident).where(
                Incident.monitor_id == monitor_id,
                Incident.alert_rule_id == rule_id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _evaluate_rule(db: AsyncSession, rule: AlertRule, monitor: Monitor, now: datetime) -> int:
    """Open or resolve this rule's incident for one monitor. Returns 1 on change."""
    from whatisup.services.incident_alerts import fire_alerts

    window = _window_seconds(rule)
    cutoff = now - timedelta(seconds=window)
    if rule.condition is AlertCondition.metric_absent:
        # An absence has no samples to inspect, so a minimum duration can only
        # mean "absent for that much longer" — folding it into the window is
        # exactly that, and keeps one code path instead of two.
        cutoff -= timedelta(seconds=max(rule.min_duration_seconds, 0))

    sample = await _latest_sample(db, monitor.id, rule.metric_name, cutoff, now)
    value = sample[0] if sample else None

    ever = False
    if rule.condition is AlertCondition.metric_absent and sample is None:
        ever = await _ever_pushed(db, monitor.id, rule.metric_name, now)

    matched = _matches(rule.condition, value, rule, ever)
    existing = await _open_incident_for_rule(db, monitor.id, rule.id)

    if matched and existing is None:
        if rule.condition is AlertCondition.metric_absent:
            started_at = cutoff
        else:
            started_at = await _sustained_since(db, rule, monitor.id, now)
            if started_at is None:
                return 0  # breaching, but not for long enough yet
        if await is_in_maintenance(db, monitor.id, monitor.group_id):
            return 0
        return await _open(db, rule, monitor, started_at, value, now, fire_alerts)

    if not matched and existing is not None and sample is not None:
        # `sample is not None` is the "on evidence" part, and it is load-bearing
        # rather than redundant: once the agent goes quiet, `value` is None and
        # every threshold predicate answers False, so testing `not matched`
        # alone would resolve the incident on silence — announcing recovery at
        # the exact moment the system stopped being able to observe anything.
        # For metric_absent the same test reads naturally: it is False precisely
        # because a sample came back.
        return await _resolve(db, rule, monitor, existing, value, now, fire_alerts)

    return 0


async def _open(db, rule, monitor, started_at, value, now, fire_alerts) -> int:
    incident = Incident(
        monitor_id=monitor.id,
        alert_rule_id=rule.id,
        started_at=started_at,
        first_failure_at=started_at,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
        trigger_kind=rule.condition.value,
    )
    db.add(incident)
    try:
        await db.flush()
    except IntegrityError:
        # Another replica won the race despite the leader lock (or the lock
        # lapsed mid-run). The partial unique index is the real guarantee.
        await db.rollback()
        logger.info(
            "metric_incident_deduplicated",
            monitor_id=str(monitor.id),
            rule_id=str(rule.id),
        )
        return 0

    logger.warning(
        "metric_alert_opened",
        monitor_id=str(monitor.id),
        rule_id=str(rule.id),
        incident_id=str(incident.id),
        condition=rule.condition.value,
        metric_name=rule.metric_name,
        value=value,
        threshold=rule.threshold_value,
    )
    await fire_alerts(
        db,
        incident,
        monitor,
        None,
        "incident_opened",
        extra_ctx=_ctx(rule, value, now),
    )
    return 1


async def _resolve(db, rule, monitor, incident, value, now, fire_alerts) -> int:
    started_at = incident.started_at
    if started_at.tzinfo is None:  # SQLite hands back naive datetimes
        started_at = started_at.replace(tzinfo=UTC)
    incident.resolved_at = now
    incident.duration_seconds = max(int((now - started_at).total_seconds()), 0)
    await db.flush()
    logger.info(
        "metric_alert_resolved",
        monitor_id=str(monitor.id),
        rule_id=str(rule.id),
        incident_id=str(incident.id),
        metric_name=rule.metric_name,
        value=value,
        duration_seconds=incident.duration_seconds,
    )
    await fire_alerts(
        db,
        incident,
        monitor,
        None,
        "incident_resolved",
        extra_ctx=_ctx(rule, value, now),
    )
    return 1


def _ctx(rule: AlertRule, value: float | None, now: datetime) -> dict:
    """Channel-message context. Mirrors the keys the other conditions inject."""
    return {
        "metric_name": rule.metric_name,
        "metric_value": value,
        "metric_threshold": rule.threshold_value,
        "metric_window_seconds": _window_seconds(rule),
        "metric_condition": rule.condition.value,
        "evaluated_at": now.isoformat(),
    }


async def evaluate_metric_alerts(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Evaluate every enabled pushed-metric rule. Returns the number of changes.

    ``now`` is injectable so tests can place samples on a fixed clock; the loop
    leaves it None.
    """
    now = now or datetime.now(UTC)

    rules = (
        (
            await db.execute(
                select(AlertRule)
                .where(
                    AlertRule.condition.in_(METRIC_CONDITIONS),
                    AlertRule.enabled.is_(True),
                    AlertRule.metric_name.isnot(None),
                    AlertRule.monitor_id.isnot(None),
                )
                .options(selectinload(AlertRule.monitor))
            )
        )
        .scalars()
        .all()
    )
    if not rules:
        return 0

    changed = 0
    for rule in rules:
        monitor = rule.monitor
        if monitor is None or not monitor.enabled:
            continue
        try:
            n = await _evaluate_rule(db, rule, monitor, now)
            # Commit per rule, for the same reason as the renotify loop: with a
            # single commit at the end, one failing rule's rollback would also
            # discard the incidents already opened for every rule processed
            # before it — and this loop is the only thing that will ever fire
            # these alerts, so what it drops is never retried.
            if n:
                await db.commit()
            changed += n
        except Exception:
            await db.rollback()
            logger.exception("metric_alert_rule_failed", rule_id=str(rule.id))
    return changed


async def check_metric_alerts() -> None:
    """Background-loop entry point (see lifespan in main.py)."""
    from whatisup.core.database import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        await evaluate_metric_alerts(db)
