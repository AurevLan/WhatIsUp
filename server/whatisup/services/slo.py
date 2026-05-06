"""V2 Global Health Engine — SLO evaluators (M2).

Decides ``open | close | hold`` for each enabled :class:`SLORule` of a
monitor, working off the rolling :class:`MonitorHealthState` maintained by
``services/health.py``. The decision is purely a function of the current
state and recent persisted incidents — no side effects here. The bridge to
:class:`Incident` lifecycle lives in ``services/incident.py``
(``open_incident_from_health`` / ``resolve_incident_for_slo``).

Phase scope (M2 + M3):

- ``quorum_down`` — open if ≥ quorum_ratio probes are reported down (after
  staleness filter on ``window_seconds``), with at least ``min_probes`` fresh
  samples. Close when the ratio drops back below the threshold.
- ``quorum_slow`` — open if the fleet ``p95_5m`` exceeds the configured
  ``p95_threshold_ms``, requiring ≥ ``min_probes`` distinct fresh probes
  (M3). Recomputed exactly each ingest from raw CheckResults.
- ``burn_rate`` — stub raising NotImplementedError (M6, requires T-Digest
  long-window percentiles).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor_health import MonitorHealthState, SLORule, SLORuleType

_DOWN_STATES = {"down", "timeout", "error"}
_DIVERGENCE_EXCLUSION_THRESHOLD = 0.5


@dataclass(frozen=True)
class Open:
    reason: str
    scope: IncidentScope
    affected_probe_ids: list[str]


@dataclass(frozen=True)
class Close:
    reason: str


@dataclass(frozen=True)
class Hold:
    reason: str


Decision = Open | Close | Hold


def _is_down(status: str | None) -> bool:
    return status in _DOWN_STATES


def _is_divergent(state: MonitorHealthState, probe_id: str) -> bool:
    """A probe is divergent (and excluded from quorum, M5) when its rolling
    ``divergence_score`` in ``probe_health`` exceeds the threshold."""
    health = (state.probe_health or {}).get(probe_id) or {}
    return float(health.get("divergence_score") or 0.0) > _DIVERGENCE_EXCLUSION_THRESHOLD


def _fresh_probes(
    state: MonitorHealthState,
    window_seconds: int,
    now: datetime,
    *,
    exclude_divergent: bool = True,
) -> list[tuple[str, dict]]:
    """Return ``(probe_id, view)`` pairs whose ``last_at`` is within window.

    Probes flagged as divergent (M5) are skipped by default — they still ingest
    samples and remain visible in ``probes_state``, but they don't count toward
    the quorum so a single misbehaving probe can't fabricate or mask incidents.
    """
    cutoff = now - timedelta(seconds=window_seconds)
    fresh: list[tuple[str, dict]] = []
    for pid, view in (state.probes_state or {}).items():
        last_at = view.get("last_at")
        if not last_at:
            continue
        try:
            ts = datetime.fromisoformat(last_at)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts < cutoff:
            continue
        if exclude_divergent and _is_divergent(state, pid):
            continue
        fresh.append((pid, view))
    return fresh


def _evaluate_quorum_down(rule: SLORule, state: MonitorHealthState, now: datetime) -> Decision:
    window = rule.window_seconds or 300
    ratio = rule.quorum_ratio if rule.quorum_ratio is not None else 1.0
    fresh = _fresh_probes(state, window, now)
    total = len(fresh)
    if total < rule.min_probes:
        return Hold(reason=f"not_enough_probes:{total}<{rule.min_probes}")
    down_pairs = [(pid, v) for pid, v in fresh if _is_down(v.get("last_status"))]
    down = len(down_pairs)
    down_ratio = down / total if total else 0.0
    if down_ratio >= ratio:
        scope = IncidentScope.global_ if down == total else IncidentScope.geographic
        return Open(
            reason=f"quorum_down:{down}/{total}>={ratio:.2f}",
            scope=scope,
            affected_probe_ids=[pid for pid, _ in down_pairs],
        )
    if down == 0:
        return Close(reason="all_probes_up")
    return Close(reason=f"below_quorum:{down}/{total}<{ratio:.2f}")


def _evaluate_quorum_slow(rule: SLORule, state: MonitorHealthState, now: datetime) -> Decision:
    threshold = rule.p95_threshold_ms
    if threshold is None:
        return Hold(reason="no_threshold_configured")
    window = rule.window_seconds or 300
    fresh = _fresh_probes(state, window, now)
    total = len(fresh)
    if total < rule.min_probes:
        return Hold(reason=f"not_enough_probes:{total}<{rule.min_probes}")
    if state.sample_count_5m == 0 or state.p95_5m is None:
        return Hold(reason="no_p95_signal")
    if state.p95_5m > threshold:
        return Open(
            reason=f"quorum_slow:p95_5m={state.p95_5m:.0f}>{threshold}ms",
            scope=IncidentScope.global_,
            affected_probe_ids=[pid for pid, _ in fresh],
        )
    return Close(reason=f"p95_5m={state.p95_5m:.0f}<={threshold}ms")


def evaluate_rule(rule: SLORule, state: MonitorHealthState, now: datetime) -> Decision:
    """Single-rule decision dispatcher. Pure — no DB calls."""
    if not rule.enabled:
        return Hold(reason="rule_disabled")
    if rule.rule_type == SLORuleType.quorum_down:
        return _evaluate_quorum_down(rule, state, now)
    if rule.rule_type == SLORuleType.quorum_slow:
        return _evaluate_quorum_slow(rule, state, now)
    if rule.rule_type == SLORuleType.burn_rate:
        raise NotImplementedError("burn_rate lands in M6")
    raise ValueError(f"unknown SLO rule type: {rule.rule_type}")


async def _last_incident_for_rule(
    db: AsyncSession, monitor_id: uuid.UUID, rule_id: uuid.UUID
) -> Incident | None:
    return (
        await db.execute(
            select(Incident)
            .where(Incident.monitor_id == monitor_id, Incident.slo_rule_id == rule_id)
            .order_by(Incident.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def in_cooldown(db: AsyncSession, rule: SLORule, now: datetime) -> bool:
    """True if the rule recently resolved an incident and is still cooling down."""
    if not rule.cooldown_seconds:
        return False
    last = await _last_incident_for_rule(db, rule.monitor_id, rule.id)
    if last is None or last.resolved_at is None:
        return False
    return (now - last.resolved_at).total_seconds() < rule.cooldown_seconds


async def active_rules_for_monitor(db: AsyncSession, monitor_id: uuid.UUID) -> list[SLORule]:
    return list(
        (
            await db.execute(
                select(SLORule).where(
                    SLORule.monitor_id == monitor_id,
                    SLORule.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )


def merge_affected_probes(decisions: Iterable[Decision]) -> list[str]:
    """Union of affected probe IDs across a set of Open decisions."""
    out: set[str] = set()
    for d in decisions:
        if isinstance(d, Open):
            out.update(d.affected_probe_ids)
    return sorted(out)
