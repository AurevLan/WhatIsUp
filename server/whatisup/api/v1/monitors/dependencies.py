"""Monitor topology — dependency graph, dependencies, composite members, correlated monitors."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    build_access_filter,
    get_current_user,
    get_user_team_ids,
)
from whatisup.api.v1.monitors._common import _get_monitor_or_404
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.monitor import CompositeMonitorMember, Monitor
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.schemas.monitor import (
    CompositeMonitorMemberCreate,
    CompositeMonitorMemberOut,
    MonitorDependencyCreate,
    MonitorDependencyOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get("/graph")
@limiter.limit("30/minute")
async def get_dependency_graph(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the full monitor dependency graph for the current user.

    Declared BEFORE ``/{monitor_id}`` on purpose: FastAPI matches paths in
    declaration order, so the literal ``/graph`` would otherwise be consumed
    by the parameterized route and fail UUID validation with 422.

    Nodes: all accessible monitors with their current status.
    Edges: all dependencies between those monitors.
    """
    from whatisup.models.monitor import MonitorDependency

    # Fetch all accessible monitors
    query = select(Monitor)
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        query = query.where(build_access_filter(Monitor, current_user, team_ids))
    monitors = list((await db.execute(query)).scalars().all())

    monitor_ids = [m.id for m in monitors]
    monitor_id_set = {m.id for m in monitors}

    # Latest status per monitor
    nodes = []
    latest_map: dict = {}
    if monitor_ids:
        max_ts_subq = (
            select(
                CheckResult.monitor_id,
                func.max(CheckResult.checked_at).label("max_at"),
            )
            .where(CheckResult.monitor_id.in_(monitor_ids))
            .group_by(CheckResult.monitor_id)
            .subquery()
        )
        latest_rows = (
            await db.execute(
                select(CheckResult.monitor_id, CheckResult.status, CheckResult.checked_at).join(
                    max_ts_subq,
                    and_(
                        CheckResult.monitor_id == max_ts_subq.c.monitor_id,
                        CheckResult.checked_at == max_ts_subq.c.max_at,
                    ),
                )
            )
        ).all()
        now = datetime.now(UTC)
        for r in latest_rows:
            age = (now - r.checked_at).total_seconds()
            latest_map[r.monitor_id] = r.status.value if age < 300 else None

    for m in monitors:
        nodes.append(
            {
                "id": str(m.id),
                "name": m.name,
                "status": latest_map.get(m.id),
                "check_type": m.check_type,
            }
        )

    # Fetch all dependencies between accessible monitors only
    edges = []
    if monitor_ids:
        dep_rows = (
            (
                await db.execute(
                    select(MonitorDependency).where(
                        MonitorDependency.parent_id.in_(monitor_ids),
                        MonitorDependency.child_id.in_(monitor_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        for dep in dep_rows:
            if dep.parent_id in monitor_id_set and dep.child_id in monitor_id_set:
                edges.append(
                    {
                        "source": str(dep.parent_id),
                        "target": str(dep.child_id),
                        "suppress_on_parent_down": dep.suppress_on_parent_down,
                    }
                )

    return {"nodes": nodes, "edges": edges}


@router.get(
    "/{monitor_id}/dependencies",
    response_model=list[MonitorDependencyOut],
)
@limiter.limit("60/minute")
async def list_dependencies(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all parent monitors this monitor depends on."""
    from whatisup.models.monitor import MonitorDependency

    await _get_monitor_or_404(monitor_id, current_user, db)
    rows = (
        (
            await db.execute(
                select(MonitorDependency).where(MonitorDependency.child_id == monitor_id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post(
    "/{monitor_id}/dependencies",
    response_model=MonitorDependencyOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def add_dependency(
    request: Request,
    monitor_id: uuid.UUID,
    payload: MonitorDependencyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Declare that this monitor depends on a parent monitor.

    When the parent has an open incident and ``suppress_on_parent_down`` is
    ``true``, incidents on this (child) monitor will be suppressed.
    """
    from whatisup.models.monitor import MonitorDependency

    child = await _get_monitor_or_404(monitor_id, current_user, db)
    parent = await _get_monitor_or_404(payload.parent_id, current_user, db)

    if parent.id == child.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A monitor cannot depend on itself",
        )

    # Check for duplicates
    existing = (
        await db.execute(
            select(MonitorDependency).where(
                MonitorDependency.parent_id == parent.id,
                MonitorDependency.child_id == child.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dependency already exists",
        )

    dep = MonitorDependency(
        parent_id=parent.id,
        child_id=child.id,
        suppress_on_parent_down=payload.suppress_on_parent_down,
    )
    db.add(dep)
    await db.flush()
    return dep


@router.delete(
    "/{monitor_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("30/minute")
async def remove_dependency(
    request: Request,
    monitor_id: uuid.UUID,
    dependency_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a parent dependency from this monitor."""
    from whatisup.models.monitor import MonitorDependency

    await _get_monitor_or_404(monitor_id, current_user, db)
    dep = (
        await db.execute(
            select(MonitorDependency).where(
                MonitorDependency.id == dependency_id,
                MonitorDependency.child_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if dep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dependency not found")
    await db.delete(dep)


# ---------------------------------------------------------------------------
# DNS baseline management
# ---------------------------------------------------------------------------


async def _would_create_cycle(
    db: AsyncSession,
    composite_id: uuid.UUID,
    member_id: uuid.UUID,
) -> bool:
    """Check if adding member_id to composite_id would create a cycle.

    Iterative BFS with a single edge query: scales linearly in edges rather
    than issuing one query per node (the previous recursive implementation
    was O(nodes) round-trips).
    """
    if member_id == composite_id:
        return True

    # Load every composite edge once; building the adjacency map in Python
    # turns the cycle check into pure in-memory graph traversal.
    edges = (
        await db.execute(
            select(
                CompositeMonitorMember.composite_id,
                CompositeMonitorMember.monitor_id,
            )
        )
    ).all()
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
    for parent, child in edges:
        adjacency.setdefault(parent, []).append(child)

    visited: set[uuid.UUID] = set()
    queue: list[uuid.UUID] = [member_id]
    while queue:
        node = queue.pop()
        if node in visited:
            continue
        if node == composite_id:
            return True
        visited.add(node)
        queue.extend(adjacency.get(node, ()))
    return False


@router.get(
    "/{monitor_id}/composite-members",
    response_model=list[CompositeMonitorMemberOut],
)
@limiter.limit("60/minute")
async def list_composite_members(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all source monitors of a composite monitor."""
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "composite":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This monitor is not a composite monitor",
        )
    rows = (
        (
            await db.execute(
                select(CompositeMonitorMember).where(
                    CompositeMonitorMember.composite_id == monitor_id
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post(
    "/{monitor_id}/composite-members",
    response_model=CompositeMonitorMemberOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def add_composite_member(
    request: Request,
    monitor_id: uuid.UUID,
    payload: CompositeMonitorMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Add a source monitor to a composite monitor."""
    composite = await _get_monitor_or_404(monitor_id, current_user, db)
    if composite.check_type != "composite":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target monitor is not a composite monitor",
        )
    if payload.monitor_id == monitor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A composite monitor cannot reference itself",
        )

    member_monitor = await _get_monitor_or_404(payload.monitor_id, current_user, db)

    # Cycle detection: if member is itself a composite, check for transitive cycles
    if member_monitor.check_type == "composite":
        if await _would_create_cycle(db, monitor_id, payload.monitor_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Adding this member would create a circular dependency",
            )

    existing = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.composite_id == monitor_id,
                CompositeMonitorMember.monitor_id == payload.monitor_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Member already added")

    member = CompositeMonitorMember(
        composite_id=monitor_id,
        monitor_id=payload.monitor_id,
        weight=payload.weight,
        role=payload.role,
    )
    db.add(member)
    await db.flush()
    return member


@router.patch(
    "/{monitor_id}/composite-members/{member_id}",
    response_model=CompositeMonitorMemberOut,
)
@limiter.limit("30/minute")
async def update_composite_member(
    request: Request,
    monitor_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: CompositeMonitorMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Update weight or role of a composite member."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    member = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.id == member_id,
                CompositeMonitorMember.composite_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    member.weight = payload.weight
    member.role = payload.role
    await db.flush()
    return member


@router.delete(
    "/{monitor_id}/composite-members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("30/minute")
async def remove_composite_member(
    request: Request,
    monitor_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a source monitor from a composite monitor."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    member = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.id == member_id,
                CompositeMonitorMember.composite_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await db.delete(member)


# ── Correlation patterns ─────────────────────────────────────────────────


@router.get("/{monitor_id}/correlated")
@limiter.limit("60/minute")
async def get_correlated_monitors(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return monitors that frequently fail at the same time as this one."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.correlation import get_correlated_monitors as _get

    patterns = await _get(db, monitor_id)
    # Enrich with monitor names
    if patterns:
        monitor_ids = [uuid.UUID(p["monitor_id"]) for p in patterns]
        monitors = (
            await db.execute(select(Monitor.id, Monitor.name).where(Monitor.id.in_(monitor_ids)))
        ).all()
        name_map = {str(m.id): m.name for m in monitors}
        for p in patterns:
            p["monitor_name"] = name_map.get(p["monitor_id"])
    return patterns
