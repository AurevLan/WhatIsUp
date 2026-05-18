"""Web Push notification service (VAPID)."""

from __future__ import annotations

import asyncio
import json
import uuid
from urllib.parse import urlparse

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.services.channels._helpers import validate_webhook_url

logger = structlog.get_logger(__name__)

# Known Web Push provider host suffixes. The endpoint is later used as the
# target of an outbound request, so it must point at a real push service.
_ALLOWED_PUSH_HOST_SUFFIXES = (
    ".push.services.mozilla.com",  # Firefox autopush
    ".googleapis.com",  # Chromium — fcm.googleapis.com
    ".push.apple.com",  # Safari Web Push
    ".notify.windows.com",  # Edge / WNS
)


class InvalidPushEndpoint(ValueError):
    """Raised when a Web Push endpoint is not an allowed push-service URL."""


async def validate_push_endpoint(endpoint: str) -> None:
    """SSRF guard for user-supplied Web Push endpoints (SEC-H1).

    Without this an authenticated user could register
    ``endpoint=http://169.254.169.254/...`` and have the server issue an
    outbound request there via ``pywebpush``. We require https + a known push
    provider host, then run the shared SSRF resolver as defence in depth.
    """
    parsed = urlparse(endpoint)
    if parsed.scheme != "https":
        raise InvalidPushEndpoint("Push endpoint must use https")
    host = (parsed.hostname or "").lower()
    if not host or not host.endswith(_ALLOWED_PUSH_HOST_SUFFIXES):
        raise InvalidPushEndpoint("Push endpoint host is not an allowed push service")
    # Defence in depth: reject DNS results pointing at private/loopback/metadata.
    await validate_webhook_url(endpoint)


def _send_one(
    endpoint: str, p256dh: str, auth: str, payload: str, private_key: str, contact: str
) -> None:
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
    except WebPushException:
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
        (
            await db.execute(
                select(WebPushSubscription).where(WebPushSubscription.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )

    if not subs:
        return

    payload = json.dumps({"title": title, "body": body, "url": url})
    stale_ids: list[uuid.UUID] = []

    for sub in subs:
        # Re-validate at dispatch: guards stored endpoints that predate the
        # subscription-time check and narrows the DNS-rebinding window.
        try:
            await validate_push_endpoint(sub.endpoint)
        except ValueError as exc:
            logger.warning("web_push_endpoint_rejected", user_id=str(user_id), error=str(exc))
            continue
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

            if (
                isinstance(exc, WebPushException)
                and exc.response is not None
                and exc.response.status_code == 410
            ):
                # Subscription expired — queue for removal
                stale_ids.append(sub.id)
            else:
                logger.warning("web_push_failed", user_id=str(user_id), error=str(exc))

    # Remove stale subscriptions (batch delete)
    if stale_ids:
        from sqlalchemy import delete as sa_delete

        await db.execute(
            sa_delete(WebPushSubscription).where(WebPushSubscription.id.in_(stale_ids))
        )
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
        body = "An incident was detected. Check your dashboard."
    elif event_type == "incident_resolved":
        title = f"✅ {monitor.name} is back UP"
        body = "The incident has been resolved."
    else:
        return

    try:
        await send_push_to_user(db, monitor.owner_id, title, body, url="/monitors")
    except Exception as exc:
        logger.error("dispatch_web_push_error", monitor_id=str(monitor.id), error=str(exc))
