"""User API key management endpoints."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import generate_user_api_key, hash_api_key
from whatisup.models.api_key import UserApiKey
from whatisup.models.user import User
from whatisup.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyOut

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api-keys", tags=["api-keys"])

_MAX_KEYS_PER_USER = 20


async def _get_key_or_404(key_id: uuid.UUID, user: User, db: AsyncSession) -> UserApiKey:
    row = (
        await db.execute(
            select(UserApiKey).where(UserApiKey.id == key_id, UserApiKey.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return row


@router.get("/", response_model=list[ApiKeyOut])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserApiKey]:
    """List all API keys for the current user (never returns the raw key)."""
    rows = (
        await db.execute(
            select(UserApiKey)
            .where(UserApiKey.user_id == current_user.id)
            .order_by(UserApiKey.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.post("/", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_api_key(
    request: Request,
    payload: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Create a new API key.  The raw key is returned **once** — store it safely."""
    # Enforce per-user cap
    count = (
        await db.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == current_user.id,
                UserApiKey.is_revoked.is_(False),
            )
        )
    ).scalars().all()
    if len(count) >= _MAX_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {_MAX_KEYS_PER_USER} active API keys per user",
        )

    raw_key = generate_user_api_key()
    row = UserApiKey(
        user_id=current_user.id,
        name=payload.name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:12],  # "wiu_u_XXXXXX"
        expires_at=payload.expires_at,
    )
    db.add(row)
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(db, "api_key.create", "api_key", row.id, payload.name, current_user.id)
    logger.info("api_key_created", user_id=str(current_user.id), key_name=payload.name)

    return ApiKeyCreateResponse(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        is_revoked=row.is_revoked,
        key=raw_key,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke (soft-delete) an API key.  Cached entries expire within 5 minutes."""
    row = await _get_key_or_404(key_id, current_user, db)
    row.is_revoked = True

    from whatisup.services.audit import log_action

    await log_action(db, "api_key.revoke", "api_key", row.id, row.name, current_user.id)
    logger.info("api_key_revoked", user_id=str(current_user.id), key_id=str(key_id))
