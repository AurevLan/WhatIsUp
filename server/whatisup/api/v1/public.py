"""Public status page endpoints — no authentication required."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import get_db
from whatisup.models.monitor import Monitor, PublicPage
from whatisup.schemas.monitor import PublicPageOut
from whatisup.services.stats import compute_uptime

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/pages/{slug}", response_model=PublicPageOut)
async def get_public_page(slug: str, db: AsyncSession = Depends(get_db)) -> PublicPage:
    page = (await db.execute(
        select(PublicPage).where(PublicPage.slug == slug)
    )).scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status page not found")
    return page


@router.get("/pages/{slug}/monitors")
async def get_public_monitors(slug: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    page = (await db.execute(
        select(PublicPage).where(PublicPage.slug == slug)
    )).scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status page not found")

    if page.group_id is None:
        return []

    monitors = (await db.execute(
        select(Monitor).where(Monitor.group_id == page.group_id, Monitor.enabled is True)
    )).scalars().all()

    results = []
    for m in monitors:
        uptime = await compute_uptime(db, m.id, period_hours=24)
        results.append({
            "id": str(m.id),
            "name": m.name,
            "url": m.url,
            "uptime_24h": uptime.uptime_percent,
            "avg_response_time_ms": uptime.avg_response_time_ms,
        })
    return results
