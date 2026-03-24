"""Web Push subscription endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.config import get_settings
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.user import User
from whatisup.models.web_push import WebPushSubscription
from whatisup.schemas.web_push import WebPushPublicKeyOut, WebPushSubscribeIn, WebPushSubscriptionOut

router = APIRouter(prefix="/push", tags=["web-push"])


@router.get("/vapid-public-key", response_model=WebPushPublicKeyOut)
async def get_vapid_public_key() -> WebPushPublicKeyOut:
    """Return the VAPID public key for the frontend to subscribe."""
    settings = get_settings()
    return WebPushPublicKeyOut(
        public_key=settings.vapid_public_key,
        enabled=bool(settings.vapid_public_key and settings.vapid_private_key),
    )


@router.get("/subscription", response_model=WebPushSubscriptionOut | None)
@limiter.limit("30/minute")
async def get_subscription(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebPushSubscriptionOut | None:
    """Return the current user's push subscription (most recent)."""
    sub = (
        await db.execute(
            select(WebPushSubscription)
            .where(WebPushSubscription.user_id == current_user.id)
            .order_by(WebPushSubscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return sub


@router.post("/subscription", response_model=WebPushSubscriptionOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def subscribe(
    request: Request,
    body: WebPushSubscribeIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebPushSubscriptionOut:
    """Register or update a push subscription for the current user."""
    settings = get_settings()
    if not settings.vapid_public_key or not settings.vapid_private_key:
        raise HTTPException(status_code=503, detail="Web Push not configured on this server.")

    # Upsert: if same endpoint already exists, update keys
    existing = (
        await db.execute(
            select(WebPushSubscription).where(
                WebPushSubscription.user_id == current_user.id,
                WebPushSubscription.endpoint == body.endpoint,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.p256dh = body.p256dh
        existing.auth = body.auth
        if body.user_agent:
            existing.user_agent = body.user_agent
        await db.commit()
        await db.refresh(existing)
        return existing

    sub = WebPushSubscription(
        user_id=current_user.id,
        endpoint=body.endpoint,
        p256dh=body.p256dh,
        auth=body.auth,
        user_agent=body.user_agent,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


@router.delete("/subscription", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def unsubscribe(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove all push subscriptions for the current user."""
    subs = (
        await db.execute(
            select(WebPushSubscription).where(WebPushSubscription.user_id == current_user.id)
        )
    ).scalars().all()
    for sub in subs:
        await db.delete(sub)
    await db.commit()


@router.post("/subscription/test", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def test_push(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Send a test push notification to the current user."""
    from whatisup.services.web_push import send_push_to_user

    await send_push_to_user(
        db,
        current_user.id,
        title="WhatIsUp — Test notification",
        body="Push notifications are working correctly.",
        url="/",
    )
