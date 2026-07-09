"""Authentication utilities: JWT, bcrypt, probe API keys."""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from whatisup.core.config import get_settings

# ---------------------------------------------------------------------------
# Password hashing (users)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password, plain, hashed)


# ---------------------------------------------------------------------------
# JWT tokens (users)
# ---------------------------------------------------------------------------


def create_access_token(subject: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iss": "whatisup",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iss": "whatisup",
        "iat": now,
        "exp": now + timedelta(days=settings.refresh_token_expire_days),
        "type": "refresh",
        # Unique per issue — two logins in the same second must yield distinct
        # tokens (and thus distinct Redis session keys).
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_mfa_token(subject: str) -> str:
    """Short-lived challenge token issued after password check when TOTP is on.

    Exchanged (with a valid TOTP/recovery code) for the real token pair.
    Deliberately NOT an access token: it grants nothing but /auth/totp/verify.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iss": "whatisup",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "type": "mfa",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def encrypt_secret_str(value: str) -> str:
    """Fernet-encrypt a standalone secret string (e.g. TOTP secret).

    Returns the value unchanged if FERNET_KEY is not configured (dev only —
    production refuses to start without a Fernet key).
    """
    fernet = _get_fernet()
    if fernet is None:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_secret_str(value: str) -> str:
    """Decrypt a string encrypted with :func:`encrypt_secret_str`.

    Falls back to the raw value for legacy plaintext entries.
    """
    from cryptography.fernet import InvalidToken

    fernet = _get_fernet()
    if fernet is None:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return value


def decode_token(token: str, token_type: str = "access") -> dict:
    """
    Decode and validate a JWT token.
    Raises jwt.InvalidTokenError on failure.
    """
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        issuer="whatisup",
        options={"require": ["sub", "exp", "iss", "type"]},
    )
    if payload.get("type") != token_type:
        raise InvalidTokenError(f"Expected token type '{token_type}'")
    return payload


# ---------------------------------------------------------------------------
# Probe API keys
# ---------------------------------------------------------------------------


# Probe API key scheme.
#
# New format: ``wiu_<prefix>.<secret>`` where ``<prefix>`` is a NON-SECRET
# identifier stored in clear (indexed column ``probes.api_key_prefix``) so the
# auth path can look up the single candidate probe and run exactly ONE bcrypt
# verification — instead of scanning the whole fleet (O(n) bcrypt).
#
# The ``.`` separator is unambiguous: ``secrets.token_urlsafe`` only emits chars
# from ``[A-Za-z0-9_-]`` and never a dot, so a legacy key (``wiu_<secret>``) can
# never contain one. Detecting a ``.`` therefore reliably distinguishes a
# new-scheme key from a pre-migration legacy key.
#
# Security: possession of ``<prefix>`` alone grants nothing — the bcrypt hash
# covers the WHOLE key (prefix + secret), and the secret keeps ~256 bits of
# entropy. The prefix only narrows the candidate lookup.
_PROBE_KEY_SCHEME = "wiu_"
_PROBE_KEY_SEP = "."


def generate_probe_api_key() -> tuple[str, str]:
    """Generate a probe API key (displayed once) and its public prefix.

    Returns ``(full_key, prefix)``:

    - ``full_key`` = ``wiu_<prefix>.<secret>`` — handed to the probe once.
    - ``prefix`` = the non-secret lookup identifier to persist in
      ``probes.api_key_prefix`` (indexed) so auth avoids the O(n) bcrypt scan.
    """
    prefix = secrets.token_urlsafe(8)
    secret = secrets.token_urlsafe(32)
    return f"{_PROBE_KEY_SCHEME}{prefix}{_PROBE_KEY_SEP}{secret}", prefix


def extract_probe_key_prefix(api_key: str) -> str | None:
    """Return the public prefix embedded in a presented probe key.

    Returns ``None`` for a **legacy** key (``wiu_<secret>`` with no ``.``
    separator) — those have no derivable prefix and must fall back to the
    bcrypt scan until the probe rotates to the new format.
    """
    if not api_key.startswith(_PROBE_KEY_SCHEME):
        return None
    rest = api_key[len(_PROBE_KEY_SCHEME) :]
    prefix, sep, _secret = rest.partition(_PROBE_KEY_SEP)
    if not sep or not prefix:
        return None
    return prefix


def generate_user_api_key() -> str:
    """Generate a cryptographically secure user API key (displayed once).

    Format: ``wiu_u_<43 URL-safe base64 chars>``
    Prefix ``wiu_u_`` distinguishes user keys from probe keys (``wiu_``).
    """
    return f"wiu_u_{secrets.token_urlsafe(32)}"


def generate_heartbeat_token() -> str:
    """Generate the globally unique secret used in ``/api/v1/ping/{token}`` URLs.

    The ``heartbeat_slug`` field is user-friendly and only unique per owner; the
    token is what actually routes the public ping endpoint and must not be
    guessable across tenants.
    """
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """Hash a probe API key for storage."""
    return bcrypt.hashpw(api_key.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_api_key(api_key: str, hashed: str) -> bool:
    """Verify a probe API key against its stored hash."""
    return bcrypt.checkpw(api_key.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------


def refresh_token_redis_key(jti_or_subject: str) -> str:
    return f"whatisup:refresh:{jti_or_subject}"


# ---------------------------------------------------------------------------
# Alert channel config encryption (Fernet symmetric)
# ---------------------------------------------------------------------------


def _get_fernet():
    """Return the Fernet engine from settings, or None if not configured.

    When FERNET_KEY_PREVIOUS is set (key rotation in progress), returns a
    MultiFernet: encryption always uses the primary FERNET_KEY (listed first),
    while decryption transparently falls back to the previous key(s). Once the
    rotation tool (``python -m whatisup.tools.rotate_fernet``) has re-encrypted
    everything, FERNET_KEY_PREVIOUS can be removed and this degrades to a plain
    single-key Fernet.
    """
    from cryptography.fernet import Fernet, MultiFernet

    settings = get_settings()
    if not settings.fernet_key:
        return None
    primary = Fernet(
        settings.fernet_key.encode()
        if isinstance(settings.fernet_key, str)
        else settings.fernet_key
    )
    previous = [Fernet(key.encode()) for key in settings.fernet_previous_keys]
    if previous:
        return MultiFernet([primary, *previous])
    return primary


# Fields in alert channel config that contain secrets and must be encrypted
_SECRET_FIELDS = {"secret", "bot_token", "password", "integration_key", "api_key"}


def encrypt_channel_config(config: dict) -> dict:
    """Encrypt sensitive fields in an alert channel config dict.

    Only fields listed in _SECRET_FIELDS are encrypted.
    Returns the config unchanged if FERNET_KEY is not configured.
    """
    fernet = _get_fernet()
    if fernet is None:
        return config
    return {
        k: fernet.encrypt(v.encode()).decode()
        if k in _SECRET_FIELDS and isinstance(v, str) and v
        else v
        for k, v in config.items()
    }


def decrypt_channel_config(config: dict) -> dict:
    """Decrypt sensitive fields in an alert channel config dict.

    Returns the config unchanged if FERNET_KEY is not configured.
    Logs a warning for fields that cannot be decrypted (e.g. plaintext legacy values).
    """
    import structlog
    from cryptography.fernet import InvalidToken

    fernet = _get_fernet()
    if fernet is None:
        return config
    _logger = structlog.get_logger(__name__)
    result = {}
    for k, v in config.items():
        if k in _SECRET_FIELDS and isinstance(v, str) and v:
            try:
                result[k] = fernet.decrypt(v.encode()).decode()
            except InvalidToken:
                _logger.warning("decrypt_channel_field_failed", field=k)
                result[k] = v  # fallback: return as-is (legacy plaintext)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Scenario variable encryption (Fernet symmetric)
# ---------------------------------------------------------------------------


def encrypt_scenario_variables(variables: list[dict]) -> list[dict]:
    """Encrypt the ``value`` of variables marked ``secret: true``.

    Non-secret variables and variables with non-string or empty values are
    left unchanged. Returns the list unchanged if FERNET_KEY is not configured.
    """
    fernet = _get_fernet()
    if fernet is None:
        return variables
    return [
        {**v, "value": fernet.encrypt(v["value"].encode()).decode()}
        if v.get("secret") and isinstance(v.get("value"), str) and v["value"]
        else v
        for v in variables
    ]


def decrypt_scenario_variables(variables: list[dict]) -> list[dict]:
    """Decrypt the ``value`` of variables marked ``secret: true``.

    Silently falls back to the raw value for entries that cannot be decrypted
    (e.g. legacy plaintext stored before encryption was enabled).
    Returns the list unchanged if FERNET_KEY is not configured.
    """
    from cryptography.fernet import InvalidToken

    fernet = _get_fernet()
    if fernet is None:
        return variables
    result = []
    for v in variables:
        if v.get("secret") and isinstance(v.get("value"), str) and v["value"]:
            try:
                result.append({**v, "value": fernet.decrypt(v["value"].encode()).decode()})
            except InvalidToken:
                result.append(v)  # fallback: return as-is
        else:
            result.append(v)
    return result
