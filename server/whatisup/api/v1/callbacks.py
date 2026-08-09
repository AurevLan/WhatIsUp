"""Inbound chat callbacks — acknowledging from Slack / Telegram (plan V2, B-3).

These are the only endpoints in the product that accept a mutation from an
unauthenticated caller, so the order of checks below is the design, not an
implementation detail:

1. **Our token first.** It names the channel, and until we know the channel we
   do not know which signing secret to verify against. It is also the only thing
   that ties the request to a *specific incident we announced there* — a
   provider signature says nothing about that.
2. **Provider signature**, against that channel's secret. Constant-time, with a
   replay window for Slack.
3. **Who is clicking**, resolved from the chat identity the provider reports,
   matched against ``UserContact``. Never taken from the payload's own idea of
   who the user is beyond that lookup.
4. **Can they see the monitor**, through the same access helper the UI uses.

Reversing 1 and 2 is the cross-tenant hole: an attacker with their own Slack app
knows their own signing secret, so a server that picked the channel from the
payload *after* verifying "a" signature would happily acknowledge a stranger's
incident. Binding the token to the channel first is what closes it.

Every failure answers the same way. These endpoints never reveal whether an
incident exists, whether a token was merely expired rather than forged, or
whether the clicking user is known — an unauthenticated endpoint that
distinguishes those is an oracle.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import decrypt_channel_config
from whatisup.models.alert import AlertChannel
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.oncall import ContactMethod, UserContact
from whatisup.models.team import TeamMembership
from whatisup.models.user import User
from whatisup.services.channel_ack import (
    AckTokenError,
    verify_ack_token,
    verify_slack_signature,
    verify_telegram_secret,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/callbacks", tags=["callbacks"])

#: One opaque answer for every rejection. Anything more specific turns an
#: unauthenticated endpoint into an oracle for incident ids and user handles.
_REFUSED = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid callback")


async def _channel_and_secret(db: AsyncSession, channel_id: uuid.UUID) -> tuple[AlertChannel, str]:
    channel = (
        await db.execute(select(AlertChannel).where(AlertChannel.id == channel_id))
    ).scalar_one_or_none()
    if channel is None:
        raise _REFUSED
    secret = (decrypt_channel_config(channel.config) or {}).get("signing_secret")
    if not secret:
        # The channel stopped carrying a secret since the button was sent. We
        # cannot verify anything, so we refuse — never "accept unsigned".
        raise _REFUSED
    return channel, secret


async def _resolve_clicker(db: AsyncSession, method: ContactMethod, handle: str) -> User | None:
    """The WhatIsUp user behind a chat identity, via their declared contact.

    Deliberately the only bridge: the payload's display name or email is
    attacker-influenced on some providers, whereas a ``UserContact`` row was
    created by an authenticated user under ``_assert_can_page_users``.
    """
    if not handle:
        return None
    contact = (
        await db.execute(
            select(UserContact)
            .where(
                UserContact.method == method,
                UserContact.value == str(handle),
                UserContact.enabled.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if contact is None:
        return None
    user = (await db.execute(select(User).where(User.id == contact.user_id))).scalar_one_or_none()
    return user if (user and user.is_active) else None


async def _acknowledge(
    db: AsyncSession, incident_id: uuid.UUID, channel: AlertChannel, user: User
) -> str:
    """Ack the incident if this user may, or refuse. Returns a message to echo."""
    incident = (
        await db.execute(select(Incident).where(Incident.id == incident_id))
    ).scalar_one_or_none()
    if incident is None:
        raise _REFUSED

    monitor = (
        await db.execute(select(Monitor).where(Monitor.id == incident.monitor_id))
    ).scalar_one_or_none()
    if monitor is None:
        raise _REFUSED

    # Same rule as the UI: owner, or a member of the monitor's team. A
    # superadmin bypass would be explicit; there is deliberately none here,
    # because this path is unauthenticated and a superadmin has the UI.
    if monitor.owner_id != user.id:
        allowed = False
        if monitor.team_id is not None:
            allowed = (
                await db.execute(
                    select(TeamMembership.user_id).where(
                        TeamMembership.team_id == monitor.team_id,
                        TeamMembership.user_id == user.id,
                    )
                )
            ).scalar_one_or_none() is not None
        if not allowed:
            logger.warning(
                "channel_ack_denied",
                incident_id=str(incident_id),
                user_id=str(user.id),
                reason="no_access_to_monitor",
            )
            raise _REFUSED

    if incident.resolved_at is not None:
        return "Incident already resolved."
    if incident.acked_at is not None:
        return "Already acknowledged."

    incident.acked_at = datetime.now(UTC)
    incident.acked_by_id = user.id
    await db.flush()

    # Stop the ladder now rather than at the next tick, so the rung that was
    # about to fire does not page after someone has already answered.
    from whatisup.services.escalation import cancel_escalation

    await cancel_escalation(db, incident.id)

    logger.info(
        "channel_ack_accepted",
        incident_id=str(incident.id),
        user_id=str(user.id),
        channel_id=str(channel.id),
    )
    return "Acknowledged."


@router.post("/slack")
@limiter.limit("60/minute")
async def slack_callback(
    request: Request,
    x_slack_signature: str = Header(default=""),
    x_slack_request_timestamp: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Slack interactive component → acknowledge.

    Slack posts ``payload=<urlencoded json>``. The raw body is needed verbatim
    for the signature, so it is read before any parsing.
    """
    body = await request.body()
    form = await request.form()
    raw_payload = form.get("payload")
    if not raw_payload:
        raise _REFUSED
    try:
        payload = json.loads(raw_payload)
    except (ValueError, TypeError) as exc:
        raise _REFUSED from exc

    actions = payload.get("actions") or []
    token = next((a.get("value") for a in actions if a.get("action_id") == "whatisup_ack"), None)
    if not token:
        raise _REFUSED

    try:
        incident_id, channel_id = verify_ack_token(token)
    except AckTokenError as exc:
        logger.warning("channel_ack_bad_token", provider="slack", reason=str(exc))
        raise _REFUSED from exc

    channel, secret = await _channel_and_secret(db, channel_id)
    if not verify_slack_signature(secret, x_slack_request_timestamp, body, x_slack_signature):
        logger.warning("channel_ack_bad_signature", provider="slack", channel_id=str(channel.id))
        raise _REFUSED

    handle = str((payload.get("user") or {}).get("id") or "")
    user = await _resolve_clicker(db, ContactMethod.slack, handle)
    if user is None:
        logger.warning("channel_ack_unknown_user", provider="slack")
        raise _REFUSED

    text = await _acknowledge(db, incident_id, channel, user)

    # Replaces the original message's buttons in place, so the ack is visible to
    # everyone in the channel rather than only to whoever tapped.
    return {"replace_original": False, "text": f"✅ {text}"}


