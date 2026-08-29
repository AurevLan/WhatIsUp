"""FastAPI dependencies: current user, superadmin check, probe auth."""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from fastapi import Depends, Header, HTTPException, Request, Security, status
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

if TYPE_CHECKING:
    from whatisup.models.probe_group import ProbeGroup

logger = structlog.get_logger(__name__)

# auto_error=False so we can fall back to X-Api-Key when no Bearer token is present
bearer_scheme = HTTPBearer(auto_error=False)

_USER_KEY_PREFIX = "wiu_u_"


def _hash_fingerprint(api_key_hash: str) -> str:
    """Short fingerprint of a stored bcrypt hash, embedded in cache values (SA6).

    Binds an auth cache entry to the exact credential generation it was verified
    against. After a probe key rotation the DB hash changes, so the fingerprint of
    any stale entry (e.g. one re-written by a bcrypt slow path that was in flight
    while the rotation committed) no longer matches the live hash: the fast path
    rejects and evicts it instead of letting the old key re-authenticate for
    another cache TTL. Used for both probe and user API-key caches.
    """
    # SHA-256 used as a comparison tag only (not for password hashing — the
    # underlying credential is already bcrypt-hashed).
    return hashlib.sha256(api_key_hash.encode(), usedforsecurity=False).hexdigest()[:16]


# Back-compat alias — probe-auth cache tests reference this name.
_probe_hash_fingerprint = _hash_fingerprint


