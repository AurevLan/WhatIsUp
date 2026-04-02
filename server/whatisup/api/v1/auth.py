"""Authentication endpoints: register, login, refresh, logout, me, OIDC."""

import hashlib
import os
import uuid
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user, require_superadmin
from whatisup.core.config import get_settings
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.redis import get_redis
from whatisup.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password_async,
    verify_password_async,
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
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Registration is disabled. Contact your administrator.",
    )


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Create a user account (superadmin only — for invite-only deployments)."""
    existing = (
        await db.execute(
            select(User).where((User.email == payload.email) | (User.username == payload.username))
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        )

    user = User(
        email=str(payload.email),
        username=payload.username,
        full_name=payload.full_name,
        hashed_password=await hash_password_async(payload.password),
        is_superadmin=False,  # Admin explicitly sets superadmin if needed
    )
    db.add(user)
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(db, "user.create", "user", user.id, user.username, None)

    logger.info("user_created_by_admin", user_id=str(user.id), admin_id=str(_admin.id))
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = (await db.execute(select(User).where(User.email == form.username))).scalar_one_or_none()

    if user is None or not user.is_active or not user.hashed_password:
        logger.warning("login_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not await verify_password_async(form.password, user.hashed_password):
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
    _rh = hashlib.sha256(refresh.encode()).hexdigest()[:32]
    await redis.setex(f"whatisup:refresh:{user.id}:{_rh}", 7 * 86400, "1")

    logger.info("login_success", user_id=str(user.id))
    from whatisup.services.audit import log_action

    await log_action(db, "user.login", "user", user.id, user.username, None)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    payload: TokenRefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        data = decode_token(payload.refresh_token, "refresh")
        user_id = uuid.UUID(data["sub"])
    except (InvalidTokenError, ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    # Check not blacklisted
    redis = get_redis()
    _rh = hashlib.sha256(payload.refresh_token.encode()).hexdigest()[:32]
    key = f"whatisup:refresh:{user_id}:{_rh}"
    if not await redis.exists(key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked"
        )

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Rotate refresh token
    await redis.delete(key)
    new_access = create_access_token(str(user.id))
    new_refresh = create_refresh_token(str(user.id))
    _nrh = hashlib.sha256(new_refresh.encode()).hexdigest()[:32]
    await redis.setex(f"whatisup:refresh:{user.id}:{_nrh}", 7 * 86400, "1")

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: TokenRefreshRequest) -> None:
    try:
        data = decode_token(payload.refresh_token, "refresh")
        user_id = data["sub"]
    except (InvalidTokenError, KeyError):
        return  # Already invalid, nothing to revoke

    redis = get_redis()
    _rh = hashlib.sha256(payload.refresh_token.encode()).hexdigest()[:32]
    key = f"whatisup:refresh:{user_id}:{_rh}"
    await redis.delete(key)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return current_user


# ── OIDC ─────────────────────────────────────────────────────────────────────


async def _resolve_oidc_settings(db: AsyncSession) -> dict:
    """Return effective OIDC settings: DB row overrides env vars."""
    from whatisup.core.security import _get_fernet
    from whatisup.models.system_settings import SystemSettings

    row = (
        await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    ).scalar_one_or_none()
    settings = get_settings()

    if row is not None:
        client_secret = ""
        if row.oidc_client_secret:
            fernet = _get_fernet()
            if fernet:
                try:
                    client_secret = fernet.decrypt(row.oidc_client_secret.encode()).decode()
                except Exception:
                    client_secret = row.oidc_client_secret
            else:
                client_secret = row.oidc_client_secret

        return {
            "enabled": row.oidc_enabled,
            "issuer_url": row.oidc_issuer_url or settings.oidc_issuer_url,
            "client_id": row.oidc_client_id or settings.oidc_client_id,
            "client_secret": client_secret or settings.oidc_client_secret,
            "redirect_uri": row.oidc_redirect_uri or settings.oidc_redirect_uri,
            "scopes": row.oidc_scopes or settings.oidc_scopes,
            "auto_provision": row.oidc_auto_provision,
        }

    return {
        "enabled": settings.oidc_enabled,
        "issuer_url": settings.oidc_issuer_url,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
        "redirect_uri": settings.oidc_redirect_uri,
        "scopes": settings.oidc_scopes,
        "auto_provision": settings.oidc_auto_provision,
    }


@router.get("/oidc/config")
async def oidc_config(db: AsyncSession = Depends(get_db)) -> dict:
    """Return OIDC availability so the frontend can show/hide the SSO button."""
    cfg = await _resolve_oidc_settings(db)
    return {"enabled": cfg["enabled"]}


async def _oidc_discover(issuer: str) -> dict:
    """Fetch and return the OIDC discovery document."""
    import ipaddress as _ipa
    import socket as _sock
    from urllib.parse import urlparse as _urlparse

    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    parsed = _urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("OIDC issuer URL must use http or https")
    hostname = parsed.hostname or ""
    if hostname.lower() in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError("OIDC issuer URL points to blocked host")
    try:
        for ai in _sock.getaddrinfo(hostname, None, proto=_sock.IPPROTO_TCP):
            ip = _ipa.ip_address(ai[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError("OIDC issuer URL resolves to internal IP")
    except _sock.gaierror:
        raise ValueError("OIDC issuer URL DNS resolution failed")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


@router.get("/oidc/login")
@limiter.limit("20/minute")
async def oidc_login(
    request: Request, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    """Redirect the browser to the OIDC provider's authorization endpoint."""
    cfg = await _resolve_oidc_settings(db)
    if not cfg["enabled"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OIDC not enabled")

    try:
        discovery = await _oidc_discover(cfg["issuer_url"])
    except Exception as exc:
        logger.error("oidc_discovery_failed", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC provider unreachable",
        )

    # Generate state + PKCE code_verifier
    state = urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_verifier = urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    # Persist in Redis (10-minute TTL)
    redis = get_redis()
    await redis.setex(f"whatisup:oidc:state:{state}", 300, code_verifier)

    base = str(request.base_url).rstrip("/")
    redirect_uri = cfg["redirect_uri"] or f"{base}/api/v1/auth/oidc/callback"

    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": cfg["scopes"],
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = discovery["authorization_endpoint"] + "?" + urlencode(params)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/oidc/callback")
@limiter.limit("20/minute")
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle the provider redirect, issue JWT, redirect to frontend."""
    cfg = await _resolve_oidc_settings(db)
    if not cfg["enabled"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OIDC not enabled")

    settings = get_settings()
    # Determine frontend base URL from CORS origins or request
    frontend_url = (
        settings.cors_allowed_origins[0]
        if settings.cors_allowed_origins
        else str(request.base_url).rstrip("/")
    )

    def _fail(msg: str) -> RedirectResponse:
        from urllib.parse import urlencode

        return RedirectResponse(
            url=f"{frontend_url}/oidc-callback?{urlencode({'error': msg})}",
            status_code=302,
        )

    if error:
        return _fail(error)
    if not code or not state:
        return _fail("missing_params")

    # Validate state and retrieve code_verifier
    redis = get_redis()
    redis_key = f"whatisup:oidc:state:{state}"
    code_verifier = await redis.get(redis_key)
    if not code_verifier:
        return _fail("invalid_state")
    await redis.delete(redis_key)
    if isinstance(code_verifier, bytes):
        code_verifier = code_verifier.decode()

    try:
        discovery = await _oidc_discover(cfg["issuer_url"])
    except Exception:
        return _fail("provider_unreachable")

    base = str(request.base_url).rstrip("/")
    redirect_uri = cfg["redirect_uri"] or f"{base}/api/v1/auth/oidc/callback"

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                discovery["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()
    except Exception as exc:
        logger.error("oidc_token_exchange_failed", error_type=type(exc).__name__)
        return _fail("token_exchange_failed")

    # Fetch userinfo
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            ui_resp = await client.get(
                discovery["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            ui_resp.raise_for_status()
            userinfo = ui_resp.json()
    except Exception as exc:
        logger.error("oidc_userinfo_failed", error_type=type(exc).__name__)
        return _fail("userinfo_failed")

    sub = userinfo.get("sub")
    email = userinfo.get("email", "")
    if not sub or not email:
        return _fail("missing_claims")

    # Find or create user
    user = (await db.execute(select(User).where(User.oidc_sub == sub))).scalar_one_or_none()

    if user is None:
        # Try to find by email (link existing account)
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user:
            user.oidc_sub = sub
        elif cfg["auto_provision"]:
            # Auto-provision new account
            preferred = userinfo.get("preferred_username") or email.split("@")[0]
            # Ensure unique username
            base = preferred[:95]
            candidate = base
            suffix = 1
            while (
                await db.execute(select(User).where(User.username == candidate))
            ).scalar_one_or_none():
                candidate = f"{base}_{suffix}"
                suffix += 1
            user = User(
                email=email,
                username=candidate,
                full_name=userinfo.get("name"),
                oidc_sub=sub,
                can_create_monitors=False,
            )
            db.add(user)
            await db.flush()
            logger.info("oidc_user_provisioned", user_id=str(user.id), email=email)
        else:
            return _fail("account_not_found")

    if not user.is_active:
        return _fail("account_disabled")

    await db.flush()

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    _rh = hashlib.sha256(refresh.encode()).hexdigest()[:32]
    await redis.setex(f"whatisup:refresh:{user.id}:{_rh}", 7 * 86400, "1")

    logger.info("oidc_login_success", user_id=str(user.id))
    from whatisup.services.audit import log_action
    await log_action(db, "user.login_oidc", "user", user.id, user.username, None)
    await db.commit()

    # Use URL fragment (#) to avoid token leakage in server logs and Referer headers
    return RedirectResponse(
        url=f"{frontend_url}/oidc-callback#access_token={access}&refresh_token={refresh}",
        status_code=302,
    )