@router.post("/telegram")
@limiter.limit("60/minute")
async def telegram_callback(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Telegram ``callback_query`` → acknowledge.

    Telegram does not sign the body; it echoes the ``secret_token`` pinned on
    ``setWebhook``. Weaker than Slack's scheme, which is exactly why the ack
    token carries the binding that matters.
    """
    try:
        update = await request.json()
    except (ValueError, TypeError) as exc:
        raise _REFUSED from exc

    query = update.get("callback_query") or {}
    token = query.get("data")
    if not token:
        raise _REFUSED

    try:
        incident_id, channel_id = verify_ack_token(token)
    except AckTokenError as exc:
        logger.warning("channel_ack_bad_token", provider="telegram", reason=str(exc))
        raise _REFUSED from exc

    channel, secret = await _channel_and_secret(db, channel_id)
    if not verify_telegram_secret(secret, x_telegram_bot_api_secret_token):
        logger.warning("channel_ack_bad_signature", provider="telegram", channel_id=str(channel.id))
        raise _REFUSED

    # `from.id` is the person who tapped. In a private chat it equals the
    # chat id a UserContact usually holds; in a group it does not, so both
    # are accepted — the contact row is the authority either way.
    sender = str(((query.get("from") or {}).get("id")) or "")
    chat = str((((query.get("message") or {}).get("chat")) or {}).get("id") or "")
    user = await _resolve_clicker(db, ContactMethod.telegram, sender)
    if user is None and chat:
        user = await _resolve_clicker(db, ContactMethod.telegram, chat)
    if user is None:
        logger.warning("channel_ack_unknown_user", provider="telegram")
        raise _REFUSED

    text = await _acknowledge(db, incident_id, channel, user)

    return {"method": "answerCallbackQuery", "callback_query_id": query.get("id"), "text": text}


__all__ = ["router"]
