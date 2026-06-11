"""2FA TOTP endpoints — enrollment, login challenge verification, disable.

Flow:
  1. POST /auth/totp/setup    (auth)  → pending secret + otpauth:// URI (QR)
  2. POST /auth/totp/enable   (auth)  → first valid code activates 2FA,
                                         returns single-use recovery codes once
  3. login with password      → {mfa_required, mfa_token} instead of tokens
  4. POST /auth/totp/verify           → mfa_token + TOTP/recovery code → tokens
  5. POST /auth/totp/disable  (auth)  → password + code removes 2FA

The TOTP secret is stored Fernet-encrypted; recovery codes are stored as
bcrypt hashes and consumed on use. A 90 s Redis guard rejects code replay.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid

import pyotp
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.redis import get_redis
from whatisup.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_secret_str,
    encrypt_secret_str,
    hash_password,
    verify_password_async,
)
from whatisup.models.user import User
from whatisup.schemas.user import TokenResponse

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth/totp", tags=["auth"])

_RECOVERY_CODE_COUNT = 8
_REPLAY_GUARD_TTL = 90  # seconds — one TOTP step + drift window


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_url: str


class TotpCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class TotpEnableOut(BaseModel):
    enabled: bool
    recovery_codes: list[str]


class TotpDisableIn(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=16)


class TotpVerifyIn(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=16)


def _normalize(code: str) -> str:
    return code.strip().replace(" ", "").replace("-", "").upper()


async def _verify_totp_code(user: User, code: str) -> bool:
    """Validate a 6-digit TOTP code with a Redis replay guard."""
    if not user.totp_secret:
        return False
    secret = decrypt_secret_str(user.totp_secret)
    code = _normalize(code)
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        return False
    # Replay guard: a code is single-use within its validity window
    redis = get_redis()
    guard_key = f"whatisup:totp_used:{user.id}:{code}"
    if not await redis.set(guard_key, "1", ex=_REPLAY_GUARD_TTL, nx=True):
        logger.warning("totp_code_replayed", user_id=str(user.id))
        return False
    return True


async def _consume_recovery_code(user: User, code: str) -> bool:
    """Match a recovery code against the stored bcrypt hashes; consume on hit."""
    import bcrypt

    if not user.totp_recovery_codes:
        return False
    candidate = _normalize(code)

    def _match() -> int | None:
        for idx, hashed in enumerate(user.totp_recovery_codes):
            if bcrypt.checkpw(candidate.encode(), hashed.encode()):
                return idx
        return None

    idx = await asyncio.to_thread(_match)
    if idx is None:
        return False
    remaining = list(user.totp_recovery_codes)
    remaining.pop(idx)
    user.totp_recovery_codes = remaining
    logger.info("totp_recovery_code_used", user_id=str(user.id), remaining=len(remaining))
    return True


@router.post("/setup", response_model=TotpSetupOut)
@limiter.limit("10/minute")
async def setup_totp(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TotpSetupOut:
    """Generate a pending TOTP secret (2FA activates only after /enable)."""
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled — disable it first to re-enroll",
        )
    secret = pyotp.random_base32()
    current_user.totp_secret = encrypt_secret_str(secret)
    await db.flush()
    otpauth = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email, issuer_name="WhatIsUp"
    )
    return TotpSetupOut(secret=secret, otpauth_url=otpauth)


@router.post("/enable", response_model=TotpEnableOut)
@limiter.limit("10/minute")
async def enable_totp(
    request: Request,
    payload: TotpCodeIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TotpEnableOut:
    """Activate 2FA after the first valid code; returns recovery codes ONCE."""
    if current_user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already enabled")
    if not current_user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Call /auth/totp/setup first"
        )
    if not await _verify_totp_code(current_user, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

    plain_codes = [
        f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        for _ in range(_RECOVERY_CODE_COUNT)
    ]
    hashes = await asyncio.to_thread(lambda: [hash_password(_normalize(c)) for c in plain_codes])
    current_user.totp_enabled = True
    current_user.totp_recovery_codes = hashes
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(db, "user.totp_enabled", "user", current_user.id, current_user.username, None)
    logger.info("totp_enabled", user_id=str(current_user.id))
    return TotpEnableOut(enabled=True, recovery_codes=plain_codes)


@router.post("/verify", response_model=TokenResponse)
@limiter.limit("10/minute")
async def verify_totp(
    request: Request,
    payload: TotpVerifyIn,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a login MFA challenge + TOTP/recovery code for the token pair."""
    try:
        data = decode_token(payload.mfa_token, "mfa")
        user_id = uuid.UUID(data["sub"])
    except (InvalidTokenError, ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired MFA token"
        )

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active or not user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA state")

    ok = await _verify_totp_code(user, payload.code)
    if not ok and len(_normalize(payload.code)) >= 8:
        ok = await _consume_recovery_code(user, payload.code)
        if ok:
            await db.flush()
    if not ok:
        logger.warning("totp_verify_failed", user_id=str(user.id))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")

    from whatisup.api.v1.auth import store_refresh_session

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    await store_refresh_session(user.id, refresh, request)

    from whatisup.services.audit import log_action

    await log_action(db, "user.login", "user", user.id, user.username, None)
    logger.info("login_success_mfa", user_id=str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def disable_totp(
    request: Request,
    payload: TotpDisableIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove 2FA — requires the account password AND a valid TOTP/recovery code."""
    if not current_user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")
    if not current_user.hashed_password or not await verify_password_async(
        payload.password, current_user.hashed_password
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    ok = await _verify_totp_code(current_user, payload.code)
    if not ok and len(_normalize(payload.code)) >= 8:
        ok = await _consume_recovery_code(current_user, payload.code)
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")

    current_user.totp_secret = None
    current_user.totp_enabled = False
    current_user.totp_recovery_codes = None
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(db, "user.totp_disabled", "user", current_user.id, current_user.username, None)
    logger.info("totp_disabled", user_id=str(current_user.id))
