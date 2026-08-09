"""Health Engine V2 — health-state, SLO status and SLO rules CRUD."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    get_current_user,
    require_superadmin,
)
from whatisup.api.v1.monitors._common import _get_monitor_or_404
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.slo import SLORuleCreate, SLORuleOut, SLORuleUpdate
from whatisup.services.stats import (
    compute_uptime_in_range,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get("/{monitor_id}/health-state")
@limiter.limit("60/minute")
async def get_health_state(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Global Health Engine debug view — superadmin only.

    Returns the rolling MonitorHealthState (probes_state, p50/p95/p99 5m,
    quorum_down_ratio, current_scope) maintained by ``services/health.py``.
    Intended for ops/debug while M1-M5 ship; will be exposed to monitor
    owners once the engine is stabilized.
    """
    from whatisup.models.monitor_health import MonitorHealthState

    state = (
        await db.execute(
            select(MonitorHealthState).where(MonitorHealthState.monitor_id == monitor_id)
        )
    ).scalar_one_or_none()
    if state is None:
        return {
            "monitor_id": str(monitor_id),
            "exists": False,
            "probes_state": {},
            "sample_count_5m": 0,
        }
    return {
        "monitor_id": str(monitor_id),
        "exists": True,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
        "probes_state": state.probes_state,
        "p50_5m": state.p50_5m,
        "p95_5m": state.p95_5m,
        "p99_5m": state.p99_5m,
        "sample_count_5m": state.sample_count_5m,
        "quorum_down_ratio": state.quorum_down_ratio,
        "current_scope": state.current_scope,
        "probe_health": state.probe_health,
    }


@router.get("/{monitor_id}/slo")
@limiter.limit("30/minute")
async def get_slo(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """SLO / Error Budget status for a monitor."""
    from whatisup.models.incident import Incident

    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    if monitor.slo_target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLO non configuré sur ce moniteur",
        )

    window_days = monitor.slo_window_days or 30
    slo_target = monitor.slo_target
    now = datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    # Uptime over the SLO window (multi-probe consensus)
    consensus_slo = await compute_uptime_in_range(db, monitor_id, window_start, now)
    uptime_pct = consensus_slo["uptime_percent"]

    # Downtime from resolved incidents in the window
    inc_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Incident.duration_seconds), 0).label("total_downtime_s"),
            ).where(
                Incident.monitor_id == monitor_id,
                Incident.started_at >= window_start,
                Incident.resolved_at.isnot(None),
                # C-4 — error budget is spent by downtime. A pushed-metric
                # breach is not downtime and must not burn it.
                Incident.alert_rule_id.is_(None),
            )
        )
    ).one()
    downtime_minutes = float(inc_row.total_downtime_s or 0) / 60.0

    # Error budget calculation
    error_budget_total_minutes = window_days * 24 * 60 * (1 - slo_target / 100)
    error_budget_remaining_minutes = error_budget_total_minutes - downtime_minutes
    error_budget_used_minutes = downtime_minutes
    burn_rate = (
        downtime_minutes / error_budget_total_minutes if error_budget_total_minutes > 0 else 0.0
    )

    if burn_rate >= 1.0:
        slo_status = "exhausted"
    elif burn_rate > 0.8:
        slo_status = "critical"
    elif burn_rate > 0.5:
        slo_status = "at_risk"
    else:
        slo_status = "healthy"

    return {
        "slo_target": slo_target,
        "window_days": window_days,
        "uptime_pct": uptime_pct,
        "error_budget_total_minutes": round(error_budget_total_minutes, 2),
        "error_budget_used_minutes": round(error_budget_used_minutes, 2),
        "error_budget_remaining_minutes": round(error_budget_remaining_minutes, 2),
        "burn_rate": round(burn_rate, 4),
        "status": slo_status,
    }


# ---------------------------------------------------------------------------
# Monitor dependencies
# ---------------------------------------------------------------------------


# NOTE: `/graph` is declared higher up (above `/{monitor_id}`) so FastAPI's
# declaration-order route matcher doesn't try to parse "graph" as a UUID
# monitor_id (which would 422). See get_dependency_graph.


# ── SLO rules (V2 Global Health Engine) ─────────────────────────────────


@router.get("/{monitor_id}/slo-rules", response_model=list[SLORuleOut])
@limiter.limit("60/minute")
async def list_slo_rules(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SLORuleOut]:
    from whatisup.models.monitor_health import SLORule

    await _get_monitor_or_404(monitor_id, current_user, db)
    rules = (
        (
            await db.execute(
                select(SLORule)
                .where(SLORule.monitor_id == monitor_id)
                .order_by(SLORule.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [SLORuleOut.model_validate(r) for r in rules]


@router.post(
    "/{monitor_id}/slo-rules",
    response_model=SLORuleOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def create_slo_rule(
    monitor_id: uuid.UUID,
    request: Request,
    payload: SLORuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SLORuleOut:
    from whatisup.models.monitor_health import SLORule

    await _get_monitor_or_404(monitor_id, current_user, db, min_role=TeamRole.editor)
    rule = SLORule(
        monitor_id=monitor_id,
        rule_type=payload.rule_type,
        enabled=payload.enabled,
        quorum_ratio=payload.quorum_ratio,
        window_seconds=payload.window_seconds,
        p95_threshold_ms=payload.p95_threshold_ms,
        slo_target=payload.slo_target,
        burn_factor=payload.burn_factor,
        min_probes=payload.min_probes,
        cooldown_seconds=payload.cooldown_seconds,
    )
    db.add(rule)
    await db.flush()
    return SLORuleOut.model_validate(rule)


@router.patch("/{monitor_id}/slo-rules/{rule_id}", response_model=SLORuleOut)
@limiter.limit("30/minute")
async def update_slo_rule(
    monitor_id: uuid.UUID,
    rule_id: uuid.UUID,
    request: Request,
    payload: SLORuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SLORuleOut:
    from whatisup.models.monitor_health import SLORule

    await _get_monitor_or_404(monitor_id, current_user, db, min_role=TeamRole.editor)
    rule = (
        await db.execute(
            select(SLORule).where(SLORule.id == rule_id, SLORule.monitor_id == monitor_id)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SLO rule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await db.flush()
    return SLORuleOut.model_validate(rule)


@router.delete("/{monitor_id}/slo-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_slo_rule(
    monitor_id: uuid.UUID,
    rule_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    from whatisup.models.monitor_health import SLORule

    await _get_monitor_or_404(monitor_id, current_user, db, min_role=TeamRole.editor)
    rule = (
        await db.execute(
            select(SLORule).where(SLORule.id == rule_id, SLORule.monitor_id == monitor_id)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SLO rule not found")
    await db.delete(rule)
