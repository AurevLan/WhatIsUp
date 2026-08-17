"""Discovery sources CRUD + discovered-service review (plan D, D-0).

Two routers, one scoping rule — the same one as ``oncall.py``:
``owner_id == me OR team_id IN my_teams``, superadmin bypasses. A
``DiscoveredService`` has no owner of its own; its visibility is entirely
derived from the ``DiscoverySource`` it belongs to.

No sonde-facing endpoint lives here: the push ``POST /probes/discovery`` and
the reconciliation that turns a snapshot into ``proposed``/``orphaned`` rows
are D-1/D-2. This lot only lets a tenant configure *what* a probe should scan
and review services that already exist in the table — accept/dismiss are pure
state transitions, no ``Monitor`` is created yet.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    assert_can_assign_team,
    check_resource_access,
    get_current_user,
    get_user_team_ids,
)
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.probe import Probe
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.discovery import (
    DiscoveredServiceOut,
    DiscoverySourceIn,
    DiscoverySourceOut,
    DiscoverySourceUpdate,
    validate_discovery_params,
)
from whatisup.services.audit import log_action

sources_router = APIRouter(prefix="/discovery/sources", tags=["discovery"])
services_router = APIRouter(prefix="/discovery/services", tags=["discovery"])

#: A service may move to `accepted` / `dismissed` from either of these — never
#: from `accepted` or `dismissed` themselves (re-dismissing a live proposal or
#: accepting an already-dismissed one are both no-ops that would only hide a
#: mistake), and `orphaned` is included so a service whose target came back is
#: still actionable rather than stuck.
_TRANSITIONABLE_FROM = {"proposed", "orphaned"}


def _visibility_filter(user: User, team_ids: list[uuid.UUID]):
    """`owner_id == me OR team_id IN my_teams` — same rule as oncall.py."""
    clauses = [DiscoverySource.owner_id == user.id]
    if team_ids:
        clauses.append(DiscoverySource.team_id.in_(team_ids))
    return or_(*clauses)


async def _assert_probe_active(db: AsyncSession, probe_id: uuid.UUID) -> None:
    probe = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    if not probe.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Probe is not active")


async def _get_visible_source(
    source_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> DiscoverySource:
    source = (
        await db.execute(select(DiscoverySource).where(DiscoverySource.id == source_id))
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    await check_resource_access(source, user, db, min_role=min_role)
    return source


# ── DiscoverySource ──────────────────────────────────────────────────────────


@sources_router.get("/", response_model=list[DiscoverySourceOut])
@limiter.limit("60/minute")
async def list_sources(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DiscoverySource]:
    stmt = select(DiscoverySource)
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        stmt = stmt.where(_visibility_filter(current_user, team_ids))
    rows = (await db.execute(stmt.order_by(DiscoverySource.created_at.desc()))).scalars().all()
    return list(rows)


@sources_router.post("/", response_model=DiscoverySourceOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_source(
    request: Request,
    payload: DiscoverySourceIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoverySource:
    await assert_can_assign_team(db, current_user, payload.team_id)
    await _assert_probe_active(db, payload.probe_id)

    source = DiscoverySource(
        owner_id=current_user.id,
        team_id=payload.team_id,
        probe_id=payload.probe_id,
        source_type=payload.source_type,
        params=payload.params,
        enabled=payload.enabled,
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)

    await log_action(
        db,
        "discovery_source.create",
        "discovery_source",
        source.id,
        source.source_type,
        current_user,
    )
    return source


@sources_router.get("/{source_id}", response_model=DiscoverySourceOut)
@limiter.limit("60/minute")
async def get_source(
    request: Request,
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoverySource:
    return await _get_visible_source(source_id, current_user, db)


@sources_router.patch("/{source_id}", response_model=DiscoverySourceOut)
@limiter.limit("30/minute")
async def update_source(
    request: Request,
    source_id: uuid.UUID,
    payload: DiscoverySourceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoverySource:
    source = await _get_visible_source(source_id, current_user, db, TeamRole.editor)

    data = payload.model_dump(exclude_unset=True)
    if "team_id" in data:
        await assert_can_assign_team(db, current_user, data["team_id"])
    if "probe_id" in data:
        await _assert_probe_active(db, data["probe_id"])
    if "params" in data:
        try:
            data["params"] = validate_discovery_params(source.source_type, data["params"])
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    for field, value in data.items():
        setattr(source, field, value)

    await db.flush()
    await db.refresh(source)

    await log_action(
        db,
        "discovery_source.update",
        "discovery_source",
        source.id,
        source.source_type,
        current_user,
        diff=data,
    )
    return source


@sources_router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_source(
    request: Request,
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    source = await _get_visible_source(source_id, current_user, db, TeamRole.admin)

    await log_action(
        db,
        "discovery_source.delete",
        "discovery_source",
        source.id,
        source.source_type,
        current_user,
    )
    # discovered_services cascade (FK ondelete=CASCADE + relationship
    # cascade="all, delete-orphan") — no orphaned inventory left behind.
    await db.delete(source)
    await db.flush()


# ── DiscoveredService ────────────────────────────────────────────────────────


@services_router.get("/", response_model=list[DiscoveredServiceOut])
@limiter.limit("60/minute")
async def list_services(
    request: Request,
    source_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DiscoveredService]:
    if source_id is not None:
        # Visiting a single source's services requires visibility into that
        # source — a bare 404 on an inaccessible id, same as the CRUD above.
        await _get_visible_source(source_id, current_user, db)
        stmt = select(DiscoveredService).where(DiscoveredService.source_id == source_id)
    else:
        stmt = select(DiscoveredService).join(
            DiscoverySource, DiscoveredService.source_id == DiscoverySource.id
        )
        if not current_user.is_superadmin:
            team_ids = await get_user_team_ids(current_user, db)
            stmt = stmt.where(_visibility_filter(current_user, team_ids))

    if status_filter is not None:
        stmt = stmt.where(DiscoveredService.status == status_filter)

    rows = (await db.execute(stmt.order_by(DiscoveredService.last_seen_at.desc()))).scalars().all()
    return list(rows)


async def _get_visible_service(
    service_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> DiscoveredService:
    service = (
        await db.execute(select(DiscoveredService).where(DiscoveredService.id == service_id))
    ).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    source = (
        await db.execute(select(DiscoverySource).where(DiscoverySource.id == service.source_id))
    ).scalar_one_or_none()
    # A service can only exist with a live source (CASCADE delete), but stay
    # defensive rather than let a stale row 500 the request.
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    await check_resource_access(source, user, db, min_role=min_role)
    return service


async def _transition(
    service_id: uuid.UUID,
    new_status: str,
    action: str,
    current_user: User,
    db: AsyncSession,
) -> DiscoveredService:
    service = await _get_visible_service(service_id, current_user, db, TeamRole.editor)
    if service.status not in _TRANSITIONABLE_FROM:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot {action} a service in status '{service.status}'",
        )
    service.status = new_status
    service.status_changed_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(service)

    await log_action(
        db,
        f"discovery_service.{action}",
        "discovered_service",
        service.id,
        service.normalized_target,
        current_user,
    )
    return service


@services_router.post("/{service_id}/accept", response_model=DiscoveredServiceOut)
@limiter.limit("30/minute")
async def accept_service(
    request: Request,
    service_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoveredService:
    """Mark a proposal accepted. Pure state transition — D-0 creates no ``Monitor``."""
    return await _transition(service_id, "accepted", "accept", current_user, db)


@services_router.post("/{service_id}/dismiss", response_model=DiscoveredServiceOut)
@limiter.limit("30/minute")
async def dismiss_service(
    request: Request,
    service_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoveredService:
    """Reject a proposal. Memorised on the row — the reconciler (D-2) must not re-propose it."""
    return await _transition(service_id, "dismissed", "dismiss", current_user, db)
