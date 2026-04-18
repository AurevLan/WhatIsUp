"""Monitor template endpoints."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.monitor_template import MonitorTemplate
from whatisup.models.user import User
from whatisup.schemas.template import (
    MonitorTemplateCreate,
    MonitorTemplateOut,
    MonitorTemplateUpdate,
    TemplateApplyIn,
)

router = APIRouter(prefix="/templates", tags=["templates"])


def _substitute(value: str, values: dict[str, str]) -> str:
    """Replace {{VAR}} placeholders with provided values."""
    def replacer(m: re.Match) -> str:
        return values.get(m.group(1).strip(), m.group(0))
    return re.sub(r"\{\{([^}]+)\}\}", replacer, value)


def _substitute_config(
    config: dict | list | str | int | float | bool | None, values: dict
) -> object:
    """Recursively substitute placeholders in a monitor config dict."""
    if isinstance(config, str):
        return _substitute(config, values)
    if isinstance(config, dict):
        return {k: _substitute_config(v, values) for k, v in config.items()}
    if isinstance(config, list):
        return [_substitute_config(item, values) for item in config]
    return config


@router.get("/", response_model=list[MonitorTemplateOut])
@limiter.limit("60/minute")
async def list_templates(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List templates owned by the current user plus all public templates."""
    templates = (
        await db.execute(
            select(MonitorTemplate)
            .where(
                or_(
                    MonitorTemplate.owner_id == current_user.id,
                    MonitorTemplate.is_public.is_(True),
                )
            )
            .order_by(MonitorTemplate.created_at.desc())
        )
    ).scalars().all()
    return list(templates)


@router.post("/", response_model=MonitorTemplateOut, status_code=201)
@limiter.limit("30/minute")
async def create_template(
    request: Request,
    body: MonitorTemplateCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorTemplate:
    template = MonitorTemplate(
        owner_id=current_user.id,
        name=body.name,
        description=body.description,
        variables=[v.model_dump() for v in body.variables] if body.variables else [],
        monitor_config=body.monitor_config,
        is_public=body.is_public,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


@router.get("/{template_id}", response_model=MonitorTemplateOut)
@limiter.limit("60/minute")
async def get_template(
    request: Request,
    template_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorTemplate:
    template = (
        await db.execute(
            select(MonitorTemplate).where(
                MonitorTemplate.id == template_id,
                or_(
                    MonitorTemplate.owner_id == current_user.id,
                    MonitorTemplate.is_public.is_(True),
                ),
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


@router.patch("/{template_id}", response_model=MonitorTemplateOut)
@limiter.limit("30/minute")
async def update_template(
    request: Request,
    template_id: uuid.UUID,
    body: MonitorTemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorTemplate:
    template = (
        await db.execute(
            select(MonitorTemplate).where(
                MonitorTemplate.id == template_id,
                MonitorTemplate.owner_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    for field, value in body.model_dump(exclude_none=True).items():
        if field == "variables" and value is not None:
            value = [v if isinstance(v, dict) else v.model_dump() for v in (body.variables or [])]
        setattr(template, field, value)

    await db.flush()
    await db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_template(
    request: Request,
    template_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    template = (
        await db.execute(
            select(MonitorTemplate).where(
                MonitorTemplate.id == template_id,
                MonitorTemplate.owner_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    await db.delete(template)


@router.post("/{template_id}/apply", status_code=201)
@limiter.limit("20/minute")
async def apply_template(
    request: Request,
    template_id: uuid.UUID,
    body: TemplateApplyIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply a template with variable substitution to create a new monitor."""
    from whatisup.api.v1.monitors import create_monitor
    from whatisup.schemas.monitor import MonitorCreate

    template = (
        await db.execute(
            select(MonitorTemplate).where(
                MonitorTemplate.id == template_id,
                or_(
                    MonitorTemplate.owner_id == current_user.id,
                    MonitorTemplate.is_public.is_(True),
                ),
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    # Apply variable substitution
    config = _substitute_config(template.monitor_config, body.values)
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Template monitor_config must be a dict")

    # Override name/group if provided
    if body.name_override:
        config["name"] = body.name_override
    if body.group_id:
        config["group_id"] = str(body.group_id)

    try:
        monitor_in = MonitorCreate.model_validate(config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Delegate to the monitors create endpoint logic
    monitor = await create_monitor(
        request=request, body=monitor_in, current_user=current_user, db=db
    )
    return {"monitor_id": str(monitor.id), "name": monitor.name}
