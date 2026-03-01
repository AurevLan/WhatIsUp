"""Alert dispatch service — email, webhook, Telegram."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from email.message import EmailMessage

import aiosmtplib
import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.models.alert import AlertChannel, AlertChannelType, AlertEvent, AlertEventStatus
from whatisup.models.incident import Incident

logger = structlog.get_logger(__name__)


async def dispatch_alert(
    db: AsyncSession,
    incident: Incident,
    channel: AlertChannel,
    event_type: str = "incident_opened",
) -> None:
    """Dispatch an alert to a channel and record the AlertEvent."""
    settings = get_settings()
    now = datetime.now(UTC)
    status = AlertEventStatus.sent
    response_body = None

    try:
        if channel.type == AlertChannelType.email:
            await _send_email(incident, channel, event_type, settings)
        elif channel.type == AlertChannelType.webhook:
            response_body = await _send_webhook(incident, channel, event_type)
        elif channel.type == AlertChannelType.telegram:
            response_body = await _send_telegram(incident, channel, event_type)
    except Exception as exc:
        logger.error(
            "alert_dispatch_failed",
            channel_id=str(channel.id),
            channel_type=channel.type.value,
            error=str(exc),
        )
        status = AlertEventStatus.failed
        response_body = str(exc)[:500]

    event = AlertEvent(
        incident_id=incident.id,
        channel_id=channel.id,
        sent_at=now,
        status=status,
        response_body=response_body,
    )
    db.add(event)


async def _send_email(
    incident: Incident,
    channel: AlertChannel,
    event_type: str,
    settings,
) -> None:
    config = channel.config
    subject = (
        f"[WhatIsUp] {'RESOLVED' if event_type == 'incident_resolved' else 'ALERT'}: "
        f"Monitor {incident.monitor_id} — {incident.scope.value} outage"
    )
    body = _build_email_body(incident, event_type)

    msg = EmailMessage()
    msg["From"] = str(settings.smtp_from)
    msg["To"] = ", ".join(config["to"])
    msg["Subject"] = subject
    msg.set_content(body, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        start_tls=settings.smtp_tls,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        timeout=15,
    )


def _build_email_body(incident: Incident, event_type: str) -> str:
    status_emoji = "✅" if event_type == "incident_resolved" else "🔴"
    scope_label = "Panne globale" if incident.scope.value == "global" else "Panne géographique"
    resolved_line = ""
    if incident.resolved_at:
        resolved_line = f"<p><b>Résolu le :</b> {incident.resolved_at.isoformat()}</p>"
        if incident.duration_seconds:
            resolved_line += f"<p><b>Durée :</b> {incident.duration_seconds}s</p>"

    return f"""
    <html><body style="font-family: sans-serif; color: #333;">
    <h2>{status_emoji} WhatIsUp — {scope_label}</h2>
    <p><b>Monitor ID :</b> {incident.monitor_id}</p>
    <p><b>Début :</b> {incident.started_at.isoformat()}</p>
    <p><b>Sondes affectées :</b> {', '.join(incident.affected_probe_ids) or 'N/A'}</p>
    {resolved_line}
    <hr><p style="color:#888; font-size:12px;">WhatIsUp Monitoring</p>
    </body></html>
    """


async def _send_webhook(
    incident: Incident,
    channel: AlertChannel,
    event_type: str,
) -> str:
    config = channel.config
    payload = {
        "event": event_type,
        "monitor_id": str(incident.monitor_id),
        "incident_id": str(incident.id),
        "scope": incident.scope.value,
        "started_at": incident.started_at.isoformat(),
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "duration_seconds": incident.duration_seconds,
        "affected_probe_ids": incident.affected_probe_ids,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    payload_bytes = json.dumps(payload).encode()

    headers = {"Content-Type": "application/json", "User-Agent": "WhatIsUp/0.1"}
    if secret := config.get("secret"):
        sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        headers["X-WhatIsUp-Signature"] = f"sha256={sig}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(config["url"], content=payload_bytes, headers=headers)
        resp.raise_for_status()
        return resp.text[:500]


async def _send_telegram(
    incident: Incident,
    channel: AlertChannel,
    event_type: str,
) -> str:
    config = channel.config
    status_emoji = "✅" if event_type == "incident_resolved" else "🔴"
    scope_label = "Panne globale" if incident.scope.value == "global" else "Panne géographique"
    text = (
        f"{status_emoji} <b>WhatIsUp — {scope_label}</b>\n"
        f"Monitor: <code>{incident.monitor_id}</code>\n"
        f"Début: {incident.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Sondes: {', '.join(incident.affected_probe_ids) or 'N/A'}"
    )
    if incident.resolved_at:
        text += f"\nRésolu: {incident.resolved_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"

    url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            url,
            json={"chat_id": config["chat_id"], "text": text, "parse_mode": "HTML"},
        )
        resp.raise_for_status()
        return resp.text[:500]
