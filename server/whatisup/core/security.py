"""Authentication utilities: JWT, bcrypt, probe API keys."""

from __future__ import annotations

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
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


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

def generate_probe_api_key() -> str:
    """Generate a cryptographically secure probe API key (displayed once)."""
    return f"wiu_{secrets.token_urlsafe(32)}"


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
    """Return a Fernet instance using FERNET_KEY from settings, or None if not configured."""
    from cryptography.fernet import Fernet
    settings = get_settings()
    if not settings.fernet_key:
        return None
    return Fernet(settings.fernet_key.encode() if isinstance(settings.fernet_key, str) else settings.fernet_key)


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
        k: fernet.encrypt(v.encode()).decode() if k in _SECRET_FIELDS and isinstance(v, str) and v else v
        for k, v in config.items()
    }


def decrypt_channel_config(config: dict) -> dict:
    """Decrypt sensitive fields in an alert channel config dict.

    Returns the config unchanged if FERNET_KEY is not configured.
    Silently skips fields that cannot be decrypted (e.g. plaintext legacy values).
    """
    from cryptography.fernet import InvalidToken
    fernet = _get_fernet()
    if fernet is None:
        return config
    result = {}
    for k, v in config.items():
        if k in _SECRET_FIELDS and isinstance(v, str) and v:
            try:
                result[k] = fernet.decrypt(v.encode()).decode()
            except (InvalidToken, Exception):
                result[k] = v  # fallback: return as-is (legacy plaintext)
        else:
            result[k] = v
    return result
