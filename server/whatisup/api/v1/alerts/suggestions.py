"""Threshold suggestion endpoint."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.user import User
from whatisup.services.threshold_advisor import compute_threshold_suggestions

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/suggestions/thresholds")
@limiter.limit("10/minute")
async def get_threshold_suggestions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return monitors that could benefit from a response_time_above alert rule,
    with a suggested threshold based on their p95 over the last 7 days."""
    return await compute_threshold_suggestions(db, owner_id=current_user.id)
