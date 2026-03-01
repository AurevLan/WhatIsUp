"""Authentication endpoints: register, login, refresh, logout, me."""

import uuid
from datetime import timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.redis import get_redis
from whatisup.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from whatisup.models.user import User
from whatisup.schemas.user import TokenRefreshRequest, TokenResponse, UserCreate, UserOut

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    # Check email/username uniqueness
    existing = (await db.execute(
        select(User).where(
            (User.email == payload.email) | (User.username == payload.username)
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        )

    # First registered user becomes superadmin
    user_count = (await db.execute(select(func.count(User.id)))).scalar_one()
    is_first = user_count == 0

    user = User(
        email=str(payload.email),
        username=payload.username,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_superadmin=is_first,
    )
    db.add(user)
    await db.flush()

    logger.info("user_registered", user_id=str(user.id), is_superadmin=is_first)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = (await db.execute(
        select(User).where(User.email == form.username)
    )).scalar_one_or_none()

    if user is None or not user.is_active or not user.hashed_password:
        logger.warning("login_failed", email=form.username[:50])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(form.password, user.hashed_password):
        logger.warning("login_failed_password", user_id=str(user.id))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))

    # Store refresh token in Redis (TTL = 7 days)
    redis = get_redis()
    await redis.setex(f"whatisup:refresh:{user.id}:{refresh[-12:]}", 7 * 86400, "1")

    logger.info("login_success", user_id=str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: TokenRefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        data = decode_token(payload.refresh_token, "refresh")
        user_id = uuid.UUID(data["sub"])
    except (InvalidTokenError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

    # Check not blacklisted
    redis = get_redis()
    key = f"whatisup:refresh:{user_id}:{payload.refresh_token[-12:]}"
    if not await redis.exists(key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Rotate refresh token
    await redis.delete(key)
    new_access = create_access_token(str(user.id))
    new_refresh = create_refresh_token(str(user.id))
    await redis.setex(f"whatisup:refresh:{user.id}:{new_refresh[-12:]}", 7 * 86400, "1")

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: TokenRefreshRequest) -> None:
    try:
        data = decode_token(payload.refresh_token, "refresh")
        user_id = data["sub"]
    except (InvalidTokenError, KeyError):
        return  # Already invalid, nothing to revoke

    redis = get_redis()
    key = f"whatisup:refresh:{user_id}:{payload.refresh_token[-12:]}"
    await redis.delete(key)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return current_user
