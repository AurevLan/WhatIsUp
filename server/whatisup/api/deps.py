"""FastAPI dependencies: current user, superadmin check, probe auth."""

import uuid

import structlog
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import get_db
from whatisup.core.security import decode_token, verify_api_key
from whatisup.models.probe import Probe
from whatisup.models.user import User

logger = structlog.get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = decode_token(token, "access")
        user_id = uuid.UUID(payload["sub"])
    except (InvalidTokenError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")
    return current_user


async def get_current_probe(
    x_probe_api_key: str = Header(..., alias="X-Probe-Api-Key"),
    db: AsyncSession = Depends(get_db),
) -> Probe:
    """Authenticate a probe via its API key."""
    if not x_probe_api_key.startswith("wiu_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid probe API key",
        )

    probes = (await db.execute(
        select(Probe).where(Probe.is_active is True)
    )).scalars().all()

    for probe in probes:
        if verify_api_key(x_probe_api_key, probe.api_key_hash):
            return probe

    logger.warning("probe_auth_failed", key_prefix=x_probe_api_key[:10])
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid probe API key")
