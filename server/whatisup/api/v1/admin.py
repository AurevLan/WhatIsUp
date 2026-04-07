"""Admin endpoints: user management and global monitor overview."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import require_superadmin
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import hash_password_async
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.probe_group import ProbeGroup, probe_group_members, user_probe_group_access
from whatisup.models.system_settings import SystemSettings
from whatisup.models.user import User
from whatisup.schemas.probe_group import ProbeGroupCreate, ProbeGroupOut, ProbeGroupUpdate
from whatisup.schemas.user import AdminUserCreate, AdminUserOut, AdminUserUpdate, UserOut

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[AdminUserOut])
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    users = list((await db.execute(select(User).order_by(User.created_at))).scalars().all())
    if not users:
        return []

    user_ids = [u.id for u in users]
    count_rows = (
        await db.execute(
            select(Monitor.owner_id, func.count(Monitor.id).label("cnt"))
            .where(Monitor.owner_id.in_(user_ids))
            .group_by(Monitor.owner_id)
        )
    ).all()
    count_map = {str(r.owner_id): r.cnt for r in count_rows}

    out = []
    for u in users:
        d = UserOut.model_validate(u).model_dump()
        d["monitor_count"] = count_map.get(str(u.id), 0)
        out.append(d)
    return out


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_user(
    request: Request,
    payload: AdminUserCreate,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Generate username from email if not provided
    username = payload.username
    if username is None:
        base = str(payload.email).split("@")[0]
        # Keep only allowed chars
        base = "".join(c for c in base if c.isalnum() or c in "_-")[:30] or "user"
        # Ensure uniqueness by appending a short suffix if needed
        candidate = base
        suffix = 1
        while (
            await db.execute(select(User).where(User.username == candidate))
        ).scalar_one_or_none() is not None:
            candidate = f"{base}{suffix}"
            suffix += 1
        username = candidate

    existing = (
        await db.execute(
            select(User).where((User.email == str(payload.email)) | (User.username == username))
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        )

    user = User(
        email=str(payload.email),
        username=username,
        full_name=payload.full_name,
        hashed_password=await hash_password_async(payload.password),
        is_superadmin=payload.is_superadmin,
        can_create_monitors=payload.can_create_monitors,
    )
    db.add(user)
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(db, "admin.user.create", "user", user.id, user.username, None)
    logger.info("admin_user_created", user_id=str(user.id), admin_id=str(_admin.id))
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
@limiter.limit("30/minute")
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.email is not None:
        conflict = (
            await db.execute(
                select(User).where(User.email == str(payload.email), User.id != user_id)
            )
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already in use"
            )
        user.email = str(payload.email)

    if payload.full_name is not None:
        user.full_name = payload.full_name

    if payload.password is not None:
        user.hashed_password = await hash_password_async(payload.password)

    if payload.is_active is not None:
        user.is_active = payload.is_active

    if payload.can_create_monitors is not None:
        user.can_create_monitors = payload.can_create_monitors

    if payload.is_superadmin is not None:
        if user.id == admin.id and not payload.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove your own superadmin privileges",
            )
        user.is_superadmin = payload.is_superadmin

    await db.flush()
    from whatisup.services.audit import log_action

    await log_action(db, "admin.user.update", "user", user.id, user.username, None)
    logger.info("admin_user_updated", user_id=str(user.id), admin_id=str(admin.id))
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_user(
    request: Request,
    user_id: uuid.UUID,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account"
        )
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    from whatisup.services.audit import log_action

    await log_action(db, "admin.user.delete", "user", user.id, user.username, None)
    await db.delete(user)
    logger.info("admin_user_deleted", user_id=str(user_id), admin_id=str(admin.id))


# ---------------------------------------------------------------------------
# Monitors (read-only global view)
# ---------------------------------------------------------------------------


@router.get("/monitors")
@limiter.limit("30/minute")
async def list_all_monitors(
    request: Request,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (
        await db.execute(
            select(Monitor, User.username.label("owner_username"))
            .join(User, Monitor.owner_id == User.id)
            .order_by(Monitor.created_at.desc())
        )
    ).all()

    out = []
    for monitor, owner_username in rows:
        out.append(
            {
                "id": str(monitor.id),
                "name": monitor.name,
                "check_type": str(monitor.check_type) if monitor.check_type else None,
                "enabled": monitor.enabled,
                "url": monitor.url,
                "owner_id": str(monitor.owner_id),
                "owner_username": owner_username,
                "created_at": monitor.created_at.isoformat() if monitor.created_at else None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Probe Groups
# ---------------------------------------------------------------------------


async def _get_probe_group_or_404(
    group_id: uuid.UUID, db: AsyncSession
) -> ProbeGroup:
    group = (
        await db.execute(select(ProbeGroup).where(ProbeGroup.id == group_id))
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe group not found")
    return group


async def _load_probe_group_out(group_id: uuid.UUID, db: AsyncSession) -> ProbeGroupOut:
    """Re-fetch a probe group with relationships loaded for the response."""
    from whatisup.schemas.probe_group import ProbeGroupOut as _PGO

    group = (
        await db.execute(
            select(ProbeGroup)
            .options(selectinload(ProbeGroup.probes), selectinload(ProbeGroup.users))
            .where(ProbeGroup.id == group_id)
        )
    ).scalar_one()
    return _PGO.from_orm_obj(group)


@router.get("/probe-groups", response_model=list[ProbeGroupOut])
@limiter.limit("30/minute")
async def list_probe_groups(
    request: Request,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[ProbeGroupOut]:
    groups = (
        await db.execute(
            select(ProbeGroup)
            .options(selectinload(ProbeGroup.probes), selectinload(ProbeGroup.users))
            .order_by(ProbeGroup.created_at.desc())
        )
    ).scalars().all()
    return [ProbeGroupOut.from_orm_obj(g) for g in groups]


@router.post("/probe-groups", response_model=ProbeGroupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_probe_group(
    request: Request,
    payload: ProbeGroupCreate,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> ProbeGroupOut:
    existing = (
        await db.execute(select(ProbeGroup).where(ProbeGroup.name == payload.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Probe group name already exists"
        )
    group = ProbeGroup(name=payload.name, description=payload.description)
    db.add(group)
    await db.flush()
    logger.info("probe_group_created", group_id=str(group.id), admin_id=str(_admin.id))
    return await _load_probe_group_out(group.id, db)


@router.patch("/probe-groups/{group_id}", response_model=ProbeGroupOut)
@limiter.limit("30/minute")
async def update_probe_group(
    request: Request,
    group_id: uuid.UUID,
    payload: ProbeGroupUpdate,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> ProbeGroupOut:
    group = await _get_probe_group_or_404(group_id, db)
    if payload.name is not None:
        conflict = (
            await db.execute(
                select(ProbeGroup).where(
                    ProbeGroup.name == payload.name, ProbeGroup.id != group_id
                )
            )
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Probe group name already exists"
            )
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description
    await db.flush()
    logger.info("probe_group_updated", group_id=str(group_id), admin_id=str(_admin.id))
    return await _load_probe_group_out(group_id, db)


@router.delete("/probe-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_probe_group(
    request: Request,
    group_id: uuid.UUID,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    group = await _get_probe_group_or_404(group_id, db)
    await db.delete(group)
    logger.info("probe_group_deleted", group_id=str(group_id), admin_id=str(_admin.id))


@router.post("/probe-groups/{group_id}/probes", response_model=ProbeGroupOut)
@limiter.limit("30/minute")
async def add_probes_to_group(
    request: Request,
    group_id: uuid.UUID,
    payload: dict,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> ProbeGroupOut:
    await _get_probe_group_or_404(group_id, db)
    probe_ids: list[uuid.UUID] = [uuid.UUID(str(pid)) for pid in payload.get("probe_ids", [])]
    # Fetch existing probe_ids in group to avoid duplicate inserts
    existing = set(
        r[0] for r in (
            await db.execute(
                select(probe_group_members.c.probe_id).where(
                    probe_group_members.c.probe_group_id == group_id
                )
            )
        ).all()
    )
    for pid in probe_ids:
        if pid in existing:
            continue
        probe = (await db.execute(select(Probe).where(Probe.id == pid))).scalar_one_or_none()
        if probe is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Probe {pid} not found"
            )
        await db.execute(
            insert(probe_group_members).values(probe_group_id=group_id, probe_id=pid)
        )
    await db.flush()
    logger.info("probe_group_probes_added", group_id=str(group_id), admin_id=str(_admin.id))
    return await _load_probe_group_out(group_id, db)


@router.delete(
    "/probe-groups/{group_id}/probes/{probe_id}", status_code=status.HTTP_204_NO_CONTENT
)
@limiter.limit("30/minute")
async def remove_probe_from_group(
    request: Request,
    group_id: uuid.UUID,
    probe_id: uuid.UUID,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_probe_group_or_404(group_id, db)
    await db.execute(
        delete(probe_group_members).where(
            probe_group_members.c.probe_group_id == group_id,
            probe_group_members.c.probe_id == probe_id,
        )
    )
    await db.flush()
    logger.info(
        "probe_group_probe_removed",
        group_id=str(group_id),
        probe_id=str(probe_id),
        admin_id=str(_admin.id),
    )


@router.post("/probe-groups/{group_id}/users", response_model=ProbeGroupOut)
@limiter.limit("30/minute")
async def grant_group_access(
    request: Request,
    group_id: uuid.UUID,
    payload: dict,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> ProbeGroupOut:
    await _get_probe_group_or_404(group_id, db)
    user_ids: list[uuid.UUID] = [uuid.UUID(str(uid)) for uid in payload.get("user_ids", [])]
    existing = set(
        r[0] for r in (
            await db.execute(
                select(user_probe_group_access.c.user_id).where(
                    user_probe_group_access.c.probe_group_id == group_id
                )
            )
        ).all()
    )
    for uid in user_ids:
        if uid in existing:
            continue
        user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"User {uid} not found"
            )
        await db.execute(
            insert(user_probe_group_access).values(user_id=uid, probe_group_id=group_id)
        )
    await db.flush()
    logger.info("probe_group_users_granted", group_id=str(group_id), admin_id=str(_admin.id))
    return await _load_probe_group_out(group_id, db)


@router.delete(
    "/probe-groups/{group_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
@limiter.limit("30/minute")
async def revoke_group_access(
    request: Request,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_probe_group_or_404(group_id, db)
    await db.execute(
        delete(user_probe_group_access).where(
            user_probe_group_access.c.user_id == user_id,
            user_probe_group_access.c.probe_group_id == group_id,
        )
    )
    await db.flush()
    logger.info(
        "probe_group_user_revoked",
        group_id=str(group_id),
        user_id=str(user_id),
        admin_id=str(_admin.id),
    )


# ---------------------------------------------------------------------------
# OIDC / SSO settings
# ---------------------------------------------------------------------------


class OidcSettingsUpdate(BaseModel):
    oidc_enabled: bool = False
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    # None = keep existing secret unchanged; "" = clear; non-empty = new value
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_auto_provision: bool = True


def _mask_oidc_row(row: SystemSettings) -> dict:
    return {
        "source": "db",
        "oidc_enabled": row.oidc_enabled,
        "oidc_issuer_url": row.oidc_issuer_url,
        "oidc_client_id": row.oidc_client_id,
        "oidc_client_secret_set": bool(row.oidc_client_secret),
        "oidc_redirect_uri": row.oidc_redirect_uri,
        "oidc_scopes": row.oidc_scopes,
        "oidc_auto_provision": row.oidc_auto_provision,
    }


@router.get("/settings/oidc")
@limiter.limit("30/minute")
async def get_oidc_settings(
    request: Request,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    ).scalar_one_or_none()
    if row is not None:
        return _mask_oidc_row(row)

    # No DB row yet — surface env var defaults (read-only preview)
    from whatisup.core.config import get_settings

    s = get_settings()
    return {
        "source": "env",
        "oidc_enabled": s.oidc_enabled,
        "oidc_issuer_url": s.oidc_issuer_url,
        "oidc_client_id": s.oidc_client_id,
        "oidc_client_secret_set": bool(s.oidc_client_secret),
        "oidc_redirect_uri": s.oidc_redirect_uri,
        "oidc_scopes": s.oidc_scopes,
        "oidc_auto_provision": s.oidc_auto_provision,
    }


@router.put("/settings/oidc")
@limiter.limit("10/minute")
async def update_oidc_settings(
    request: Request,
    payload: OidcSettingsUpdate,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from whatisup.core.security import _get_fernet

    row = (
        await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    ).scalar_one_or_none()
    if row is None:
        from datetime import UTC, datetime

        row = SystemSettings(id=1, updated_at=datetime.now(UTC))
        db.add(row)

    row.oidc_enabled = payload.oidc_enabled
    row.oidc_issuer_url = payload.oidc_issuer_url or ""
    row.oidc_client_id = payload.oidc_client_id or ""
    row.oidc_redirect_uri = payload.oidc_redirect_uri or ""
    row.oidc_scopes = payload.oidc_scopes or "openid email profile"
    row.oidc_auto_provision = payload.oidc_auto_provision

    if payload.oidc_client_secret is not None:
        if payload.oidc_client_secret:
            fernet = _get_fernet()
            row.oidc_client_secret = (
                fernet.encrypt(payload.oidc_client_secret.encode()).decode()
                if fernet
                else payload.oidc_client_secret
            )
        else:
            row.oidc_client_secret = ""

    await db.flush()
    logger.info("oidc_settings_updated", admin_id=str(admin.id))
    return _mask_oidc_row(row)
