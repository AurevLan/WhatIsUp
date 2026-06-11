"""Active sessions management — list and revoke refresh tokens.

A "session" is a live refresh token in Redis (``whatisup:refresh:{uid}:{hash}``)
whose value carries metadata (created_at, user-agent, IP) written at login and
carried over on rotation. Revoking deletes the key: the access token expires
within minutes and the refresh fails immediately after.
"""

from __future__ import annotations

import hashlib
import json
import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from whatisup.api.deps import get_current_user
from whatisup.core.limiter import limiter
from whatisup.core.redis import get_redis
from whatisup.models.user import User

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth/sessions", tags=["auth"])

_SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class SessionOut(BaseModel):
    id: str  # sha256 prefix of the refresh token — safe to expose
    created_at: str | None = None
    ua: str | None = None
    ip: str | None = None
    current: bool = False


class SessionListIn(BaseModel):
    # The client's own refresh token, used only to flag "this device".
    refresh_token: str | None = None


def _key_prefix(user: User) -> str:
    return f"whatisup:refresh:{user.id}:"


@router.post("/list", response_model=list[SessionOut])
@limiter.limit("30/minute")
async def list_sessions(
    request: Request,
    payload: SessionListIn,
    current_user: User = Depends(get_current_user),
) -> list[SessionOut]:
    redis = get_redis()
    current_hash = None
    if payload.refresh_token:
        current_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()[:32]

    sessions: list[SessionOut] = []
    prefix = _key_prefix(current_user)
    async for key in redis.scan_iter(match=prefix + "*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        session_id = key_str.removeprefix(prefix)
        raw = await redis.get(key_str)
        meta: dict = {}
        if raw and raw not in ("1", b"1"):
            try:
                meta = json.loads(raw)
            except ValueError:
                pass  # legacy value — show the session without metadata
        sessions.append(
            SessionOut(
                id=session_id,
                created_at=meta.get("created_at"),
                ua=meta.get("ua") or None,
                ip=meta.get("ip"),
                current=session_id == current_hash,
            )
        )
    sessions.sort(key=lambda s: (not s.current, s.created_at or ""), reverse=False)
    return sessions


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def revoke_session(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session id")
    redis = get_redis()
    deleted = await redis.delete(_key_prefix(current_user) + session_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    logger.info("session_revoked", user_id=str(current_user.id), session=session_id[:8])


@router.post("/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def revoke_all_sessions(
    request: Request,
    payload: SessionListIn,
    current_user: User = Depends(get_current_user),
) -> None:
    """Revoke every session; if the caller passes its refresh token, keep that one."""
    redis = get_redis()
    keep_hash = None
    if payload.refresh_token:
        keep_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()[:32]

    prefix = _key_prefix(current_user)
    revoked = 0
    async for key in redis.scan_iter(match=prefix + "*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        if keep_hash and key_str.removeprefix(prefix) == keep_hash:
            continue
        await redis.delete(key_str)
        revoked += 1
    logger.info("sessions_revoked_all", user_id=str(current_user.id), count=revoked)
