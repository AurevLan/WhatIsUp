"""Firebase Cloud Messaging dispatcher.

Sends notifications to Capacitor mobile devices via the FCM HTTP v1 API. The
service account JSON ships either as ``FCM_SERVICE_ACCOUNT_JSON`` (raw JSON
string in env, used in CI/prod) or as a path in ``FCM_SERVICE_ACCOUNT_PATH``
(used locally inside docker compose).

Payload encryption
──────────────────
Each device row in the DB carries its own Fernet key. Before pushing, we wrap
``{title, body, monitor_id, severity}`` with that key, base64-encode the
ciphertext and ship it as the only field in the FCM data payload. Google's
FCM relay therefore only sees opaque bytes — the title shown to the user is
constructed by the app *after* unwrapping. The notification body itself
(``message.notification.{title,body}``) is intentionally **not** populated so
nothing readable transits the FCM relay.

OAuth2 access tokens are cached in Redis (TTL = expires_in - 60s) so we sign
a fresh JWT at most twice per hour, regardless of how many alerts fire.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import jwt
import structlog
from cryptography.fernet import Fernet

from whatisup.core.redis import get_redis

logger = structlog.get_logger()

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_SEND_URL_TEMPLATE = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
ACCESS_TOKEN_CACHE_KEY = "whatisup:fcm:access_token"


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    project_id: str
    client_email: str
    private_key: str
    token_uri: str = GOOGLE_TOKEN_URI


def load_service_account() -> ServiceAccount | None:
    """Read the FCM service account from the configured location.

    Returns ``None`` when nothing is configured so the rest of the alert
    pipeline can detect that FCM is disabled and skip cleanly without raising.
    """
    raw = os.environ.get("FCM_SERVICE_ACCOUNT_JSON")
    if not raw:
        path = os.environ.get("FCM_SERVICE_ACCOUNT_PATH")
        if path and Path(path).is_file():
            raw = Path(path).read_text(encoding="utf-8")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return ServiceAccount(
            project_id=data["project_id"],
            client_email=data["client_email"],
            private_key=data["private_key"],
            token_uri=data.get("token_uri", GOOGLE_TOKEN_URI),
        )
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("fcm_service_account_invalid", error=str(exc))
        return None


def is_enabled() -> bool:
    return load_service_account() is not None


async def _get_access_token(sa: ServiceAccount) -> str:
    """Return a cached OAuth2 bearer token, signing a new JWT if needed."""
    redis = get_redis()
    cached = await redis.get(ACCESS_TOKEN_CACHE_KEY)
    if cached:
        return cached.decode() if isinstance(cached, bytes) else cached

    now = int(time.time())
    claims = {
        "iss": sa.client_email,
        "scope": FCM_SCOPE,
        "aud": sa.token_uri,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jwt.encode(claims, sa.private_key, algorithm="RS256")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            sa.token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        resp.raise_for_status()
        body = resp.json()

    token = body["access_token"]
    expires_in = int(body.get("expires_in", 3600))
    await redis.setex(ACCESS_TOKEN_CACHE_KEY, max(60, expires_in - 60), token)
    return token


def _encrypt_payload(payload: dict[str, Any], encryption_key: str) -> str:
    """Wrap a notification payload with the device's Fernet key.

    Returns the base64 ciphertext (URL-safe — Fernet output is already URL-safe
    base64 so no extra encoding is needed)."""
    fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
    plaintext = json.dumps(payload, separators=(",", ":")).encode()
    return fernet.encrypt(plaintext).decode()


async def send_to_devices(
    devices: list[tuple[str, str]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Push the same payload to a list of (token, encryption_key) tuples.

    Returns a dict ``{"sent": int, "failed": int, "invalid_tokens": [...]}``
    where ``invalid_tokens`` lists FCM tokens the API rejected with
    ``UNREGISTERED`` / ``INVALID_ARGUMENT`` so the caller can prune them.
    """
    sa = load_service_account()
    if sa is None or not devices:
        return {"sent": 0, "failed": 0, "invalid_tokens": []}

    access_token = await _get_access_token(sa)
    url = FCM_SEND_URL_TEMPLATE.format(project_id=sa.project_id)

    sent = 0
    failed = 0
    invalid: list[str] = []

    async with httpx.AsyncClient(timeout=10) as client:
        for token, enc_key in devices:
            try:
                ciphertext = _encrypt_payload(payload, enc_key)
                body = {
                    "message": {
                        "token": token,
                        "data": {"c": ciphertext},
                        "android": {
                            "priority": "HIGH",
                            "ttl": "3600s",
                        },
                    }
                }
                resp = await client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                )
                if resp.status_code == 200:
                    sent += 1
                    continue
                failed += 1
                error_status = ""
                try:
                    error_status = resp.json().get("error", {}).get("status", "")
                except Exception:
                    pass
                if error_status in ("UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND"):
                    invalid.append(token)
                logger.warning(
                    "fcm_send_failed",
                    status=resp.status_code,
                    error_status=error_status,
                    token_prefix=token[:12],
                )
            except Exception as exc:
                failed += 1
                logger.error("fcm_dispatch_exception", error=str(exc), token_prefix=token[:12])

    return {"sent": sent, "failed": failed, "invalid_tokens": invalid}


def encode_token_for_log(token: str) -> str:
    """Helper for tests / logs — base64 the token so it doesn't leak verbatim."""
    return base64.urlsafe_b64encode(token.encode()).decode()[:16]
