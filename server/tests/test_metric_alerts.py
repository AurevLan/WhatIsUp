"""Alerting on pushed metrics (plan V2, C-4).

Three things are worth testing here, in order of how badly they would hurt:

1. that a metric incident cannot masquerade as an outage — the whole reason
   ``Incident.alert_rule_id`` exists;
2. that the evaluator opens and resolves on evidence and only on evidence;
3. that ``simulate_rule`` (the UI preview) agrees with what would actually fire,
   which every previous condition got wrong at least once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertCondition, AlertRule
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.alert import simulate_rule
from whatisup.services.alert_conditions import (
    metric_above_matches,
    metric_absent_matches,
    metric_below_matches,
)
from whatisup.services.metric_alerts import evaluate_metric_alerts
from whatisup.services.metric_ingest import IngestPoint, ingest_points

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


async def _push(
    db: AsyncSession,
    monitor: Monitor,
    name: str,
    value: float,
    at: datetime,
    labels: dict[str, str] | None = None,
) -> None:
    """Push through the real ingestion path.

    Deliberately not a hand-built ``CustomMetric``: since C-1 the evaluator
    resolves series through the ``metric_series`` registry, which only ingestion
    populates. A fixture that inserted points directly would leave the registry
    empty and every one of these tests would pass against an evaluator that can
    no longer see anything.
    """
    await ingest_points(
        db,
        monitor.id,
        [
            IngestPoint(
                metric_name=name,
                value=value,
                unit=None,
                labels=labels or {},
                pushed_at=at,
            )
        ],
    )


async def _rule(
    db: AsyncSession,
    monitor: Monitor,
    user: User,
    condition: AlertCondition,
    *,
    metric_name: str = "queue_depth",
    threshold: float | None = 100.0,
    window: int | None = 300,
    min_duration: int = 0,
) -> AlertRule:
    rule = AlertRule(
        owner_id=user.id,
        monitor_id=monitor.id,
        condition=condition,
        metric_name=metric_name,
        threshold_value=threshold,
        metric_window_seconds=window,
        min_duration_seconds=min_duration,
    )
    db.add(rule)
    await db.flush()
    return rule


async def _open_incidents(db: AsyncSession, monitor: Monitor) -> list[Incident]:
    return list(
        (
            await db.execute(
                select(Incident).where(
                    Incident.monitor_id == monitor.id, Incident.resolved_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )


# ── Pure predicates ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "threshold", "expected"),
    [
        (150.0, 100.0, True),
        (100.0, 100.0, False),  # strictly above
        (50.0, 100.0, False),
        (None, 100.0, False),  # silence is metric_absent's job
        (150.0, None, False),  # unset threshold never fires
    ],
)
async def test_metric_above_predicate(value, threshold, expected):
    assert metric_above_matches(value, threshold) is expected


@pytest.mark.parametrize(
    ("value", "threshold", "expected"),
    [
        (50.0, 100.0, True),
        (100.0, 100.0, False),
        (150.0, 100.0, False),
        # The one that matters: a dead agent must not read as a cache hit rate
        # of zero and page the "below" rule.
        (None, 100.0, False),
    ],
)
async def test_metric_below_predicate(value, threshold, expected):
    assert metric_below_matches(value, threshold) is expected


@pytest.mark.parametrize(
    ("value", "ever", "expected"),
    [
        (None, True, True),
        (None, False, False),  # a typo'd metric name must stay quiet forever
        (42.0, True, False),
    ],
)
async def test_metric_absent_predicate(value, ever, expected):
    assert metric_absent_matches(value, ever) is expected


# ── Evaluator ─────────────────────────────────────────────────────────────────


async def test_opens_then_resolves_on_evidence(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    rule = await _rule(service_db, test_monitor, test_user, AlertCondition.metric_above)

    await _push(service_db, test_monitor, "queue_depth", 150.0, NOW - timedelta(seconds=30))
    assert await evaluate_metric_alerts(service_db, now=NOW) == 1

    (incident,) = await _open_incidents(service_db, test_monitor)
    assert incident.alert_rule_id == rule.id
    assert incident.trigger_kind == "metric_above"

    # Idempotent while the breach lasts — no second incident, no re-alert.
    assert await evaluate_metric_alerts(service_db, now=NOW + timedelta(seconds=60)) == 0

    later = NOW + timedelta(seconds=120)
    await _push(service_db, test_monitor, "queue_depth", 10.0, later - timedelta(seconds=5))
    assert await evaluate_metric_alerts(service_db, now=later) == 1
    assert await _open_incidents(service_db, test_monitor) == []


async def test_silence_does_not_resolve_an_open_metric_incident(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    """A metric that went quiet is not a metric that recovered."""
    await _rule(service_db, test_monitor, test_user, AlertCondition.metric_above)
    await _push(service_db, test_monitor, "queue_depth", 150.0, NOW - timedelta(seconds=30))
    await evaluate_metric_alerts(service_db, now=NOW)
    assert len(await _open_incidents(service_db, test_monitor)) == 1

    # Far beyond the freshness window, with no new sample at all.
    await evaluate_metric_alerts(service_db, now=NOW + timedelta(hours=2))
    assert len(await _open_incidents(service_db, test_monitor)) == 1


async def test_stale_value_does_not_keep_firing(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    """A breaching sample older than the window must not open anything."""
    await _rule(service_db, test_monitor, test_user, AlertCondition.metric_above, window=60)
    await _push(service_db, test_monitor, "queue_depth", 150.0, NOW - timedelta(seconds=600))
    assert await evaluate_metric_alerts(service_db, now=NOW) == 0
    assert await _open_incidents(service_db, test_monitor) == []


async def test_metric_absent_fires_only_for_a_series_that_existed(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    typo = await _rule(
        service_db,
        test_monitor,
        test_user,
        AlertCondition.metric_absent,
        metric_name="quue_depth",
        threshold=None,
        window=60,
    )
    assert await evaluate_metric_alerts(service_db, now=NOW) == 0
    assert await _open_incidents(service_db, test_monitor) == []

    # Same rule, once the series has actually been written and then gone quiet.
    typo.metric_name = "queue_depth"
    await service_db.flush()
    await _push(service_db, test_monitor, "queue_depth", 1.0, NOW - timedelta(seconds=600))
    assert await evaluate_metric_alerts(service_db, now=NOW) == 1

    # And it clears as soon as a sample lands again.
    resumed = NOW + timedelta(seconds=30)
    await _push(service_db, test_monitor, "queue_depth", 1.0, resumed)
    assert await evaluate_metric_alerts(service_db, now=resumed) == 1
    assert await _open_incidents(service_db, test_monitor) == []


async def test_min_duration_measures_the_breach_not_the_sampling(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    """One bad value must not satisfy a 120 s minimum just by being alone."""
    await _rule(
        service_db,
        test_monitor,
        test_user,
        AlertCondition.metric_above,
        window=600,
        min_duration=120,
    )
    await _push(service_db, test_monitor, "queue_depth", 10.0, NOW - timedelta(seconds=300))
    await _push(service_db, test_monitor, "queue_depth", 150.0, NOW - timedelta(seconds=30))
    assert await evaluate_metric_alerts(service_db, now=NOW) == 0

    # Still breaching two minutes later: now it counts, and the incident is
    # backdated to the first breaching sample rather than to "now".
    later = NOW + timedelta(seconds=120)
    await _push(service_db, test_monitor, "queue_depth", 150.0, later - timedelta(seconds=10))
    assert await evaluate_metric_alerts(service_db, now=later) == 1
    (incident,) = await _open_incidents(service_db, test_monitor)
    assert incident.started_at.replace(tzinfo=UTC) == NOW - timedelta(seconds=30)


async def test_two_metric_rules_on_one_monitor_both_fire(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    """The reason the unique index had to become per (monitor, rule)."""
    await _rule(service_db, test_monitor, test_user, AlertCondition.metric_above)
    await _rule(
        service_db,
        test_monitor,
        test_user,
        AlertCondition.metric_below,
        metric_name="cache_hit_pct",
        threshold=80.0,
    )
    await _push(service_db, test_monitor, "queue_depth", 150.0, NOW - timedelta(seconds=10))
    await _push(service_db, test_monitor, "cache_hit_pct", 12.0, NOW - timedelta(seconds=10))

    assert await evaluate_metric_alerts(service_db, now=NOW) == 2
    assert len(await _open_incidents(service_db, test_monitor)) == 2


async def test_disabled_rule_and_disabled_monitor_are_skipped(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    rule = await _rule(service_db, test_monitor, test_user, AlertCondition.metric_above)
    rule.enabled = False
    await service_db.flush()
    await _push(service_db, test_monitor, "queue_depth", 150.0, NOW - timedelta(seconds=10))
    assert await evaluate_metric_alerts(service_db, now=NOW) == 0

    rule.enabled = True
    test_monitor.enabled = False
    await service_db.flush()
    assert await evaluate_metric_alerts(service_db, now=NOW) == 0


# ── The masking regression this whole design exists to prevent ────────────────


async def test_open_metric_incident_does_not_mask_a_real_outage(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User, test_probe: Probe
):
    """A down check must still open its own incident and fire its own alert.

    Before ``Incident.alert_rule_id``, the metric incident would have been found
    by ``process_check_result``'s ``scalar_one_or_none()`` as *the* open incident
    for the monitor: the outage would have opened none, sent no
    ``incident_opened``, and been recorded as having started when the metric
    breached.
    """
    from whatisup.services.incident import process_check_result

    await _rule(service_db, test_monitor, test_user, AlertCondition.metric_above)
    await _push(service_db, test_monitor, "queue_depth", 150.0, NOW - timedelta(seconds=10))
    await evaluate_metric_alerts(service_db, now=NOW)
    metric_incident = (await _open_incidents(service_db, test_monitor))[0]

    result = CheckResult(
        monitor_id=test_monitor.id,
        probe_id=test_probe.id,
        status=CheckStatus.down,
        checked_at=datetime.now(UTC),
    )
    service_db.add(result)
    await service_db.flush()

    events: list[dict] = []

    async def publish_event(payload):
        events.append(payload)

    await process_check_result(service_db, result, publish_event)

    open_now = await _open_incidents(service_db, test_monitor)
    assert len(open_now) == 2, "the outage must get its own incident"
    availability = [i for i in open_now if i.alert_rule_id is None]
    assert len(availability) == 1
    assert availability[0].id != metric_incident.id
    assert any(e.get("type") == "incident_opened" for e in events)


async def test_availability_endpoints_ignore_metric_incidents(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    """`IS_AVAILABILITY_INCIDENT` in practice: an up monitor stays up."""
    from whatisup.models.incident import IS_AVAILABILITY_INCIDENT

    await _rule(service_db, test_monitor, test_user, AlertCondition.metric_above)
    await _push(service_db, test_monitor, "queue_depth", 150.0, NOW - timedelta(seconds=10))
    await evaluate_metric_alerts(service_db, now=NOW)

    down = (
        (
            await service_db.execute(
                select(Incident.monitor_id).where(
                    Incident.monitor_id == test_monitor.id,
                    Incident.resolved_at.is_(None),
                    IS_AVAILABILITY_INCIDENT,
                )
            )
        )
        .scalars()
        .all()
    )
    assert down == []


# ── Preview / dispatch parity ─────────────────────────────────────────────────


async def test_simulate_agrees_with_the_evaluator(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    rule = await _rule(service_db, test_monitor, test_user, AlertCondition.metric_above)

    # Nothing pushed: neither side fires.
    assert (await simulate_rule(service_db, rule))["would_fire"] is False
    assert await evaluate_metric_alerts(service_db, now=datetime.now(UTC)) == 0

    # Breaching now: both sides agree.
    await _push(service_db, test_monitor, "queue_depth", 150.0, datetime.now(UTC))
    assert (await simulate_rule(service_db, rule))["would_fire"] is True
    assert await evaluate_metric_alerts(service_db, now=datetime.now(UTC)) == 1


async def test_simulate_reports_an_unusable_rule_rather_than_a_silent_false(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    rule = await _rule(
        service_db, test_monitor, test_user, AlertCondition.metric_above, threshold=None
    )
    out = await simulate_rule(service_db, rule)
    assert out["would_fire"] is False
    assert "Seuil" in out["reason"]

    rule.metric_name = None
    await service_db.flush()
    out = await simulate_rule(service_db, rule)
    assert out["would_fire"] is False
    assert "métrique" in out["reason"].lower()


# ── Per-tick batch cap (architecture hardening) ────────────────────────────────


async def test_evaluate_metric_alerts_caps_batch_and_defers_the_rest(
    service_db: AsyncSession, test_user: User, monkeypatch
):
    """A tenant with more enabled metric rules than the per-tick cap must not
    have the tail silently dropped: capped this tick, and evaluated as soon
    as a slot frees up (here: one of the already-evaluated rules is
    disabled). Unlike `escalation`'s `next_fire_at` or `heartbeat`'s
    `last_heartbeat_at`, an `AlertRule` carries no timestamp this loop could
    use to naturally rotate priority while every rule stays enabled — the
    per-tick order is a plain, deterministic `id` sort, and the fairness
    guarantee is only "not lost while capacity is exceeded", not "every rule
    gets an equal share of every tick"."""
    from whatisup.core.config import get_settings

    monkeypatch.setattr(get_settings(), "metric_alerts_max_rules_per_run", 2)

    monitors = []
    rules = []
    for i in range(3):
        monitor = Monitor(name=f"mon-{i}", url=f"http://example.com/{i}", owner_id=test_user.id)
        service_db.add(monitor)
        await service_db.flush()
        rule = await _rule(service_db, monitor, test_user, AlertCondition.metric_above)
        await _push(service_db, monitor, "queue_depth", 150.0, NOW - timedelta(seconds=30))
        monitors.append(monitor)
        rules.append(rule)

    # Batch order is `AlertRule.id` ascending — discover it rather than assume
    # creation order, since the PK is a random UUID.
    ordered_ids = (
        (await service_db.execute(select(AlertRule.id).order_by(AlertRule.id))).scalars().all()
    )
    rule_by_id = {r.id: r for r in rules}
    monitor_by_rule_id = {r.id: m for r, m in zip(rules, monitors, strict=True)}
    ordered_monitors = [monitor_by_rule_id[rid] for rid in ordered_ids]

    changed = await evaluate_metric_alerts(service_db, now=NOW)
    assert changed == 2
    assert len(await _open_incidents(service_db, ordered_monitors[0])) == 1
    assert len(await _open_incidents(service_db, ordered_monitors[1])) == 1
    assert await _open_incidents(service_db, ordered_monitors[2]) == []  # deferred, not lost

    # Free a slot: disable one of the two rules already evaluated this tick.
    rule_by_id[ordered_ids[0]].enabled = False
    await service_db.flush()

    changed = await evaluate_metric_alerts(service_db, now=NOW)
    assert changed == 1
    assert len(await _open_incidents(service_db, ordered_monitors[2])) == 1
