"""Authentication endpoints: register, login, refresh, logout, me, OIDC."""

import hashlib
import json
import os
import secrets as _secrets
import uuid
from base64 import urlsafe_b64encode
from urllib.parse import urlencode, urlparse

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.config import get_settings
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.redis import get_redis
from whatisup.core.security import (
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    decode_token,
    hash_password_async,
    verify_password_async,
)
from whatisup.models.user import User
from whatisup.schemas.user import (
    LoginResponse,
    TokenRefreshRequest,
    TokenResponse,
    UserOut,
    UserSelfUpdate,
)
from whatisup.services.lockout import (
    LOCKOUT_DURATION_SECONDS,
    LOCKOUT_THRESHOLD,
    is_locked,
    register_failure,
    reset_failures,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
@limiter.limit("10/minute")
async def register(request: Request) -> None:
    """Public registration is disabled on this instance (invite-only)."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Public registration is disabled. Ask an administrator for an invite.",
    )


async def store_refresh_session(
    user_id: uuid.UUID,
    refresh_token: str,
    request: Request | None,
    inherit_meta: dict | None = None,
) -> None:
    """Store the refresh token in Redis with session metadata (UA/IP/created).

    The key set IS the user's active session list — metadata makes it
    presentable in the "active sessions" UI. On token rotation, pass the
    previous session's metadata via ``inherit_meta`` so the continuing session
    keeps its original start date, user-agent and IP.
    """
    import json
    from datetime import UTC, datetime

    redis = get_redis()
    _rh = hashlib.sha256(refresh_token.encode()).hexdigest()[:32]
    if inherit_meta:
        meta = inherit_meta
    else:
        meta = {
            "created_at": datetime.now(UTC).isoformat(),
            "ua": (request.headers.get("user-agent", "") if request else "")[:200],
            "ip": (request.client.host if request and request.client else None),
        }
    settings = get_settings()
    await redis.setex(
        f"whatisup:refresh:{user_id}:{_rh}",
        settings.refresh_token_expire_days * 86400,
        json.dumps(meta),
    )


def _invalid_credentials() -> HTTPException:
    """The one and only failure response for /login — identical for unknown
    account, wrong password and active lockout (anti-enumeration)."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


_dummy_hash: str | None = None


async def _burn_password_check(password: str) -> None:
    """Verify against a throwaway bcrypt hash so the locked-out path takes the
    same time as a real wrong-password check (no timing oracle on the lockout)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password_async(os.urandom(16).hex())
    await verify_password_async(password, _dummy_hash)


async def _note_login_failure(
    identifier: str, user: User | None, request: Request, db: AsyncSession
) -> None:
    """Count one failed attempt; audit + persist when it triggers the lockout."""
    if not await register_failure(identifier):
        return
    from whatisup.services.audit import log_action

    await log_action(
        db,
        "user.login_lockout",
        "user",
        user.id if user else None,
        user.username if user else identifier.strip().lower()[:120],
        None,
        diff={"threshold": LOCKOUT_THRESHOLD, "lockout_seconds": LOCKOUT_DURATION_SECONDS},
        ip_address=request.client.host if request.client else None,
    )
    # The request ends with a 401 → get_db rolls back on exception; commit now
    # so the audit entry survives.
    await db.commit()
    logger.warning("login_lockout_triggered", user_id=str(user.id) if user else None)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    identifier = form.username

    # Per-account lockout (SA2) — checked first. Response and timing are
    # indistinguishable from a wrong password: never reveal the lockout.
    if await is_locked(identifier):
        await _burn_password_check(form.password)
        logger.warning("login_locked_out")
        raise _invalid_credentials()

    user = (await db.execute(select(User).where(User.email == form.username))).scalar_one_or_none()

    if user is None or not user.is_active or not user.hashed_password:
        # Burn a bcrypt verification so an unknown / inactive account takes the
        # same ~100ms as a wrong password on a real account — no timing oracle
        # to enumerate valid emails.
        await _burn_password_check(form.password)
        await _note_login_failure(identifier, None, request, db)
        logger.warning("login_failed")
        raise _invalid_credentials()

    if not await verify_password_async(form.password, user.hashed_password):
        await _note_login_failure(identifier, user, request, db)
        logger.warning("login_failed_password", user_id=str(user.id))
        raise _invalid_credentials()

    # Correct password — clear the failure counter (applies to the password
    # step only; the TOTP flow below has its own replay/attempt guards).
    await reset_failures(identifier)

    # 2FA: password alone is not enough — issue a short-lived MFA challenge
    if user.totp_enabled:
        logger.info("login_mfa_challenge", user_id=str(user.id))
        return LoginResponse(mfa_required=True, mfa_token=create_mfa_token(str(user.id)))

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    await store_refresh_session(user.id, refresh, request)

    logger.info("login_success", user_id=str(user.id))
    from whatisup.services.audit import log_action

    await log_action(db, "user.login", "user", user.id, user.username, None)
    if user.is_superadmin:
        # Le mot de passe du premier boot a servi : on retire le fichier au lieu
        # d'en conseiller la suppression (audit F15).
        from whatisup.init_data import consume_admin_password_file

        consume_admin_password_file()
    return LoginResponse(access_token=access, refresh_token=refresh)


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

    # Rotate refresh token — the continuing session keeps its original metadata
    import json as _json

    raw_meta = await redis.get(key)
    inherited = None
    try:
        if raw_meta and raw_meta not in ("1", b"1"):
            inherited = _json.loads(raw_meta)
    except (ValueError, TypeError):
        pass  # legacy value from pre-session-metadata tokens
    await redis.delete(key)
    new_access = create_access_token(str(user.id))
    new_refresh = create_refresh_token(str(user.id))
    await store_refresh_session(user.id, new_refresh, request, inherit_meta=inherited)

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def logout(request: Request, payload: TokenRefreshRequest) -> None:
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
@limiter.limit("60/minute")
async def me(request: Request, current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return current_user


@router.patch("/me", response_model=UserOut)
@limiter.limit("30/minute")
async def update_me(
    request: Request,
    payload: UserSelfUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Update the authenticated user's own profile preferences.

    Limited to non-privileged fields (full_name, timezone). Admin-level
    updates go through `/admin/users/{id}`.
    """
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(current_user, field, value)
    await db.flush()
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
@limiter.limit("30/minute")
async def oidc_config(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Return OIDC availability so the frontend can show/hide the SSO button."""
    cfg = await _resolve_oidc_settings(db)
    return {"enabled": cfg["enabled"]}


async def _oidc_discover(issuer: str) -> dict:
    """Fetch and return the OIDC discovery document."""
    import asyncio
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

    def _dns_check() -> None:
        try:
            for ai in _sock.getaddrinfo(hostname, None, proto=_sock.IPPROTO_TCP):
                ip = _ipa.ip_address(ai[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    raise ValueError("OIDC issuer URL resolves to internal IP")
        except _sock.gaierror:
            raise ValueError("OIDC issuer URL DNS resolution failed")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _dns_check)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def _email_is_verified(userinfo: dict) -> bool:
    """Whether the provider asserts the ``email`` claim was verified.

    OIDC core defines ``email_verified`` as a boolean, but providers in the wild
    also send the strings ``"true"`` / ``"1"``. A missing claim is treated as
    *not* verified: an IdP that never asserts verification cannot be used to
    bind an email address to an account (audit F16).
    """
    raw = userinfo.get("email_verified")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in ("true", "1", "yes")
    return raw == 1


# ── Liaison de la connexion OIDC au navigateur qui l'a initiée ───────────────
#
# Le callback renvoyait la paire de jetons dans le fragment d'URL. N'importe
# qui pouvait donc terminer sa propre connexion OIDC, récupérer le fragment, et
# envoyer à une victime un lien `/oidc-callback#access_token=…` : le navigateur
# de la victime enregistrait la session de l'attaquant (login CSRF / fixation
# de session), et tout ce que la victime saisissait ensuite atterrissait dans
# le compte de l'attaquant (audit F11).
#
# Deux changements, indissociables :
#   1. un nonce en cookie HttpOnly posé avant la redirection vers l'IdP, exigé
#      au retour — un flux qui n'a pas commencé dans ce navigateur est refusé ;
#   2. plus aucun jeton dans une URL : le callback ne renvoie qu'un code opaque
#      à usage unique, échangé par le front contre les jetons, échange lui-même
#      lié au même cookie.
#
# Le seul code ne suffirait pas : un attaquant peut fabriquer un lien portant
# *son* code frais. C'est le cookie qui ferme la porte, aux deux étapes.
_OIDC_NONCE_COOKIE = "wiu_oidc_nonce"
_OIDC_NONCE_PATH = "/api/v1/auth/oidc"
_OIDC_STATE_TTL = 300  # secondes — durée de vie d'une tentative de connexion
_OIDC_HANDOFF_TTL = 60  # secondes — le front échange le code immédiatement


def _hash_nonce(value: str) -> str:
    """Empreinte du nonce : Redis ne stocke jamais la valeur du cookie."""
    return hashlib.sha256(value.encode()).hexdigest()


def _nonce_matches(request: Request, expected_hash: str) -> bool:
    cookie = request.cookies.get(_OIDC_NONCE_COOKIE)
    if not cookie or not expected_hash:
        return False
    return _secrets.compare_digest(_hash_nonce(cookie), expected_hash)


def _nonce_cookie_samesite(request: Request) -> str:
    """`lax` dans le déploiement livré, `none` si le front est sur un autre hôte.

    nginx sert le front et proxifie `/api` : l'échange est alors same-origin et
    `lax` suffit (le retour de l'IdP est une navigation GET de premier niveau,
    que `lax` autorise). Si l'opérateur héberge le front sur un hôte distinct
    de l'API, l'échange devient une requête cross-site que `lax` bloquerait :
    le cookie ne partirait jamais et *toute* connexion SSO échouerait.
    `none` exige `Secure`, donc HTTPS — garanti en production, où les origines
    HTTP sont refusées au démarrage ; hors production on reste en `lax`, un
    cookie `SameSite=None` non sécurisé étant ignoré par les navigateurs.

    Ce n'est pas SameSite qui protège ici : le nonce est imprévisible et
    HttpOnly, et c'est sa valeur qui est vérifiée aux deux étapes.
    """
    settings = get_settings()
    if not settings.is_production:
        return "lax"
    origins = settings.cors_allowed_origins
    frontend_host = urlparse(origins[0]).hostname if origins else None
    return "none" if frontend_host and frontend_host != request.url.hostname else "lax"


@router.get("/oidc/login")
@limiter.limit("20/minute")
async def oidc_login(request: Request, db: AsyncSession = Depends(get_db)) -> RedirectResponse:
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

    # Generate state + PKCE code_verifier + nonce de liaison navigateur
    state = urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_verifier = urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    nonce = urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = (
        urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    )

    # Persist in Redis (5-minute TTL)
    redis = get_redis()
    await redis.setex(
        f"whatisup:oidc:state:{state}",
        _OIDC_STATE_TTL,
        json.dumps({"verifier": code_verifier, "nonce": _hash_nonce(nonce)}),
    )

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
    redirect = RedirectResponse(url=auth_url, status_code=302)
    redirect.set_cookie(
        _OIDC_NONCE_COOKIE,
        nonce,
        max_age=_OIDC_STATE_TTL,
        httponly=True,
        secure=get_settings().is_production,
        samesite=_nonce_cookie_samesite(request),
        path=_OIDC_NONCE_PATH,
    )
    return redirect


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
    # Determine frontend base URL — only from CORS config, never from request
    if not settings.cors_allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CORS_ALLOWED_ORIGINS must be configured for OIDC",
        )
    frontend_url = settings.cors_allowed_origins[0]

    def _fail(msg: str) -> RedirectResponse:
        from urllib.parse import urlencode

        return RedirectResponse(
            url=f"{frontend_url}/oidc-callback?{urlencode({'error': msg})}",
            status_code=302,
        )

    if error:
        return _fail("provider_error")
    if not code or not state:
        return _fail("missing_params")

    # Validate state and retrieve code_verifier
    redis = get_redis()
    redis_key = f"whatisup:oidc:state:{state}"
    raw_state = await redis.get(redis_key)
    if not raw_state:
        return _fail("invalid_state")
    await redis.delete(redis_key)
    if isinstance(raw_state, bytes):
        raw_state = raw_state.decode()

    try:
        state_data = json.loads(raw_state)
        code_verifier = state_data["verifier"]
        nonce_hash = state_data["nonce"]
    except (ValueError, TypeError, KeyError):
        # Format d'avant la liaison navigateur : une tentative de connexion
        # entamée juste avant la mise à jour. On refuse plutôt que d'accepter
        # sans nonce — l'utilisateur relance la connexion (fenêtre : 5 min).
        return _fail("invalid_state")

    # Ce flux a-t-il commencé dans *ce* navigateur ? (audit F11)
    if not _nonce_matches(request, nonce_hash):
        logger.warning("oidc_nonce_mismatch")
        return _fail("state_mismatch")

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
        # Audit F16: binding an identity by email address is only safe when the
        # provider asserts the address was verified. Without this check, an IdP
        # that allows unverified-email signups lets an attacker register
        # victim@corp.com there and take over the victim's local account (or
        # squat their address through auto-provisioning).
        if not _email_is_verified(userinfo):
            logger.warning("oidc_email_not_verified", sub=sub)
            return _fail("email_not_verified")

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

    # Code opaque à usage unique au lieu des jetons : rien de porteur ne
    # transite par une URL, et l'échange reste lié au même cookie (audit F11).
    # Les jetons sont émis à l'échange, donc les métadonnées de session (UA/IP)
    # décrivent le navigateur qui ouvre réellement la session.
    handoff = urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    await redis.setex(
        f"whatisup:oidc:handoff:{handoff}",
        _OIDC_HANDOFF_TTL,
        json.dumps({"user_id": str(user.id), "nonce": nonce_hash}),
    )

    logger.info("oidc_callback_ok", user_id=str(user.id))
    return RedirectResponse(
        url=f"{frontend_url}/oidc-callback#code={handoff}",
        status_code=302,
    )


class OidcExchangeIn(BaseModel):
    code: str = Field(min_length=16, max_length=128)


@router.post("/oidc/exchange", response_model=TokenResponse)
@limiter.limit("20/minute")
async def oidc_exchange(
    request: Request,
    payload: OidcExchangeIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Échange le code opaque du callback contre la paire de jetons.

    Refuse tout appel qui ne vient pas du navigateur ayant initié la connexion :
    c'est cette vérification qui rend inopérant un lien `/oidc-callback#code=…`
    fabriqué par un tiers (audit F11).
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login code"
    )

    redis = get_redis()
    key = f"whatisup:oidc:handoff:{payload.code}"
    raw = await redis.get(key)
    if not raw:
        raise invalid
    await redis.delete(key)  # usage unique, consommé même si la suite échoue

    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
        user_id = uuid.UUID(data["user_id"])
    except (ValueError, TypeError, KeyError):
        raise invalid

    if not _nonce_matches(request, data.get("nonce", "")):
        logger.warning("oidc_exchange_nonce_mismatch")
        raise invalid

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise invalid

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    # Same session bookkeeping as the classic login flow: UA/IP/created_at
    # metadata + TTL aligned on refresh_token_expire_days (was a bare "1"
    # with a hardcoded 7-day TTL, invisible in the active-sessions UI).
    await store_refresh_session(user.id, refresh, request)

    from whatisup.services.audit import log_action

    await log_action(db, "user.login_oidc", "user", user.id, user.username, None)
    logger.info("oidc_login_success", user_id=str(user.id))

    # Le nonce a servi : il ne doit pas pouvoir couvrir un second échange.
    # Mêmes attributs qu'à la pose, sinon le navigateur garde le cookie posé
    # en Secure/SameSite=None et ne voit pas la suppression.
    response.delete_cookie(
        _OIDC_NONCE_COOKIE,
        path=_OIDC_NONCE_PATH,
        httponly=True,
        secure=get_settings().is_production,
        samesite=_nonce_cookie_samesite(request),
    )
    return TokenResponse(access_token=access, refresh_token=refresh)
