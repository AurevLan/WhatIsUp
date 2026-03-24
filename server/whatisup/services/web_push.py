"""Web Push notification service (VAPID)."""

from __future__ import annotations

import asyncio
import json
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings

logger = structlog.get_logger(__name__)


def _send_one(endpoint: str, p256dh: str, auth: str, payload: str, private_key: str, contact: str) -> None:
    """Synchronous push send — runs in a thread pool via asyncio.to_thread."""
    try:
        from pywebpush import WebPushException, webpush

        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            },
            data=payload,
            vapid_private_key=private_key,
            vapid_claims={"sub": f"mailto:{contact}"},
            timeout=10,
        )
    except WebPushException as exc:
        # 410 Gone = subscription expired, caller should delete it
        raise
    except Exception as exc:
        logger.error("web_push_error", endpoint=endpoint[:60], error=str(exc))
        raise


async def send_push_to_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    body: str,
    url: str = "/",
) -> None:
    """Send a push notification to all subscriptions of a user."""
    settings = get_settings()
    if not settings.vapid_private_key or not settings.vapid_public_key:
        return

    from whatisup.models.web_push import WebPushSubscription

    subs = (
        await db.execute(
            select(WebPushSubscription).where(WebPushSubscription.user_id == user_id)
        )
    ).scalars().all()

    if not subs:
        return

    payload = json.dumps({"title": title, "body": body, "url": url})
    stale_ids: list[uuid.UUID] = []

    for sub in subs:
        try:
            await asyncio.to_thread(
                _send_one,
                sub.endpoint,
                sub.p256dh,
                sub.auth,
                payload,
                settings.vapid_private_key,
                settings.vapid_contact_email,
            )
        except Exception as exc:
            from pywebpush import WebPushException

            if isinstance(exc, WebPushException) and exc.response is not None and exc.response.status_code == 410:
                # Subscription expired — queue for removal
                stale_ids.append(sub.id)
            else:
                logger.warning("web_push_failed", user_id=str(user_id), error=str(exc))

    # Remove stale subscriptions
    for stale_id in stale_ids:
        stale = await db.get(WebPushSubscription, stale_id)
        if stale:
            await db.delete(stale)
    if stale_ids:
        await db.commit()


async def dispatch_web_push_for_incident(
    db: AsyncSession,
    incident,
    monitor,
    event_type: str,
) -> None:
    """Fire web push notification for an incident open/resolve event."""
    if event_type == "incident_opened":
        title = f"🔴 {monitor.name} is DOWN"
        body = f"An incident was detected. Check your dashboard."
    elif event_type == "incident_resolved":
        title = f"✅ {monitor.name} is back UP"
        body = "The incident has been resolved."
    else:
        return

    try:
        await send_push_to_user(db, monitor.owner_id, title, body, url="/monitors")
    except Exception as exc:
        logger.error("dispatch_web_push_error", monitor_id=str(monitor.id), error=str(exc))
