"""DNS and JSON-schema drift baselines (accept / reset)."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    get_current_user,
)
from whatisup.api.v1.monitors._common import _get_monitor_or_404
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.result import CheckResult
from whatisup.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.post("/{monitor_id}/dns-baseline/accept", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def accept_dns_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept the current DNS resolved values as the new baseline.

    Fetches the most recent successful DNS check result for this monitor
    and stores its resolved IPs as the new drift-detection baseline.
    Clears any existing open incident caused by a drift.
    """
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "dns":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNS baseline only applies to dns check_type monitors",
        )

    latest = (
        await db.execute(
            select(CheckResult)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.dns_resolved_values.isnot(None),
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is None or not latest.dns_resolved_values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No DNS result available yet — wait for the first check",
        )

    new_baseline = sorted(latest.dns_resolved_values)
    monitor.dns_baseline_ips = new_baseline
    await db.flush()

    return {"baseline": new_baseline, "accepted_at": latest.checked_at.isoformat()}


@router.delete("/{monitor_id}/dns-baseline", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def reset_dns_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    type: str = Query(default="all", pattern=r"^(all|internal|external)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear the DNS baseline — the next successful check will re-learn it.

    type=all (default): clears all baselines (global, internal, external)
    type=internal: clears only the internal probe baseline
    type=external: clears only the external probe baseline
    """
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "dns":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNS baseline only applies to dns check_type monitors",
        )
    if type == "internal":
        monitor.dns_baseline_ips_internal = None
    elif type == "external":
        monitor.dns_baseline_ips_external = None
    else:
        monitor.dns_baseline_ips = None
        monitor.dns_baseline_ips_internal = None
        monitor.dns_baseline_ips_external = None


# ---------------------------------------------------------------------------
# Schema drift baseline management
# ---------------------------------------------------------------------------


@router.post("/{monitor_id}/schema-baseline/accept", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def accept_schema_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept the current API schema fingerprint as the new baseline for drift detection."""

    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    latest = (
        await db.execute(
            select(CheckResult)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.schema_fingerprint.isnot(None),
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is None or not latest.schema_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No schema fingerprint available yet — "
                "enable schema_drift_enabled and wait for a check"
            ),
        )

    monitor.schema_baseline = latest.schema_fingerprint
    monitor.schema_baseline_updated_at = datetime.now(UTC)

    return {
        "baseline": monitor.schema_baseline,
        "accepted_at": latest.checked_at.isoformat(),
    }


@router.delete("/{monitor_id}/schema-baseline", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def reset_schema_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear the schema baseline — the next successful check will set a new one."""
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    monitor.schema_baseline = None
    monitor.schema_baseline_updated_at = None


# ---------------------------------------------------------------------------
# Composite monitor members
# ---------------------------------------------------------------------------
