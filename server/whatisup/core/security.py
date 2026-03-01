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
