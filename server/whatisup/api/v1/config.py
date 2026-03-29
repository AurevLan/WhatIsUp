"""Declarative configuration API — export and import monitoring setup."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.user import User
from whatisup.services.config_sync import export_config, import_config

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/")
async def get_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Export the full monitoring configuration as JSON.

    Returns monitors, groups, alert channels, and alert rules.
    Secrets in alert channel configs are redacted (shown as ``***``).
    """
    return await export_config(current_user, db)


@router.put("/")
@limiter.limit("10/minute")
async def put_config(
    request: Request,
    payload: dict[str, Any],
    dry_run: bool = Query(default=False, description="Preview changes without applying"),
    prune: bool = Query(default=True, description="Delete resources not in the config"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Import a declarative configuration.

    Performs a diff against the current state and applies creates/updates/deletes
    to converge to the desired state. Resources are matched by name (not UUID).

    Query parameters:
    - ``dry_run=true``: preview the plan without applying changes
    - ``prune=false``: skip deletion of resources not present in the config
    """
    return await import_config(
        user=current_user,
        db=db,
        config=payload,
        dry_run=dry_run,
        prune=prune,
    )
