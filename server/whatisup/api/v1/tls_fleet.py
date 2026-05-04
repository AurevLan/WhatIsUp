"""V2-02-08 — TLS fleet dashboard.

Aggregates the most recent ``CheckResult.tls_audit`` per monitor for the
caller, with grade / expiry filters and CSV export.
"""

from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import build_access_filter, get_current_user, get_user_team_ids
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.monitor import Monitor
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.services.stats import latest_results_subq

router = APIRouter(prefix="/tls-fleet", tags=["tls-fleet"])

# Lower index = better grade. Compared via this order map.
_GRADE_ORDER = {"A+": 0, "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}


@router.get("/")
@limiter.limit("60/minute")
async def list_tls_fleet(
    request: Request,
    grade_below: str | None = Query(default=None, pattern=r"^(A\+|A|B|C|D|E|F)$"),
    expires_within_days: int | None = Query(default=None, ge=1, le=365),
    san_mismatch: bool | None = None,
    fmt: Literal["json", "csv"] = "json",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one entry per monitor with the latest TLS audit available.

    Filters are AND-combined and applied **after** the latest-per-monitor
    aggregation so ``grade_below=B`` returns monitors whose *current* grade
    is worse than B, not monitors that ever had a worse grade.
    """
    if current_user.is_superadmin:
        monitor_ids_subq = select(Monitor.id).subquery()
    else:
        team_ids = await get_user_team_ids(current_user, db)
        access = build_access_filter(Monitor, current_user, team_ids)
        monitor_ids_subq = select(Monitor.id).where(access).subquery()

    # Latest CheckResult per monitor that has tls_audit non-null.
    latest = latest_results_subq(
        CheckResult.monitor_id.in_(select(monitor_ids_subq.c.id)),
        CheckResult.tls_audit.is_not(None),
        group_col=CheckResult.monitor_id,
    )
    rows = (
        await db.execute(
            select(CheckResult, Monitor.name, Monitor.url)
            .join(
                latest,
                (CheckResult.monitor_id == latest.c.monitor_id)
                & (CheckResult.checked_at == latest.c.max_at),
            )
            .join(Monitor, Monitor.id == CheckResult.monitor_id)
        )
    ).all()

    threshold = _GRADE_ORDER.get(grade_below) if grade_below else None
    items: list[dict] = []
    for cr, name, url in rows:
        audit = cr.tls_audit or {}
        grade = audit.get("grade")
        days = audit.get("days_remaining")
        san_ok = audit.get("san_match", True)

        if threshold is not None:
            if grade is None or _GRADE_ORDER.get(grade, 99) <= threshold:
                continue
        if expires_within_days is not None:
            if days is None or days > expires_within_days:
                continue
        if san_mismatch is True and san_ok:
            continue

        items.append(
            {
                "monitor_id": str(cr.monitor_id),
                "monitor_name": name,
                "url": url,
                "grade": grade,
                "tls_version": audit.get("tls_version"),
                "cipher_name": audit.get("cipher_name"),
                "san_match": san_ok,
                "days_remaining": days,
                "expires_at": audit.get("expires_at"),
                "checked_at": cr.checked_at.isoformat(),
            }
        )

    items.sort(key=lambda r: (_GRADE_ORDER.get(r["grade"] or "F", 99), r["days_remaining"] or 0))

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "monitor_name",
                "url",
                "grade",
                "tls_version",
                "cipher_name",
                "san_match",
                "days_remaining",
                "expires_at",
                "checked_at",
            ]
        )
        for it in items:
            writer.writerow(
                [
                    it["monitor_name"],
                    it["url"],
                    it["grade"] or "",
                    it["tls_version"] or "",
                    it["cipher_name"] or "",
                    it["san_match"],
                    it["days_remaining"] if it["days_remaining"] is not None else "",
                    it["expires_at"] or "",
                    it["checked_at"],
                ]
            )
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="tls-fleet.csv"'},
        )

    return {"count": len(items), "items": items}
