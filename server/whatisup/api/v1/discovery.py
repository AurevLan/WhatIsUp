"""Discovery sources CRUD + discovered-service review (plan D, D-0 / D-2 / D-3).

Two routers, one scoping rule — the same one as ``oncall.py``:
``owner_id == me OR team_id IN my_teams``, superadmin bypasses. A
``DiscoveredService`` has no owner of its own; its visibility is entirely
derived from the ``DiscoverySource`` it belongs to.

No sonde-facing endpoint lives here: the push ``POST /probes/discovery``
(``api/v1/probes.py``) stores the snapshot and calls
``services.discovery.reconcile_source_push`` to turn it into
``proposed``/``accepted``/``orphaned`` rows. This module is what a tenant
uses to configure *what* a probe should scan and review what it found:
``accept`` (D-2) now actually creates a ``Monitor`` — via the same creation
path as ``POST /monitors`` (``_create_monitor_from_payload``), never a copy
of it — pre-filled from the proposal computed by
``services/discovery.py::default_monitor_fields`` and overridable by the
caller; ``dismiss`` stays a pure state transition, optionally carrying a
free-text ``reason`` (D-3). ``POST /discovery/services/bulk`` (D-3) runs
either transition over a batch of ids through the exact same per-id checks —
never a bulk SQL statement, since ``accept`` may create a ``Monitor``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    assert_can_assign_group,
    assert_can_assign_team,
    check_resource_access,
    get_current_user,
    get_user_team_ids,
)
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.discovery import (
    DiscoveredServiceAcceptIn,
    DiscoveredServiceDismissIn,
    DiscoveredServiceOut,
    DiscoveryBulkActionIn,
    DiscoveryBulkActionOut,
    DiscoverySourceIn,
    DiscoverySourceOut,
    DiscoverySourceUpdate,
    validate_discovery_params,
)
from whatisup.services.audit import log_action
from whatisup.services.discovery import (
    compute_proposal,
    default_monitor_fields,
    port_field_for_check_type,
    suggest_alert_matrix_templates,
)

#: `Monitor` fields that carry a port for some check_type — cleared and
#: recomputed (see `_create_monitor_from_proposal`) whenever the caller
#: overrides `check_type` away from the prefill's own deduction.
_PORT_OVERRIDE_FIELDS = ("tcp_port", "udp_port", "smtp_port")

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


#: `DiscoveredServiceOut`'s columns that come straight from the ORM row —
#: everything else on the schema (`suggested_*`) is computed, not a
#: `DiscoveredService` attribute, so `model_validate(service, from_attributes=True)`
#: directly on the ORM object would fail on those as missing.
_BASE_SERVICE_FIELDS = (
    "id",
    "source_id",
    "monitor_id",
    "host",
    "port",
    "proto",
    "normalized_target",
    "hints",
    "status",
    "dismissed_reason",
    "first_seen_at",
    "last_seen_at",
    "status_changed_at",
    "created_at",
    "updated_at",
)


async def _serialize_service(
    service: DiscoveredService, source_type: str, template_id: uuid.UUID | None
) -> dict:
    """`DiscoveredServiceOut` plus the prefill (plan D, D-2 §3) — computed
    fresh every time, never stored (see the schema's docstring)."""
    proposal = compute_proposal(service, source_type)
    data = {field: getattr(service, field) for field in _BASE_SERVICE_FIELDS}
    data.update(
        suggested_check_type=proposal.check_type,
        suggested_name=proposal.name,
        suggested_group=proposal.group,
        suggested_tags=proposal.tags,
        suggested_alert_matrix_template_id=template_id,
    )
    return DiscoveredServiceOut.model_validate(data).model_dump()


@services_router.get("/", response_model=list[DiscoveredServiceOut])
@limiter.limit("60/minute")
async def list_services(
    request: Request,
    source_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    if source_id is not None:
        # Visiting a single source's services requires visibility into that
        # source — a bare 404 on an inaccessible id, same as the CRUD above.
        await _get_visible_source(source_id, current_user, db)
        stmt = (
            select(DiscoveredService, DiscoverySource.source_type)
            .join(DiscoverySource, DiscoveredService.source_id == DiscoverySource.id)
            .where(DiscoveredService.source_id == source_id)
        )
    else:
        stmt = select(DiscoveredService, DiscoverySource.source_type).join(
            DiscoverySource, DiscoveredService.source_id == DiscoverySource.id
        )
        if not current_user.is_superadmin:
            team_ids = await get_user_team_ids(current_user, db)
            stmt = stmt.where(_visibility_filter(current_user, team_ids))

    if status_filter is not None:
        stmt = stmt.where(DiscoveredService.status == status_filter)

    rows = (await db.execute(stmt.order_by(DiscoveredService.last_seen_at.desc()))).all()

    # One batched lookup for every suggested check_type in the page, instead
    # of a query per row.
    proposals = {
        row.DiscoveredService.id: compute_proposal(row.DiscoveredService, row.source_type)
        for row in rows
    }
    template_map = await suggest_alert_matrix_templates(
        db, {p.check_type for p in proposals.values()}
    )

    return [
        await _serialize_service(
            row.DiscoveredService,
            row.source_type,
            template_map.get(proposals[row.DiscoveredService.id].check_type),
        )
        for row in rows
    ]


async def _get_visible_service(
    service_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> tuple[DiscoveredService, DiscoverySource]:
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
    return service, source


async def _respond(service: DiscoveredService, source: DiscoverySource, db: AsyncSession) -> dict:
    proposal = compute_proposal(service, source.source_type)
    template_map = await suggest_alert_matrix_templates(db, {proposal.check_type})
    return await _serialize_service(
        service, source.source_type, template_map.get(proposal.check_type)
    )


def _assert_transitionable(service: DiscoveredService, action: str) -> None:
    if service.status not in _TRANSITIONABLE_FROM:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot {action} a service in status '{service.status}'",
        )


async def _dismiss_row(
    db: AsyncSession,
    service: DiscoveredService,
    source: DiscoverySource,
    reason: str | None,
    current_user: User,
) -> dict:
    """Reject a proposal. Memorised on the row (with an optional reason,
    plan D, D-3) — the reconciler (D-2) must not re-propose it. Shared by the
    unitary and bulk endpoints; the caller has already checked visibility and
    ``_assert_transitionable``."""
    service.status = "dismissed"
    service.dismissed_reason = reason
    service.status_changed_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(service)

    await log_action(
        db,
        "discovery_service.dismiss",
        "discovered_service",
        service.id,
        service.normalized_target,
        current_user,
        diff={"reason": reason},
    )
    return await _respond(service, source, db)


async def _accept_row(
    db: AsyncSession,
    service: DiscoveredService,
    source: DiscoverySource,
    payload: DiscoveredServiceAcceptIn,
    current_user: User,
) -> dict:
    """Accept a proposal.

    Two shapes, both ending in ``status="accepted"`` (plan D, D-2):

    - ``monitor_id`` already set (a matched proposal that was auto-linked to
      an existing monitor at ingestion, or an ``orphaned`` row whose monitor
      is still real) — just re-affirm the link, no new ``Monitor``.
    - otherwise — a genuine new proposal: create the ``Monitor`` via the same
      path as ``POST /monitors`` (``_create_monitor_from_payload``), prefilled
      from the proposal and overridable by ``payload``, then link it.

    Shared by the unitary and bulk endpoints; the caller has already checked
    visibility and ``_assert_transitionable``.
    """
    now = datetime.now(UTC)
    diff: dict | None = None

    if service.monitor_id is None:
        # Same permission gate as POST /monitors — an editor of the
        # discovery source must not bypass the monitor-creation restriction.
        if not current_user.is_superadmin and not current_user.can_create_monitors:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Monitor creation not allowed for your account",
            )
        monitor = await _create_monitor_from_proposal(db, service, source, payload, current_user)
        service.monitor_id = monitor.id
        diff = {"monitor_id": str(monitor.id)}

    # Defensive: a service can only reach `accept` from `proposed`/`orphaned`
    # today (never from `dismissed`), but clearing this here keeps the
    # invariant true even if that ever changes (plan_discovery.md D-3 §1:
    # "vidé si le service redevient autre chose que dismissed").
    service.dismissed_reason = None
    service.status = "accepted"
    service.status_changed_at = now
    await db.flush()
    await db.refresh(service)

    await log_action(
        db,
        "discovery_service.accept",
        "discovered_service",
        service.id,
        service.normalized_target,
        current_user,
        diff=diff,
    )
    return await _respond(service, source, db)


@services_router.post("/{service_id}/dismiss", response_model=DiscoveredServiceOut)
@limiter.limit("30/minute")
async def dismiss_service(
    request: Request,
    service_id: uuid.UUID,
    payload: DiscoveredServiceDismissIn | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a proposal. Memorised on the row — the reconciler (D-2) must not re-propose it."""
    service, source = await _get_visible_service(service_id, current_user, db, TeamRole.editor)
    _assert_transitionable(service, "dismiss")
    reason = payload.reason if payload else None
    return await _dismiss_row(db, service, source, reason, current_user)


@services_router.post("/{service_id}/accept", response_model=DiscoveredServiceOut)
@limiter.limit("30/minute")
async def accept_service(
    request: Request,
    service_id: uuid.UUID,
    payload: DiscoveredServiceAcceptIn | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept a proposal — see ``_accept_row`` for the two shapes it covers."""
    service, source = await _get_visible_service(service_id, current_user, db, TeamRole.editor)
    _assert_transitionable(service, "accept")
    payload = payload or DiscoveredServiceAcceptIn()
    return await _accept_row(db, service, source, payload, current_user)


@services_router.post("/bulk", response_model=DiscoveryBulkActionOut)
@limiter.limit("10/minute")
async def bulk_action(
    request: Request,
    payload: DiscoveryBulkActionIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bulk accept/dismiss (plan D, D-3 §2).

    Every id goes through the exact same visibility/role/transition checks as
    the unitary endpoints (``_get_visible_service`` + ``_assert_transitionable``)
    — this is a loop over the single-service path, not a bulk SQL statement,
    because ``accept`` may need to create a real ``Monitor`` per id. An id
    that is inaccessible or not transitionable is reported as a per-id
    failure, never as a 4xx for the whole call; each nested transaction
    (``db.begin_nested()``) isolates one id's failure from the rest, same
    pattern as ``services/escalation.py``.
    """
    results: list[dict] = []
    for service_id in payload.service_ids:
        try:
            async with db.begin_nested():
                service, source = await _get_visible_service(
                    service_id, current_user, db, TeamRole.editor
                )
                _assert_transitionable(service, payload.action)
                if payload.action == "dismiss":
                    body = await _dismiss_row(db, service, source, payload.reason, current_user)
                else:
                    body = await _accept_row(
                        db, service, source, DiscoveredServiceAcceptIn(), current_user
                    )
        except HTTPException as exc:
            results.append(
                {"service_id": service_id, "ok": False, "detail": str(exc.detail), "service": None}
            )
            continue
        results.append({"service_id": service_id, "ok": True, "detail": None, "service": body})
    return {"results": results}


async def _create_monitor_from_proposal(
    db: AsyncSession,
    service: DiscoveredService,
    source: DiscoverySource,
    payload: DiscoveredServiceAcceptIn,
    current_user: User,
) -> Monitor:
    """Build a ``MonitorCreate`` from the proposal + caller overrides and run
    it through the exact same creation path as ``POST /monitors`` — imported
    locally to avoid a module-level dependency from this router onto
    ``monitors.crud``/``alerts`` (mirrors how ``monitors/crud.py`` itself
    imports ``services.audit`` at point of use)."""
    from whatisup.api.v1.monitors.crud import _create_monitor_from_payload
    from whatisup.schemas.monitor import MonitorCreate

    fields = default_monitor_fields(service, source)
    overrides = payload.model_dump(
        exclude_unset=True, exclude={"alert_matrix_template_id", "alert_channel_ids"}
    )
    new_check_type = overrides.get("check_type")
    if new_check_type is not None and new_check_type != fields["check_type"]:
        # The prefill's port field (if any) was computed for its *own*
        # deduced check_type — it doesn't carry over to a different one.
        # Recompute from the same observed port instead of dropping it.
        for field in _PORT_OVERRIDE_FIELDS:
            fields.pop(field, None)
        new_port_field = port_field_for_check_type(new_check_type)
        if new_port_field is not None:
            fields[new_port_field] = service.port
    fields.update(overrides)
    if payload.alert_matrix_template_id is None:
        fields["alert_channel_ids"] = payload.alert_channel_ids

    monitor_create = MonitorCreate(**fields)

    await assert_can_assign_group(db, current_user, monitor_create.group_id)
    await assert_can_assign_team(db, current_user, monitor_create.team_id)

    monitor = await _create_monitor_from_payload(db, current_user, monitor_create)

    if payload.alert_matrix_template_id is not None:
        await _apply_alert_matrix_template(
            db, monitor, current_user, payload.alert_matrix_template_id, payload.alert_channel_ids
        )

    return monitor


async def _apply_alert_matrix_template(
    db: AsyncSession,
    monitor: Monitor,
    current_user: User,
    template_id: uuid.UUID,
    default_channel_ids: list[uuid.UUID],
) -> None:
    """Create one ``AlertRule`` per template row (plan D, D-2 §4).

    A row that names its own ``channel_ids`` uses those; otherwise it falls
    back to ``default_channel_ids``. A row that resolves to no channel at all
    is skipped rather than failing the whole accept — applying a template is
    a bonus on top of monitor creation, not a condition of it. Metric
    conditions (`metric_above`/`below`/`absent`) never appear in a matrix
    template — skipped the same way ``PUT /monitors/{id}/matrix`` rejects
    them, since they need a `metric_name` a template can't supply.
    """
    from pydantic import ValidationError

    from whatisup.api.v1.alerts import _MATRIX_RULE_FIELDS, _fetch_channels_by_ids
    from whatisup.models.alert import AlertRule
    from whatisup.models.alert_matrix_template import AlertMatrixTemplate
    from whatisup.schemas.alert import METRIC_CONDITIONS, AlertMatrixRow

    tpl = (
        await db.execute(select(AlertMatrixTemplate).where(AlertMatrixTemplate.id == template_id))
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert matrix template not found"
        )

    all_channel_ids: set[uuid.UUID] = set(default_channel_ids)
    for raw_row in tpl.rows:
        all_channel_ids.update(uuid.UUID(str(cid)) for cid in raw_row.get("channel_ids") or [])
    channels_by_id = {
        c.id: c for c in await _fetch_channels_by_ids(db, current_user, all_channel_ids)
    }

    for raw_row in tpl.rows:
        if raw_row.get("condition") in METRIC_CONDITIONS:
            continue
        row_channel_ids = raw_row.get("channel_ids") or [str(cid) for cid in default_channel_ids]
        try:
            # Template rows are admin-authored free-form dicts (no schema
            # enforced at template-creation time) — an unrecognised key must
            # not 500 the whole accept, just skip that one row.
            row = AlertMatrixRow.model_validate({**raw_row, "channel_ids": row_channel_ids})
        except ValidationError:
            continue
        resolved = [channels_by_id[cid] for cid in row.channel_ids if cid in channels_by_id]
        if not resolved:
            continue
        rule = AlertRule(owner_id=current_user.id, monitor_id=monitor.id, condition=row.condition)
        for field in _MATRIX_RULE_FIELDS:
            setattr(rule, field, getattr(row, field))
        rule.channels = resolved
        db.add(rule)
    await db.flush()
