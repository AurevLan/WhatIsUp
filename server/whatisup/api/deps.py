"""FastAPI dependencies: current user, superadmin check, probe auth."""

import hashlib
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import get_db
from whatisup.core.security import decode_token, verify_api_key
from whatisup.models.api_key import UserApiKey
from whatisup.models.probe import Probe
from whatisup.models.team import TeamMembership, TeamRole
from whatisup.models.user import User

logger = structlog.get_logger(__name__)

# auto_error=False so we can fall back to X-Api-Key when no Bearer token is present
bearer_scheme = HTTPBearer(auto_error=False)

_USER_KEY_PREFIX = "wiu_u_"


async def _auth_via_user_api_key(raw_key: str, db: AsyncSession) -> User:
    """Authenticate using a user API key (fast Redis cache + slow bcrypt fallback)."""
    from whatisup.core.redis import get_redis

    redis = get_redis()
    # SHA-256 used as cache index only (not for password hashing — bcrypt handles that)
    cache_key = (
        f"whatisup:user_api:{hashlib.sha256(raw_key.encode()).hexdigest()[:32]}"  # noqa: S324
    )

    cached_id = await redis.get(cache_key)
    if cached_id:
        user = (
            await db.execute(select(User).where(User.id == uuid.UUID(cached_id), User.is_active))
        ).scalar_one_or_none()
        if user is not None:
            return user
        await redis.delete(cache_key)

    # Slow path — find the matching key row
    now = datetime.now(UTC)
    api_key_row = None
    rows = (
        await db.execute(
            select(UserApiKey).where(
                UserApiKey.is_revoked.is_(False),
            )
        )
    ).scalars().all()

    for row in rows:
        if row.expires_at and row.expires_at < now:
            continue
        if verify_api_key(raw_key, row.key_hash):
            api_key_row = row
            break

    if api_key_row is None:
        logger.warning("user_api_key_auth_failed", key_prefix=raw_key[:12])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    user = (
        await db.execute(
            select(User).where(User.id == api_key_row.user_id, User.is_active)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Update last_used_at and populate cache
    api_key_row.last_used_at = now
    await redis.setex(cache_key, 60, str(user.id))
    logger.info("user_api_key_auth_ok", user_id=str(user.id), key_name=api_key_row.name)
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate via JWT Bearer token **or** user API key.

    Priority:
    1. ``Authorization: Bearer <jwt>``
    2. ``Authorization: Bearer wiu_u_<key>``  (API key as Bearer)
    3. ``X-Api-Key: wiu_u_<key>``
    """
    token: str | None = credentials.credentials if credentials else None

    # --- API key paths ---
    if token and token.startswith(_USER_KEY_PREFIX):
        return await _auth_via_user_api_key(token, db)

    if x_api_key and x_api_key.startswith(_USER_KEY_PREFIX):
        return await _auth_via_user_api_key(x_api_key, db)

    # --- JWT path ---
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token, "access")
        user_id = uuid.UUID(payload["sub"])
    except (InvalidTokenError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")
    return current_user


async def get_current_probe(
    x_probe_api_key: str = Header(..., alias="X-Probe-Api-Key"),
    db: AsyncSession = Depends(get_db),
) -> Probe:
    """Authenticate a probe via its API key.

    Fast path: SHA-256(key) → probe_id cached in Redis (TTL 300s).
    Slow path (cache miss): full bcrypt scan, then populate cache.
    """
    if not x_probe_api_key.startswith("wiu_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid probe API key",
        )

    # Fast path: try Redis cache (key is SHA-256 of the raw API key — safe, preimage-resistant)
    from whatisup.core.redis import get_redis

    redis = get_redis()
    # SHA-256 used as cache index only (not for password hashing — bcrypt handles that)
    cache_key = f"whatisup:probe_auth:{hashlib.sha256(x_probe_api_key.encode()).hexdigest()[:32]}"  # noqa: S324
    cached_id = await redis.get(cache_key)
    if cached_id:
        probe = (
            await db.execute(select(Probe).where(Probe.id == cached_id, Probe.is_active))
        ).scalar_one_or_none()
        if probe is not None:
            return probe
        # Cache stale (probe deactivated/deleted) — fall through to slow path
        await redis.delete(cache_key)

    # Slow path: full bcrypt scan
    probes = (await db.execute(select(Probe).where(Probe.is_active))).scalars().all()

    for probe in probes:
        if verify_api_key(x_probe_api_key, probe.api_key_hash):
            # Cache the result (TTL 60s)
            await redis.setex(cache_key, 60, str(probe.id))
            return probe

    logger.warning("probe_auth_failed", key_prefix=x_probe_api_key[:10])
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid probe API key")


# ── Team-aware access control ────────────────────────────────────────────────

# Minimum role required for each permission level
_ROLE_HIERARCHY: dict[str, int] = {
    TeamRole.viewer: 0,
    TeamRole.editor: 1,
    TeamRole.admin: 2,
    TeamRole.owner: 3,
}


async def get_user_team_ids(
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> list[uuid.UUID]:
    """Return team IDs the user belongs to with at least *min_role*.

    Used as WHERE filter on list endpoints: resources visible if
    ``owner_id == user.id OR team_id IN get_user_team_ids()``.
    """
    min_level = _ROLE_HIERARCHY[min_role]
    rows = (
        await db.execute(
            select(TeamMembership.team_id, TeamMembership.role).where(
                TeamMembership.user_id == user.id,
            )
        )
    ).all()
    return [
        r.team_id
        for r in rows
        if _ROLE_HIERARCHY.get(r.role, 0) >= min_level
    ]


async def _get_user_team_ids_with_roles(
    user: User,
    db: AsyncSession,
) -> dict[uuid.UUID, TeamRole]:
    """Return {team_id: role} for all teams the user belongs to."""
    rows = (
        await db.execute(
            select(TeamMembership.team_id, TeamMembership.role).where(
                TeamMembership.user_id == user.id,
            )
        )
    ).all()
    return {r.team_id: r.role for r in rows}


def _has_min_role(role: TeamRole, min_role: TeamRole) -> bool:
    """Check if *role* meets the minimum required level."""
    return _ROLE_HIERARCHY.get(role, 0) >= _ROLE_HIERARCHY.get(min_role, 0)


async def check_resource_access(
    resource,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> None:
    """Raise 403 if user cannot access resource at the given permission level.

    Access is granted if ANY of:
    - user is superadmin
    - user is the owner (resource.owner_id == user.id)
    - resource belongs to a team the user is a member of with >= min_role

    For create/update operations, pass ``min_role=TeamRole.editor``.
    For delete/admin operations, pass ``min_role=TeamRole.admin``.
    """
    if user.is_superadmin:
        return

    # Owner always has full access
    if hasattr(resource, "owner_id") and resource.owner_id == user.id:
        return

    # Team access
    team_id = getattr(resource, "team_id", None)
    if team_id is not None:
        team_roles = await _get_user_team_ids_with_roles(user, db)
        role = team_roles.get(team_id)
        if role is not None and _has_min_role(role, min_role):
            return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


def build_access_filter(model, user: User, team_ids: list[uuid.UUID]):
    """Build a SQLAlchemy WHERE clause for list endpoints.

    Returns a filter that matches resources owned by the user OR belonging
    to one of their teams. Superadmins should skip this filter entirely.

    Usage::

        if not user.is_superadmin:
            team_ids = await get_user_team_ids(user, db)
            query = query.where(build_access_filter(Monitor, user, team_ids))
    """
    from sqlalchemy import or_

    conditions = [model.owner_id == user.id]
    if team_ids:
        conditions.append(model.team_id.in_(team_ids))
    if len(conditions) == 1:
        return conditions[0]
    return or_(*conditions)
