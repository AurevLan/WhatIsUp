"""V2 Global Health Engine — server-side aggregator (M1+M2).

Updates ``MonitorHealthState`` from each persisted CheckResult so SLO rules
can be evaluated against a fleet view rather than per-probe local decisions.

- M1: 5-minute percentiles + per-probe state + quorum ratio.
- M2: ``evaluate_slos`` calls ``services/slo`` evaluators after each ingest;
  monitors with ``health_engine_enabled=True`` then drive incidents through
  ``services.incident.open_incident_from_health`` /
  ``resolve_incident_for_slo`` instead of the legacy per-probe decider.
- M3: T-Digest long-window percentiles for ``quorum_slow``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import MonitorHealthState
from whatisup.models.result import CheckResult, CheckStatus

# structlog, not stdlib logging — the existing `logger.info("event", key=value)`
# calls below pass structlog-style kwargs, which plain `logging.Logger` methods
# don't accept (TypeError). Matches the convention used everywhere else in
# services/ (see core/logging.py).
logger = structlog.get_logger(__name__)

_FIVE_MIN = timedelta(minutes=5)
_DOWN_STATES = {CheckStatus.down.value, CheckStatus.timeout.value, CheckStatus.error.value}


async def ensure_state(db: AsyncSession, monitor_id) -> MonitorHealthState:
    """Get-or-create the MonitorHealthState row for a monitor."""
    state = (
        await db.execute(
            select(MonitorHealthState).where(MonitorHealthState.monitor_id == monitor_id)
        )
    ).scalar_one_or_none()
    if state is not None:
        return state
    state = MonitorHealthState(
        monitor_id=monitor_id,
        updated_at=datetime.now(UTC),
        probes_state={},
        probe_health={},
    )
    db.add(state)
    await db.flush()
    return state


def _percentiles(samples: Iterable[float], qs: tuple[float, ...]) -> list[float | None]:
    """Inclusive linear-interpolation percentiles for a small in-memory list."""
    sorted_samples = sorted(s for s in samples if s is not None)
    n = len(sorted_samples)
    if n == 0:
        return [None for _ in qs]
    if n == 1:
        return [sorted_samples[0] for _ in qs]
    out: list[float | None] = []
    for q in qs:
        rank = q * (n - 1)
        lo = int(rank)
        hi = min(lo + 1, n - 1)
        frac = rank - lo
        out.append(sorted_samples[lo] * (1 - frac) + sorted_samples[hi] * frac)
    return out


def _is_down(status: str) -> bool:
    return status in _DOWN_STATES


def _update_probe_view(state: MonitorHealthState, cr: CheckResult) -> None:
    """Merge one CheckResult into ``probes_state[probe_id]``."""
    if cr.probe_id is None:
        return
    pid = str(cr.probe_id)
    cur = dict(state.probes_state or {})
    prev = cur.get(pid, {})
    consecutive_down = (prev.get("consecutive_down", 0) + 1) if _is_down(cr.status.value) else 0
    cur[pid] = {
        "last_status": cr.status.value,
        "last_at": cr.checked_at.isoformat(),
        "consecutive_down": consecutive_down,
        "response_time_ms": cr.response_time_ms,
    }
    state.probes_state = cur


_DIVERGENCE_DOWN_WEIGHT = 0.10  # probe says down but fleet majority up
_DIVERGENCE_UP_WEIGHT = 0.05  # probe says up but fleet majority down (lighter)
_DIVERGENCE_DECAY_PER_HOUR = 0.05  # 5%/h decay so old divergences fade
_DIVERGENCE_FLEET_AGREEMENT = 0.7  # fraction of *other* probes needed for "majority"
_DIVERGENCE_MIN_OTHER_PROBES = 2  # need at least 2 peers to judge divergence


def _update_probe_divergence(state: MonitorHealthState, cr: CheckResult, now: datetime) -> None:
    """Per-probe divergence score — flags probes systematically out of sync.

    Compared at each ingest: the current probe's verdict vs the latest verdict
    of *other* fresh probes. A probe whose ``divergence_score`` exceeds 0.5 is
    excluded from the quorum count by ``services.slo`` (M5).
    """
    if cr.probe_id is None:
        return
    pid = str(cr.probe_id)
    others = [v for ppid, v in (state.probes_state or {}).items() if ppid != pid]
    if len(others) < _DIVERGENCE_MIN_OTHER_PROBES:
        return
    n_up = sum(1 for v in others if not _is_down(v.get("last_status", "")))
    n_down = sum(1 for v in others if _is_down(v.get("last_status", "")))
    sample_total = n_up + n_down
    if sample_total == 0:
        return
    fleet_up_ratio = n_up / sample_total

    health = dict(state.probe_health or {})
    entry = dict(health.get(pid) or {})
    score = float(entry.get("divergence_score") or 0.0)

    last_eval = entry.get("last_eval_at")
    if last_eval:
        try:
            dt = datetime.fromisoformat(last_eval)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            hours = max(0.0, (now - dt).total_seconds() / 3600.0)
            score = max(0.0, score * ((1.0 - _DIVERGENCE_DECAY_PER_HOUR) ** hours))
        except ValueError:
            pass

    is_cur_down = _is_down(cr.status.value)
    if is_cur_down and fleet_up_ratio >= _DIVERGENCE_FLEET_AGREEMENT:
        score = min(1.0, score + _DIVERGENCE_DOWN_WEIGHT)
    elif (not is_cur_down) and (1.0 - fleet_up_ratio) >= _DIVERGENCE_FLEET_AGREEMENT:
        score = min(1.0, score + _DIVERGENCE_UP_WEIGHT)

    health[pid] = {
        "divergence_score": round(score, 4),
        "samples": int(entry.get("samples") or 0) + 1,
        "last_eval_at": now.isoformat(),
    }
    state.probe_health = health


def _recompute_quorum(state: MonitorHealthState) -> None:
    """Quorum ratio = fraction of probes whose latest sample is in a down state.

    `current_scope` mirrors `IncidentScope` semantics: 'global' if all-down,
    'geographic' if some-but-not-all, None if everything is up.
    """
    probes = state.probes_state or {}
    if not probes:
        state.quorum_down_ratio = 0.0
        state.current_scope = None
        return
    total = len(probes)
    down = sum(1 for v in probes.values() if _is_down(v.get("last_status", "")))
    state.quorum_down_ratio = down / total
    if down == 0:
        state.current_scope = None
    elif down == total:
        state.current_scope = "global"
    else:
        state.current_scope = "geographic"


async def _refresh_5m_percentiles(
    db: AsyncSession, state: MonitorHealthState, now: datetime
) -> None:
    """Recompute exact p50/p95/p99 over the last 5 min from raw CheckResults."""
    cutoff = now - _FIVE_MIN
    samples = (
        (
            await db.execute(
                select(CheckResult.response_time_ms).where(
                    CheckResult.monitor_id == state.monitor_id,
                    CheckResult.checked_at >= cutoff,
                    CheckResult.response_time_ms.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    state.sample_count_5m = len(samples)
    p50, p95, p99 = _percentiles(samples, (0.50, 0.95, 0.99))
    state.p50_5m = p50
    state.p95_5m = p95
    state.p99_5m = p99


async def evaluate_slos(
    db: AsyncSession,
    monitor: Monitor,
    state: MonitorHealthState,
    publish_event,
    now: datetime | None = None,
) -> None:
    """Run every enabled SLO rule for the monitor and drive incident lifecycle.

    Imported lazily inside the function to avoid a circular import between
    ``services/incident`` and ``services/health``.
    """
    from whatisup.services import slo as slo_module
    from whatisup.services.incident import (
        open_incident_from_health,
        resolve_incident_for_slo,
    )

    now = now or datetime.now(UTC)
    rules = await slo_module.active_rules_for_monitor(db, monitor.id)
    if not rules:
        # Engine active + zero active SLORule = mute monitor: neither this
        # path nor the legacy per-probe decider (bypassed once
        # health_engine_enabled=True, see incident.process_check_result) can
        # ever open an incident for it. Monitor creation always provisions a
        # default rule (crud.py, plan Cap v2 4a) so this only fires when a
        # rule was disabled/deleted after the fact, or the flag was toggled
        # on by hand — CLAUDE.md "Health Engine V2" diagnostic pitfall #1.
        # Not auto-healed here: surfacing it beats guessing what the operator
        # wanted back.
        logger.warning("health_engine_no_active_rule", monitor_id=str(monitor.id))
        return
    for rule in rules:
        decision = slo_module.evaluate_rule(rule, state, now)
        if isinstance(decision, slo_module.Open):
            if await slo_module.in_cooldown(db, rule, now):
                logger.info(
                    "slo_open_skipped_cooldown",
                    monitor_id=str(monitor.id),
                    slo_rule_id=str(rule.id),
                    reason=decision.reason,
                )
                continue
            await open_incident_from_health(
                db,
                monitor=monitor,
                slo_rule_id=rule.id,
                trigger_kind=rule.rule_type.value,
                scope=decision.scope,
                affected_probe_ids=decision.affected_probe_ids,
                reason=decision.reason,
                publish_event=publish_event,
            )
        elif isinstance(decision, slo_module.Close):
            await resolve_incident_for_slo(
                db,
                monitor=monitor,
                slo_rule_id=rule.id,
                publish_event=publish_event,
                reason=decision.reason,
            )
        # Hold → no-op


async def ingest(
    db: AsyncSession,
    check_result: CheckResult,
    publish_event=None,
) -> None:
    """Update the monitor's health state from a freshly-persisted CheckResult.

    Called from the ``push_result`` background task after legacy incident
    processing — failure here must NOT bubble up to break ingest of the next
    check, so callers wrap in try/except + log.

    When the monitor opts into the Global Health Engine
    (``health_engine_enabled=True``) and ``publish_event`` is provided,
    enabled :class:`SLORule` rows are evaluated and may open or resolve
    incidents through the ``slo_rule_id`` / ``trigger_kind`` path.
    """
    state = await ensure_state(db, check_result.monitor_id)
    now = datetime.now(UTC)

    _update_probe_divergence(state, check_result, now)
    _update_probe_view(state, check_result)
    _recompute_quorum(state)
    await _refresh_5m_percentiles(db, state, now)

    state.updated_at = now

    if publish_event is None:
        return

    monitor = (
        await db.execute(select(Monitor).where(Monitor.id == check_result.monitor_id))
    ).scalar_one_or_none()
    if monitor is None or not monitor.health_engine_enabled:
        return

    await evaluate_slos(db, monitor, state, publish_event, now=now)
