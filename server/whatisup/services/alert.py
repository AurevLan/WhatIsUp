"""Alert dispatch service — email, webhook, Telegram, Slack."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.security import decrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertChannelType, AlertEvent, AlertEventStatus
from whatisup.models.incident import Incident, IncidentScope

logger = structlog.get_logger(__name__)

# ── Digest helpers ─────────────────────────────────────────────────────────────

async def _flush_digest(rule_id: str, channels: list[AlertChannel], ctx: dict) -> None:
    """Lit les événements en attente dans Redis pour rule_id et envoie un message groupé."""
    from whatisup.core.database import get_session_factory
    from whatisup.core.redis import get_redis
    from whatisup.models.alert import AlertChannel as AC, AlertEvent as AE, AlertEventStatus as AES
    import uuid as _uuid

    redis = get_redis()
    redis_key = f"whatisup:digest:{rule_id}"

    raw_events = await redis.lrange(redis_key, 0, -1)
    await redis.delete(redis_key)

    if not raw_events:
        return

    events_data = []
    for raw in raw_events:
        try:
            events_data.append(json.loads(raw))
        except Exception:
            pass

    if not events_data:
        return

    count = len(events_data)
    monitor_name = ctx.get("monitor_name", "Monitor inconnu")
    check_type = ctx.get("check_type", "?").upper()

    # Résumé textuel (multi-canal)
    summary_lines = [
        f"📦 **Digest WhatIsUp — {count} alerte(s) groupée(s)**",
        f"Monitor : {monitor_name} ({check_type})",
        "",
    ]
    for i, ev in enumerate(events_data, 1):
        summary_lines.append(
            f"{i}. [{ev.get('event_type', '?')}] {ev.get('started_at', '')} "
            f"— scope : {ev.get('scope', '?')}"
        )
    summary_text = "\n".join(summary_lines)

    # Envoyer sur chaque canal via une session DB fraîche
    async with get_session_factory()() as db:
        for channel in channels:
            try:
                decrypted_config = decrypt_channel_config(channel.config)
                # Envoi simplifié via les fonctions existantes — on crée un faux incident digest
                # Pour chaque canal on utilise directement httpx/smtp selon le type
                if channel.type == AlertChannelType.email:
                    settings = get_settings()
                    msg = EmailMessage()
                    msg["From"] = str(settings.smtp_from)
                    msg["To"] = ", ".join(decrypted_config["to"])
                    msg["Subject"] = f"[WhatIsUp] Digest — {count} alertes groupées : {monitor_name}"
                    msg.set_content(summary_text.replace("**", "").replace("*", ""))
                    await aiosmtplib.send(
                        msg,
                        hostname=settings.smtp_host,
                        port=settings.smtp_port,
                        start_tls=settings.smtp_tls,
                        username=settings.smtp_user or None,
                        password=settings.smtp_password or None,
                        timeout=15,
                    )
                elif channel.type == AlertChannelType.telegram:
                    url = f"https://api.telegram.org/bot{decrypted_config['bot_token']}/sendMessage"
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(
                            url,
                            json={"chat_id": decrypted_config["chat_id"], "text": summary_text, "parse_mode": "Markdown"},
                        )
                elif channel.type == AlertChannelType.slack:
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(
                            decrypted_config["webhook_url"],
                            json={"text": summary_text},
                        )
                elif channel.type == AlertChannelType.webhook:
                    _validate_webhook_url(decrypted_config["url"])
                    payload_bytes = json.dumps({
                        "event": "digest",
                        "monitor_name": monitor_name,
                        "check_type": check_type,
                        "count": count,
                        "events": events_data,
                    }).encode()
                    headers = {"Content-Type": "application/json", "User-Agent": "WhatIsUp/1.0"}
                    if secret := decrypted_config.get("secret"):
                        sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
                        headers["X-WhatIsUp-Signature"] = f"sha256={sig}"
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.post(decrypted_config["url"], content=payload_bytes, headers=headers)
                        resp.raise_for_status()

                digest_event = AE(
                    incident_id=_uuid.UUID(events_data[0].get("incident_id", str(_uuid.uuid4()))),
                    channel_id=channel.id,
                    sent_at=datetime.now(UTC),
                    status=AES.sent,
                    response_body=f"digest:{count}",
                )
                db.add(digest_event)
                logger.info("digest_sent", rule_id=rule_id, channel_id=str(channel.id), count=count)
            except Exception as exc:
                logger.error("digest_dispatch_failed", rule_id=rule_id, channel_id=str(channel.id), error=str(exc))
        await db.commit()


async def maybe_digest_or_dispatch(
    db: AsyncSession,
    incident: Incident,
    channel: AlertChannel,
    rule,
    event_type: str,
    ctx: dict[str, Any],
) -> None:
    """Gère la logique digest : accumule dans Redis ou envoie immédiatement."""
    from whatisup.core.redis import get_redis

    if not rule.digest_minutes or rule.digest_minutes <= 0:
        await dispatch_alert(db, incident, channel, event_type, ctx=ctx)
        return

    redis = get_redis()
    redis_key = f"whatisup:digest:{rule.id}"

    event_payload = json.dumps({
        "incident_id": str(incident.id),
        "monitor_id": str(incident.monitor_id),
        "event_type": event_type,
        "scope": incident.scope.value,
        "started_at": incident.started_at.isoformat(),
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
    })

    count = await redis.lpush(redis_key, event_payload)
    await redis.expire(redis_key, rule.digest_minutes * 60)

    if count == 1:
        # Premier événement dans la fenêtre — programmer le flush différé
        channels_snapshot = list(rule.channels)
        ctx_snapshot = dict(ctx)
        rule_id_str = str(rule.id)
        loop = asyncio.get_event_loop()
        loop.call_later(
            rule.digest_minutes * 60,
            lambda: asyncio.ensure_future(
                _flush_digest(rule_id_str, channels_snapshot, ctx_snapshot)
            ),
        )
        logger.info(
            "digest_scheduled",
            rule_id=rule_id_str,
            digest_minutes=rule.digest_minutes,
        )
    # count > 1 → la fenêtre est déjà ouverte, ne pas envoyer maintenant


async def dispatch_alert(
    db: AsyncSession,
    incident: Incident,
    channel: AlertChannel,
    event_type: str = "incident_opened",
    ctx: dict[str, Any] | None = None,
) -> None:
    """Dispatch an alert to a channel and record the AlertEvent.

    ctx (optional enriched context):
        monitor_name: str
        check_type: str
        probe_names: dict[str, str]  # probe_id -> probe name
    """
    settings = get_settings()
    now = datetime.now(UTC)
    status = AlertEventStatus.sent
    response_body = None
    ctx = ctx or {}
    # Decrypt secrets at dispatch time (config stored encrypted at rest)
    decrypted_config = decrypt_channel_config(channel.config)

    try:
        if channel.type == AlertChannelType.email:
            await _send_email(incident, channel, event_type, settings, ctx, decrypted_config)
        elif channel.type == AlertChannelType.webhook:
            response_body = await _send_webhook(incident, channel, event_type, ctx, decrypted_config)
        elif channel.type == AlertChannelType.telegram:
            response_body = await _send_telegram(incident, channel, event_type, ctx, decrypted_config)
        elif channel.type == AlertChannelType.slack:
            response_body = await _send_slack(incident, channel, event_type, ctx, decrypted_config)
        elif channel.type == AlertChannelType.pagerduty:
            monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
            details = _scope_label_en(incident, ctx)
            inc_status = "down" if event_type != "incident_resolved" else "up"
            response_body = await _send_pagerduty(
                decrypted_config, monitor_name, str(incident.id), inc_status, details, settings
            )
        elif channel.type == AlertChannelType.opsgenie:
            monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
            details = _scope_label_en(incident, ctx)
            inc_status = "down" if event_type != "incident_resolved" else "up"
            response_body = await _send_opsgenie(
                decrypted_config, monitor_name, str(incident.id), inc_status, details, settings
            )
    except Exception as exc:
        logger.error(
            "alert_dispatch_failed",
            channel_id=str(channel.id),
            channel_type=channel.type.value,
            error=str(exc),
        )
        status = AlertEventStatus.failed
        response_body = type(exc).__name__

    event = AlertEvent(
        incident_id=incident.id,
        channel_id=channel.id,
        sent_at=now,
        status=status,
        response_body=response_body,
    )
    db.add(event)


# ── Context helpers ────────────────────────────────────────────────────────────

def _scope_label(incident: Incident, ctx: dict) -> str:
    probe_names: dict = ctx.get("probe_names", {})
    affected = incident.affected_probe_ids or []

    if incident.scope == IncidentScope.global_:
        return "Panne globale (toutes les sondes)"

    if len(affected) == 1:
        name = probe_names.get(affected[0], affected[0])
        return f"Panne géographique — sonde : {name}"

    names = [probe_names.get(pid, pid) for pid in affected]
    return f"Panne géographique — sondes : {', '.join(names)}"


def _scope_label_en(incident: Incident, ctx: dict) -> str:
    probe_names: dict = ctx.get("probe_names", {})
    affected = incident.affected_probe_ids or []

    if incident.scope == IncidentScope.global_:
        return "Global outage (all probes)"

    if len(affected) == 1:
        name = probe_names.get(affected[0], affected[0])
        return f"Geographic outage — probe: {name}"

    names = [probe_names.get(pid, pid) for pid in affected]
    return f"Geographic outage — probes: {', '.join(names)}"


# ── Email ──────────────────────────────────────────────────────────────────────

async def _send_email(
    incident: Incident,
    channel: AlertChannel,
    event_type: str,
    settings,
    ctx: dict,
    config: dict,
) -> None:
    monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
    check_type = ctx.get("check_type", "?")
    scope_label = _scope_label(incident, ctx)

    is_resolved = event_type == "incident_resolved"
    subject = (
        f"[WhatIsUp] {'RÉSOLU' if is_resolved else 'ALERTE'}: "
        f"{monitor_name} ({check_type.upper()}) — {scope_label}"
    )
    body = _build_email_body(incident, event_type, monitor_name, check_type, ctx)

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


def _build_email_body(
    incident: Incident,
    event_type: str,
    monitor_name: str,
    check_type: str,
    ctx: dict,
) -> str:
    status_emoji = "✅" if event_type == "incident_resolved" else "🔴"
    scope_label = _scope_label(incident, ctx)
    resolved_line = ""
    if incident.resolved_at:
        resolved_line = f"<p><b>Résolu le :</b> {incident.resolved_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</p>"
        if incident.duration_seconds:
            resolved_line += f"<p><b>Durée :</b> {incident.duration_seconds}s</p>"

    return f"""
    <html><body style="font-family: sans-serif; color: #333;">
    <h2>{status_emoji} WhatIsUp — {scope_label}</h2>
    <p><b>Monitor :</b> {monitor_name}</p>
    <p><b>Type :</b> {check_type.upper()}</p>
    <p><b>Début :</b> {incident.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
    {resolved_line}
    <hr><p style="color:#888; font-size:12px;">WhatIsUp Monitoring</p>
    </body></html>
    """


# ── Webhook ────────────────────────────────────────────────────────────────────

def _validate_webhook_url(url: str) -> None:
    """Reject webhook URLs pointing to internal/private IP ranges (SSRF prevention)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Webhook URL scheme must be http or https, got: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL has no hostname")

    # Reject private/loopback hostnames by name
    if hostname.lower() in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError(f"Webhook URL points to blocked host: {hostname!r}")

    # Resolve hostname and reject private/internal IP ranges
    try:
        addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for addr_info in addr_infos:
            resolved_ip = addr_info[4][0]
            ip = ipaddress.ip_address(resolved_ip)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                raise ValueError(f"Webhook URL resolves to internal IP: {resolved_ip!r}")
    except socket.gaierror:
        pass  # DNS lookup failed — skip IP check, let httpx handle it


async def _send_webhook(
    incident: Incident,
    channel: AlertChannel,
    event_type: str,
    ctx: dict,
    config: dict,
) -> str:
    _validate_webhook_url(config["url"])
    probe_names = ctx.get("probe_names", {})
    payload = {
        "event": event_type,
        "monitor_id": str(incident.monitor_id),
        "monitor_name": ctx.get("monitor_name", str(incident.monitor_id)),
        "check_type": ctx.get("check_type", "unknown"),
        "incident_id": str(incident.id),
        "scope": incident.scope.value,
        "affected_probes": [
            {"id": pid, "name": probe_names.get(pid, pid)}
            for pid in (incident.affected_probe_ids or [])
        ],
        "started_at": incident.started_at.isoformat(),
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "duration_seconds": incident.duration_seconds,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    payload_bytes = json.dumps(payload).encode()

    headers = {"Content-Type": "application/json", "User-Agent": "WhatIsUp/1.0"}
    if secret := config.get("secret"):
        sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        headers["X-WhatIsUp-Signature"] = f"sha256={sig}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(config["url"], content=payload_bytes, headers=headers)
        resp.raise_for_status()
        return f"HTTP {resp.status_code}"


# ── Telegram ───────────────────────────────────────────────────────────────────

async def _send_telegram(
    incident: Incident,
    channel: AlertChannel,
    event_type: str,
    ctx: dict,
    config: dict,
) -> str:
    monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
    check_type = ctx.get("check_type", "?").upper()
    scope_label = _scope_label(incident, ctx)

    is_resolved = event_type == "incident_resolved"
    status_emoji = "✅" if is_resolved else "🔴"

    lines = [
        f"{status_emoji} <b>WhatIsUp — {scope_label}</b>",
        f"<b>Monitor :</b> {monitor_name}",
        f"<b>Type :</b> {check_type}",
        f"<b>Début :</b> {incident.started_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    if is_resolved and incident.resolved_at:
        lines.append(f"<b>Résolu :</b> {incident.resolved_at.strftime('%Y-%m-%d %H:%M UTC')}")
        if incident.duration_seconds:
            lines.append(f"<b>Durée :</b> {incident.duration_seconds}s")

    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            url,
            json={"chat_id": config["chat_id"], "text": text, "parse_mode": "HTML"},
        )
        resp.raise_for_status()
        return f"HTTP {resp.status_code}"


# ── Slack ──────────────────────────────────────────────────────────────────────

async def _send_slack(
    incident: Incident,
    channel: AlertChannel,
    event_type: str,
    ctx: dict,
    config: dict,
) -> str:
    monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
    check_type = ctx.get("check_type", "?").upper()
    scope_label = _scope_label_en(incident, ctx)

    is_resolved = event_type == "incident_resolved"
    color = "#36a64f" if is_resolved else "#dc3545"
    status_text = "RESOLVED" if is_resolved else "ALERT"

    fields = [
        {"title": "Monitor", "value": monitor_name, "short": True},
        {"title": "Type", "value": check_type, "short": True},
        {"title": "Scope", "value": scope_label, "short": False},
        {"title": "Started", "value": incident.started_at.strftime("%Y-%m-%d %H:%M UTC"), "short": True},
    ]
    if is_resolved and incident.duration_seconds:
        fields.append({"title": "Duration", "value": f"{incident.duration_seconds}s", "short": True})

    payload = {
        "attachments": [{
            "color": color,
            "title": f"WhatIsUp — {status_text}",
            "fields": fields,
            "footer": "WhatIsUp Monitoring",
            "ts": int(incident.started_at.timestamp()),
        }]
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(config["webhook_url"], json=payload)
        resp.raise_for_status()
        return f"HTTP {resp.status_code}"


# ── PagerDuty ──────────────────────────────────────────────────────────────────

async def _send_pagerduty(
    config: dict,
    monitor_name: str,
    incident_id: str,
    status: str,
    details: str,
    settings,
) -> str:
    """Send an alert to PagerDuty Events API v2.

    URLs are hardcoded — no SSRF risk.
    In non-production environments, only logs the event (no real HTTP call).
    """
    if not settings.is_production:
        logger.debug(
            "pagerduty_skipped_non_production",
            monitor_name=monitor_name,
            incident_id=incident_id,
            status=status,
        )
        return "skipped:non_production"

    url = "https://events.pagerduty.com/v2/enqueue"
    event_action = "trigger" if status == "down" else "resolve"
    status_emoji = "🔴" if status == "down" else "✅"
    payload = {
        "routing_key": config["integration_key"],
        "event_action": event_action,
        "dedup_key": f"whatisup-{incident_id}",
        "payload": {
            "summary": f"{status_emoji} {monitor_name}: {details}",
            "severity": config.get("severity", "critical"),
            "source": "WhatIsUp",
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return f"HTTP {resp.status_code}"


# ── Opsgenie ───────────────────────────────────────────────────────────────────

async def _send_opsgenie(
    config: dict,
    monitor_name: str,
    incident_id: str,
    status: str,
    details: str,
    settings,
) -> str:
    """Send an alert to Opsgenie Alerts API.

    URLs are hardcoded — no SSRF risk.
    In non-production environments, only logs the event (no real HTTP call).
    """
    if not settings.is_production:
        logger.debug(
            "opsgenie_skipped_non_production",
            monitor_name=monitor_name,
            incident_id=incident_id,
            status=status,
        )
        return "skipped:non_production"

    region = config.get("region", "us")
    base_url = (
        "https://api.opsgenie.com" if region == "us" else "https://api.eu.opsgenie.com"
    )
    headers = {"Authorization": f"GenieKey {config['api_key']}"}

    if status == "down":
        url = f"{base_url}/v2/alerts"
        payload = {
            "message": f"{monitor_name}: {details}",
            "alias": f"whatisup-{incident_id}",
            "priority": config.get("priority", "P1"),
            "source": "WhatIsUp",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"
    else:
        url = f"{base_url}/v2/alerts/whatisup-{incident_id}/close"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"source": "WhatIsUp"}, headers=headers)
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"
