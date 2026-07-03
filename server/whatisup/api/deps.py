"""FastAPI dependencies: current user, superadmin check, probe auth."""

import hashlib
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import get_db
from whatisup.core.metrics import observe_auth_cache
from whatisup.core.security import decode_token, extract_probe_key_prefix, verify_api_key
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
    digest = hashlib.sha256(
        raw_key.encode(),
        usedforsecurity=False,
    ).hexdigest()[:32]
    cache_key = f"whatisup:user_api:{digest}"

    cached_id = await redis.get(cache_key)
    if cached_id:
        user = (
            await db.execute(select(User).where(User.id == uuid.UUID(cached_id), User.is_active))
        ).scalar_one_or_none()
        if user is not None:
            observe_auth_cache("user_api_key", hit=True)
            return user
        await redis.delete(cache_key)
    observe_auth_cache("user_api_key", hit=False)

    # Slow path — find the matching key row
    now = datetime.now(UTC)
    api_key_row = None
    rows = (
        (
            await db.execute(
                select(UserApiKey).where(
                    UserApiKey.is_revoked.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )

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
        await db.execute(select(User).where(User.id == api_key_row.user_id, User.is_active))
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

    Fast path: SHA-256(key) → probe_id cached in Redis (TTL 60s).
    Slow path (cache miss):

    - New-scheme key ``wiu_<prefix>.<secret>`` → resolve the single candidate by
      its indexed public prefix and run exactly ONE bcrypt verification.
    - Legacy key ``wiu_<secret>`` (no prefix derivable) → fall back to the bcrypt
      scan, restricted to probes that have not yet migrated
      (``api_key_prefix IS NULL``). The scan set shrinks to zero as probes rotate.
    - New-scheme key whose prefix matches no row (e.g. ``api_key_prefix`` wiped
      by a downgrade/upgrade cycle) → same NULL-prefix scan; on bcrypt match the
      prefix is re-populated (self-healing, no manual rotation needed).

    Both slow-path branches then populate the same forward cache + reverse index.
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
    digest = hashlib.sha256(
        x_probe_api_key.encode(),
        usedforsecurity=False,
    ).hexdigest()[:32]
    cache_key = f"whatisup:probe_auth:{digest}"
    cached_id = await redis.get(cache_key)
    if cached_id:
        probe = (
            await db.execute(select(Probe).where(Probe.id == cached_id, Probe.is_active))
        ).scalar_one_or_none()
        if probe is not None:
            observe_auth_cache("probe_api_key", hit=True)
            return probe
        # Cache stale (probe deactivated/deleted) — fall through to slow path
        await redis.delete(cache_key)
    observe_auth_cache("probe_api_key", hit=False)

    async def _accept(probe: Probe) -> Probe:
        # Cache the result (TTL 60s) + reverse index (probe_id → key digest) so key
        # rotation / deactivation can evict the forward entry precisely without
        # holding the raw key.
        await redis.setex(cache_key, 60, str(probe.id))
        await redis.setex(f"whatisup:probe_auth_rev:{probe.id}", 60, digest)
        return probe

    # New-scheme slow path: indexed prefix lookup → at most one candidate, one bcrypt.
    prefix = extract_probe_key_prefix(x_probe_api_key)
    if prefix is not None:
        candidate = (
            await db.execute(select(Probe).where(Probe.api_key_prefix == prefix, Probe.is_active))
        ).scalar_one_or_none()
        if candidate is not None:
            if verify_api_key(x_probe_api_key, candidate.api_key_hash):
                return await _accept(candidate)
            # Prefix resolved but secret wrong → hard reject, never fall back
            # to the scan (exactly one bcrypt per attempt on this path).
            logger.warning("probe_auth_failed", key_prefix=x_probe_api_key[:10])
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid probe API key"
            )
        # Prefix miss: ``api_key_prefix`` may have been wiped in DB (e.g. an
        # alembic downgrade dropping the column, then upgrade recreating it
        # NULL). Fall through to the NULL-prefix scan below and self-heal on
        # match — free on a healthy fleet, where that scan set is empty.

    # Legacy slow path: bcrypt scan restricted to un-migrated probes (no prefix).
    probes = (
        (await db.execute(select(Probe).where(Probe.is_active, Probe.api_key_prefix.is_(None))))
        .scalars()
        .all()
    )

    for probe in probes:
        if verify_api_key(x_probe_api_key, probe.api_key_hash):
            if prefix is not None:
                # Self-heal: re-populate the wiped prefix so the next auth for
                # this probe takes the indexed fast path again (same mechanics
                # as the opportunistic migration performed on key rotation).
                # Guarded on IS NULL: a concurrent rotation committing a new
                # prefix mid-flight must not be clobbered by this stale value.
                await db.execute(
                    update(Probe)
                    .where(Probe.id == probe.id, Probe.api_key_prefix.is_(None))
                    .values(api_key_prefix=prefix)
                )
            return await _accept(probe)

    logger.warning("probe_auth_failed", key_prefix=x_probe_api_key[:10])
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid probe API key")


async def invalidate_probe_auth_cache(probe_id: uuid.UUID) -> None:
    """Immediately evict the Redis probe-auth cache entry for a probe.

    The forward cache maps ``SHA-256(raw_key)[:32] → probe_id`` and the raw key
    is not available at rotation/deactivation time. We therefore keep a reverse
    index (``probe_id → digest``) written whenever a key is cached, and use it
    here to delete the forward entry. Without this the previous key would keep
    authenticating on the fast path until the cache TTL expires.
    """
    from whatisup.core.redis import get_redis

    redis = get_redis()
    rev_key = f"whatisup:probe_auth_rev:{probe_id}"
    digest = await redis.get(rev_key)
    if digest:
        await redis.delete(f"whatisup:probe_auth:{digest}")
    await redis.delete(rev_key)


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
    return [r.team_id for r in rows if _ROLE_HIERARCHY.get(r.role, 0) >= min_level]


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


async def assert_can_assign_team(db: AsyncSession, user: User, team_id: uuid.UUID | None) -> None:
    """Reject assigning a resource to a team the user is not an editor+ member of.

    Without this check a user can attach their monitor/group to an arbitrary
    ``team_id``, leaking it into another tenant's scope (status pages, team views).
    ``None`` means "no team" and is always allowed.
    """
    if team_id is None or user.is_superadmin:
        return
    allowed = await get_user_team_ids(user, db, min_role=TeamRole.editor)
    if team_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an editor of the target team",
        )


async def assert_can_assign_group(db: AsyncSession, user: User, group_id: uuid.UUID | None) -> None:
    """Reject assigning a monitor to a group the user cannot access (editor+).

    Prevents cross-tenant poisoning of a victim's public status page via an
    attacker-chosen ``group_id``. ``None`` means "ungrouped" and is allowed.
    """
    if group_id is None or user.is_superadmin:
        return
    from whatisup.models.monitor import MonitorGroup

    group = (
        await db.execute(select(MonitorGroup).where(MonitorGroup.id == group_id))
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    await check_resource_access(group, user, db, min_role=TeamRole.editor)


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