async def _auth_via_user_api_key(raw_key: str, db: AsyncSession) -> tuple[User, list[str]]:
    """Authenticate using a user API key (fast Redis cache + slow bcrypt fallback).

    Fast path: ``SHA-256(key)`` → ``user_id|key_id|hash_fingerprint`` cached in
    Redis (TTL 60s). The fingerprint is re-checked against the live key row the
    fast path loads anyway (constant-time ``hmac.compare_digest``), and the row's
    ``is_revoked`` / ``expires_at`` are re-validated — so a revoked or expired key
    stops authenticating on sight, without waiting for the cache TTL.

    Revocation hardening (S4, mirrors probe SA6): the cache value carries a
    fingerprint of the bcrypt hash the key was verified against, a reverse index
    (``user_api_rev:{key_id} → digest``) lets ``revoke`` evict the forward entry
    precisely, and the slow path only writes the cache if the key is still live —
    so a bcrypt verification in flight while ``revoke`` commits cannot re-cache a
    credential that was just invalidated.

    Redis is a pure accelerator on this path (R-2): any outage degrades to a
    cache miss + bcrypt fallback instead of failing the request.
    """
    from whatisup.core.redis import redis_delete_safe, redis_get_safe, redis_setex_safe

    # SHA-256 used as cache index only (not for password hashing — bcrypt handles that)
    digest = hashlib.sha256(
        raw_key.encode(),
        usedforsecurity=False,
    ).hexdigest()[:32]
    cache_key = f"whatisup:user_api:{digest}"

    now = datetime.now(UTC)
    cached = await redis_get_safe(cache_key)
    if cached:
        if isinstance(cached, bytes):  # decode_responses=False clients (e.g. fakeredis)
            cached = cached.decode()
        parts = cached.split("|")
        user_pk: uuid.UUID | None = None
        key_pk: uuid.UUID | None = None
        cached_fp = ""
        if len(parts) == 3:
            try:
                user_pk = uuid.UUID(parts[0])
                key_pk = uuid.UUID(parts[1])
                cached_fp = parts[2]
            except ValueError:
                user_pk = key_pk = None  # corrupted value → treat as stale
        key_row = (
            (
                await db.execute(
                    select(UserApiKey).where(
                        UserApiKey.id == key_pk, UserApiKey.is_revoked.is_(False)
                    )
                )
            ).scalar_one_or_none()
            if key_pk is not None
            else None
        )
        fresh = (
            key_row is not None
            and key_row.user_id == user_pk
            and not (key_row.expires_at and key_row.expires_at < now)
            and hmac.compare_digest(cached_fp, _hash_fingerprint(key_row.key_hash))
        )
        if fresh:
            user = (
                await db.execute(select(User).where(User.id == key_row.user_id, User.is_active))
            ).scalar_one_or_none()
            if user is not None:
                observe_auth_cache("user_api_key", hit=True)
                return user, list(key_row.scopes or [])
        # Cache stale — key revoked/expired/deleted, user deactivated, fingerprint
        # mismatch, or pre-S4 value format. Evict the forward entry (and the reverse
        # index if we could parse the key id) and fall through to the slow path.
        stale_keys = [cache_key]
        if key_pk is not None:
            stale_keys.append(f"whatisup:user_api_rev:{key_pk}")
        await redis_delete_safe(*stale_keys)
    observe_auth_cache("user_api_key", hit=False)

    # Slow path — find the matching key row
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

    # Snapshot the hash we verified against — it is what the cache entry must be
    # fingerprinted with, even if the row is invalidated concurrently.
    verified_hash = api_key_row.key_hash
    key_id = api_key_row.id
    key_scopes = list(api_key_row.scopes or [])

    user = (
        await db.execute(select(User).where(User.id == api_key_row.user_id, User.is_active))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    api_key_row.last_used_at = now
    logger.info("user_api_key_auth_ok", user_id=str(user.id), key_name=api_key_row.name)

    # Guarded write (S4): this slow path may have verified the key against a row
    # snapshot read BEFORE a concurrent revoke committed. Writing the cache
    # unconditionally would re-authenticate the revoked key for another TTL after
    # revoke already evicted it. Re-read the live row and only cache if the
    # credential we verified is still valid; the fingerprint stored in the value
    # lets the fast path re-check this on every hit for free.
    fingerprint = _hash_fingerprint(verified_hash)
    live = (
        await db.execute(
            select(
                UserApiKey.key_hash,
                UserApiKey.is_revoked,
                UserApiKey.expires_at,
            ).where(UserApiKey.id == key_id)
        )
    ).one_or_none()
    now_write = datetime.now(UTC)
    stale = (
        live is None
        or live.is_revoked
        or (live.expires_at and live.expires_at < now_write)
        or not hmac.compare_digest(_hash_fingerprint(live.key_hash), fingerprint)
    )
    if stale:
        logger.info("user_api_key_cache_write_skipped_stale", key_id=str(key_id))
        return user, key_scopes
    await redis_setex_safe(cache_key, 60, f"{user.id}|{key_id}|{fingerprint}")
    await redis_setex_safe(f"whatisup:user_api_rev:{key_id}", 60, digest)
    return user, key_scopes


# Méthodes considérées comme des lectures : elles ne modifient rien côté
# serveur. Tout le reste exige le scope "write".
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _enforce_api_key_scopes(request: Request, scopes: list[str]) -> None:
    """Refuse une écriture faite avec une clé API en lecture seule.

    Appliqué ici plutôt que par endpoint : `get_current_user` est le passage
    obligé de toute route authentifiée, donc aucune ne peut être oubliée. Les
    sessions JWT ne sont pas concernées — seule une clé API porte des scopes.
    """
    if request.method in _READ_METHODS:
        return
    if "write" in scopes:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This API key is read-only",
    )


async def get_current_user(
    request: Request,
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
    raw_api_key = None
    if token and token.startswith(_USER_KEY_PREFIX):
        raw_api_key = token
    elif x_api_key and x_api_key.startswith(_USER_KEY_PREFIX):
        raw_api_key = x_api_key

    if raw_api_key is not None:
        user, scopes = await _auth_via_user_api_key(raw_api_key, db)
        _enforce_api_key_scopes(request, scopes)
        return user

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

    Fast path: SHA-256(key) → ``probe_id|hash_fingerprint`` cached in Redis
    (TTL 60s); the fingerprint is checked against the probe row loaded anyway.
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

    Rotation hardening (SA6): the cache value carries a fingerprint of the
    bcrypt hash the key was verified against. The fast path checks it against
    the probe row it loads anyway (no extra DB read), and the slow path only
    writes the cache if the verified hash is still the live one in DB — so a
    bcrypt verification in flight during ``rotate-key`` cannot re-cache the
    old key after the rotation's eviction.
    """
    if not x_probe_api_key.startswith("wiu_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid probe API key",
        )

    # Fast path: try Redis cache (key is SHA-256 of the raw API key — safe, preimage-resistant).
    # Redis is a pure accelerator here (R-2): outage → cache miss + bcrypt fallback, not a 500.
    from whatisup.core.redis import redis_delete_safe, redis_get_safe, redis_setex_safe

    # SHA-256 used as cache index only (not for password hashing — bcrypt handles that)
    digest = hashlib.sha256(
        x_probe_api_key.encode(),
        usedforsecurity=False,
    ).hexdigest()[:32]
    cache_key = f"whatisup:probe_auth:{digest}"
    cached = await redis_get_safe(cache_key)
    if cached:
        if isinstance(cached, bytes):  # decode_responses=False clients (e.g. fakeredis)
            cached = cached.decode()
        cached_id, _, cached_fp = cached.partition("|")
        try:
            probe_pk = uuid.UUID(cached_id)
        except ValueError:
            probe_pk = None  # corrupted value → treat as stale
        probe = (
            (
                await db.execute(select(Probe).where(Probe.id == probe_pk, Probe.is_active))
            ).scalar_one_or_none()
            if probe_pk is not None
            else None
        )
        if probe is not None and cached_fp == _probe_hash_fingerprint(probe.api_key_hash):
            observe_auth_cache("probe_api_key", hit=True)
            return probe
        # Cache stale — probe deactivated/deleted, key rotated since the entry
        # was written (fingerprint mismatch), or pre-fingerprint value format.
        # Evict and fall through to the slow path: only the credential that
        # matches the CURRENT hash can (re-)authenticate.
        await redis_delete_safe(cache_key)
    observe_auth_cache("probe_api_key", hit=False)

    async def _accept(probe: Probe, verified_hash: str) -> Probe:
        # Cache the result (TTL 60s) + reverse index (probe_id → key digest) so key
        # rotation / deactivation can evict the forward entry precisely without
        # holding the raw key.
        #
        # Guarded write (SA6): this slow path may have verified the key against a
        # hash snapshot read BEFORE a concurrent rotate-key committed. Writing the
        # cache unconditionally here would re-authenticate the OLD key for another
        # TTL after the rotation already evicted it. Re-read the live hash and
        # only cache if the credential we verified is still current; the
        # fingerprint stored in the value lets the fast path re-check this on
        # every hit for free (the probe row is loaded there anyway).
        fingerprint = _probe_hash_fingerprint(verified_hash)
        current_hash = (
            await db.execute(select(Probe.api_key_hash).where(Probe.id == probe.id))
        ).scalar_one_or_none()
        if current_hash is None or _probe_hash_fingerprint(current_hash) != fingerprint:
            logger.info("probe_auth_cache_write_skipped_stale_hash", probe_id=str(probe.id))
            return probe
        await redis_setex_safe(cache_key, 60, f"{probe.id}|{fingerprint}")
        await redis_setex_safe(f"whatisup:probe_auth_rev:{probe.id}", 60, digest)
        return probe

    # New-scheme slow path: indexed prefix lookup → at most one candidate, one bcrypt.
    prefix = extract_probe_key_prefix(x_probe_api_key)
    if prefix is not None:
        candidate = (
            await db.execute(select(Probe).where(Probe.api_key_prefix == prefix, Probe.is_active))
        ).scalar_one_or_none()
        if candidate is not None:
            # Snapshot the hash we verify against: it is what the cache entry
            # must be fingerprinted with, even if the row changes concurrently.
            verified_hash = candidate.api_key_hash
            if verify_api_key(x_probe_api_key, verified_hash):
                return await _accept(candidate, verified_hash)
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
        verified_hash = probe.api_key_hash
        if verify_api_key(x_probe_api_key, verified_hash):
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
            return await _accept(probe, verified_hash)

    logger.warning("probe_auth_failed", key_prefix=x_probe_api_key[:10])
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid probe API key")


async def invalidate_probe_auth_cache(probe_id: uuid.UUID) -> None:
    """Immediately evict the Redis probe-auth cache entry for a probe.

    The forward cache maps ``SHA-256(raw_key)[:32] → probe_id`` and the raw key
    is not available at rotation/deactivation time. We therefore keep a reverse
    index (``probe_id → digest``) written whenever a key is cached, and use it
    here to delete the forward entry. Without this the previous key would keep
    authenticating on the fast path until the cache TTL expires.

    Fail-open on Redis outage (R-2): a skipped eviction is defused by the hash
    fingerprint in the cache value (fast path rejects it against the live row)
    and bounded by the 60 s TTL — while failing here would 500 the rotation
    or deactivation itself.
    """
    from whatisup.core.redis import redis_delete_safe, redis_get_safe

    rev_key = f"whatisup:probe_auth_rev:{probe_id}"
    digest = await redis_get_safe(rev_key)
    if digest:
        if isinstance(digest, bytes):  # decode_responses=False clients (e.g. fakeredis)
            digest = digest.decode()
        await redis_delete_safe(f"whatisup:probe_auth:{digest}")
    await redis_delete_safe(rev_key)


async def invalidate_user_api_key_cache(key_id: uuid.UUID) -> None:
    """Immediately evict the Redis user-API-key auth cache entry for a key.

    The forward cache maps ``SHA-256(raw_key)[:32] → user_id|key_id|fingerprint``
    and the raw key is not available at revocation time. We therefore keep a
    reverse index (``key_id → digest``) written whenever a key is cached, and use
    it here to delete the forward entry. Without this a revoked key would keep
    authenticating on the fast path until the cache TTL (≤60 s) expires.

    Fail-open on Redis outage (R-2): a skipped eviction is defused by the hash
    fingerprint in the cache value (fast path rejects it against the live row)
    and bounded by the 60 s TTL — while failing here would 500 the revocation
    itself.
    """
    from whatisup.core.redis import redis_delete_safe, redis_get_safe

    rev_key = f"whatisup:user_api_rev:{key_id}"
    digest = await redis_get_safe(rev_key)
    if digest:
        if isinstance(digest, bytes):  # decode_responses=False clients (e.g. fakeredis)
            digest = digest.decode()
        await redis_delete_safe(f"whatisup:user_api:{digest}")
    await redis_delete_safe(rev_key)


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


async def assert_can_assign_probe_group(
    db: AsyncSession, user: User, probe_group_id: uuid.UUID
) -> "ProbeGroup":
    """Reject targeting a ``ProbeGroup`` the user has no visibility into
    (plan E, E-2) — same tenancy rule ``GET /probes/`` already applies:
    ``user_probe_group_access`` grants it, superadmin is exempt. Unlike
    ``assert_can_assign_team``/``assert_can_assign_group`` this has no
    "``None`` means unset, always allowed" case — a group-targeted discovery
    source always names a real group. Returns the group (with ``.probes``
    eager-loaded, ``lazy="selectin"`` on the model) so the caller can compute
    capability counts without a second query.
    """
    from whatisup.models.probe_group import ProbeGroup, user_probe_group_access

    group = (
        await db.execute(select(ProbeGroup).where(ProbeGroup.id == probe_group_id))
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe group not found")
    if user.is_superadmin:
        return group
    visible = (
        await db.execute(
            select(user_probe_group_access.c.probe_group_id).where(
                user_probe_group_access.c.user_id == user.id,
                user_probe_group_access.c.probe_group_id == probe_group_id,
            )
        )
    ).scalar_one_or_none()
    if visible is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return group


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
