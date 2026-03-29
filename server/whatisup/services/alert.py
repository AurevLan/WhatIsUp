"""Alert dispatch service — email, webhook, Telegram, Slack."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
import zoneinfo
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.security import decrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertChannelType, AlertEvent, AlertEventStatus
from whatisup.models.incident import Incident
from whatisup.services.channels._helpers import validate_webhook_url as _validate_webhook_url

logger = structlog.get_logger(__name__)

# ── Channel test ───────────────────────────────────────────────────────────────


async def test_channel(channel: AlertChannel) -> tuple[bool, str]:
    """Send a test notification to the channel. Returns (success, detail)."""
    from whatisup.services.channels import CHANNEL_REGISTRY

    settings = get_settings()
    decrypted_config = decrypt_channel_config(channel.config)

    try:
        handler = CHANNEL_REGISTRY.get(channel.type.value)
        if handler is None:
            return False, f"Type de canal non supporté : {channel.type}"
        return await handler.test(decrypted_config, settings)
    except Exception as exc:
        logger.warning("channel_test_failed", channel_id=str(channel.id), error=str(exc))
        return False, str(exc)


# ── Rule simulation ────────────────────────────────────────────────────────────


async def simulate_rule(db: AsyncSession, rule) -> dict:
    """Evaluate a rule against the current state of its monitors.

    Returns a dict with: would_fire, reason, monitor_name, affected_monitors.
    Does NOT send any alert.
    """
    from whatisup.models.monitor import Monitor
    from whatisup.models.result import CheckResult

    # Collect monitors targeted by this rule
    if rule.monitor_id:
        monitors = (
            (await db.execute(select(Monitor).where(Monitor.id == rule.monitor_id)))
            .scalars()
            .all()
        )
    elif rule.group_id:
        monitors = (
            (
                await db.execute(
                    select(Monitor).where(Monitor.group_id == rule.group_id)
                )
            )
            .scalars()
            .all()
        )
    else:
        return {
            "would_fire": False,
            "reason": "Aucun monitor ciblé",
            "monitor_name": None,
            "affected_monitors": [],
        }

    if not monitors:
        return {
            "would_fire": False,
            "reason": "Aucun monitor trouvé",
            "monitor_name": None,
            "affected_monitors": [],
        }

    monitor_ids = [m.id for m in monitors]
    monitors_by_id = {m.id: m for m in monitors}

    # Get latest CheckResult per monitor
    subq = (
        select(
            CheckResult.monitor_id,
            func.max(CheckResult.checked_at).label("max_checked_at"),
        )
        .where(CheckResult.monitor_id.in_(monitor_ids))
        .group_by(CheckResult.monitor_id)
        .subquery()
    )
    latest_results = (
        (
            await db.execute(
                select(CheckResult).join(
                    subq,
                    (CheckResult.monitor_id == subq.c.monitor_id)
                    & (CheckResult.checked_at == subq.c.max_checked_at),
                )
            )
        )
        .scalars()
        .all()
    )

    results_by_monitor: dict[uuid.UUID, list] = {}
    for r in latest_results:
        results_by_monitor.setdefault(r.monitor_id, []).append(r)

    condition = rule.condition

    if condition in ("any_down", "all_down"):
        down_monitors = []
        for mid in monitor_ids:
            results = results_by_monitor.get(mid, [])
            if not results:
                continue
            is_down = any(r.status != "up" for r in results)
            if is_down:
                down_monitors.append(monitors_by_id[mid].name)

        if condition == "any_down":
            would_fire = len(down_monitors) > 0
            names = ", ".join(down_monitors)
            reason = (
                f"{len(down_monitors)} monitor(s) actuellement en panne : {names}"
                if would_fire
                else "Tous les monitors sont UP"
            )
        else:  # all_down
            would_fire = len(down_monitors) == len(monitor_ids)
            reason = (
                "Panne globale — tous les monitors sont down"
                if would_fire
                else f"{len(down_monitors)}/{len(monitor_ids)} monitors en panne (pas encore tous)"
            )
        return {
            "would_fire": would_fire,
            "reason": reason,
            "monitor_name": monitors[0].name if len(monitors) == 1 else None,
            "affected_monitors": down_monitors,
        }

    elif condition == "response_time_above":
        threshold = rule.threshold_value or 0
        slow_monitors = []
        for mid in monitor_ids:
            results = results_by_monitor.get(mid, [])
            for r in results:
                if r.response_time_ms is not None and r.response_time_ms > threshold:
                    slow_monitors.append(
                        f"{monitors_by_id[mid].name} ({r.response_time_ms:.0f}ms)"
                    )
                    break
        would_fire = len(slow_monitors) > 0
        reason = (
            f"Temps de réponse dépassé sur : {', '.join(slow_monitors)}"
            if would_fire
            else f"Tous les monitors sont sous le seuil de {threshold}ms"
        )
        return {
            "would_fire": would_fire,
            "reason": reason,
            "monitor_name": monitors[0].name if len(monitors) == 1 else None,
            "affected_monitors": slow_monitors,
        }

    elif condition == "ssl_expiry":
        expiring = []
        for mid in monitor_ids:
            results = results_by_monitor.get(mid, [])
            for r in results:
                if r.ssl_days_remaining is not None and r.ssl_days_remaining < 30:
                    expiring.append(
                        f"{monitors_by_id[mid].name} (expire dans {r.ssl_days_remaining}j)"
                    )
                    break
        would_fire = len(expiring) > 0
        reason = (
            f"Certificat(s) SSL expirant bientôt : {', '.join(expiring)}"
            if would_fire
            else "Tous les certificats SSL sont valides (> 30 jours)"
        )
        return {
            "would_fire": would_fire,
            "reason": reason,
            "monitor_name": monitors[0].name if len(monitors) == 1 else None,
            "affected_monitors": expiring,
        }

    else:
        return {
            "would_fire": False,
            "reason": (
                f"Simulation non supportée pour la condition '{condition}'"
                " (uptime/baseline nécessitent un historique)"
            ),
            "monitor_name": monitors[0].name if len(monitors) == 1 else None,
            "affected_monitors": [],
        }


# ── Digest helpers ─────────────────────────────────────────────────────────────


async def _flush_digest(rule_id: str, channels: list[AlertChannel], ctx: dict) -> None:
    """Lit les événements en attente dans Redis pour rule_id et envoie un message groupé."""
    from whatisup.core.database import get_session_factory
    from whatisup.core.redis import get_redis
    from whatisup.models.alert import AlertEvent as AE
    from whatisup.models.alert import AlertEventStatus as AES

    redis = get_redis()
    events_key = f"whatisup:digest:{rule_id}"

    raw_events = await redis.lrange(events_key, 0, -1)
    await redis.delete(events_key)
    await redis.delete(f"whatisup:digest_ctx:{rule_id}")

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

    async with get_session_factory()() as db:
        for channel in channels:
            try:
                decrypted_config = decrypt_channel_config(channel.config)
                if channel.type == AlertChannelType.email:
                    settings = get_settings()
                    msg = EmailMessage()
                    msg["From"] = str(settings.smtp_from)
                    msg["To"] = ", ".join(decrypted_config["to"])
                    msg["Subject"] = (
                        f"[WhatIsUp] Digest — {count} alertes groupées : {monitor_name}"
                    )
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
                            json={
                                "chat_id": decrypted_config["chat_id"],
                                "text": summary_text,
                                "parse_mode": "Markdown",
                            },
                        )
                elif channel.type == AlertChannelType.slack:
                    _validate_webhook_url(decrypted_config["webhook_url"])
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(
                            decrypted_config["webhook_url"],
                            json={"text": summary_text},
                        )
                elif channel.type == AlertChannelType.webhook:
                    _validate_webhook_url(decrypted_config["url"])
                    payload_bytes = json.dumps(
                        {
                            "event": "digest",
                            "monitor_name": monitor_name,
                            "check_type": check_type,
                            "count": count,
                            "events": events_data,
                        }
                    ).encode()
                    headers = {"Content-Type": "application/json", "User-Agent": "WhatIsUp/1.0"}
                    if secret := decrypted_config.get("secret"):
                        sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
                        headers["X-WhatIsUp-Signature"] = f"sha256={sig}"
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.post(
                            decrypted_config["url"], content=payload_bytes, headers=headers
                        )
                        resp.raise_for_status()

                digest_event = AE(
                    incident_id=uuid.UUID(events_data[0].get("incident_id", str(uuid.uuid4()))),
                    channel_id=channel.id,
                    sent_at=datetime.now(UTC),
                    status=AES.sent,
                    response_body=f"digest:{count}",
                )
                db.add(digest_event)
                logger.info("digest_sent", rule_id=rule_id, channel_id=str(channel.id), count=count)
            except Exception as exc:
                logger.error(
                    "digest_dispatch_failed",
                    rule_id=rule_id,
                    channel_id=str(channel.id),
                    error=str(exc),
                )
        await db.commit()


async def flush_pending_digests() -> None:
    """Background task: flush all digest windows whose scheduled time has passed.

    Called every 30 s from the lifespan loop. Survives server restarts because
    the schedule is stored in a Redis sorted set (not in-memory call_later).
    """
    from sqlalchemy import select

    from whatisup.core.database import get_session_factory
    from whatisup.core.redis import get_redis
    from whatisup.models.alert import AlertChannel as AC

    redis = get_redis()
    schedule_key = "whatisup:digest_schedule"
    now_ts = datetime.now(UTC).timestamp()

    # Atomically pop all entries whose flush time has passed
    due_rule_ids: list[str] = await redis.zrangebyscore(schedule_key, "-inf", now_ts)
    if not due_rule_ids:
        return

    await redis.zremrangebyscore(schedule_key, "-inf", now_ts)

    async with get_session_factory()() as db:
        for rule_id_str in due_rule_ids:
            ctx_key = f"whatisup:digest_ctx:{rule_id_str}"
            raw_ctx = await redis.get(ctx_key)
            if not raw_ctx:
                # Context expired — nothing to send, clean up events list too
                await redis.delete(f"whatisup:digest:{rule_id_str}")
                continue

            try:
                ctx_data = json.loads(raw_ctx)
            except Exception:
                continue

            channel_ids = [uuid.UUID(cid) for cid in ctx_data.get("channel_ids", [])]
            if not channel_ids:
                continue

            channels = (
                (await db.execute(select(AC).where(AC.id.in_(channel_ids)))).scalars().all()
            )
            await _flush_digest(rule_id_str, list(channels), ctx_data.get("ctx", {}))


def _is_within_business_hours(schedule: dict) -> bool:
    """Return True if the current moment falls within the defined business hours schedule."""
    tz_name = schedule.get("timezone", "UTC")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = zoneinfo.ZoneInfo("UTC")

    now_local = datetime.now(tz)
    weekday = now_local.weekday()  # Monday=0, Sunday=6

    allowed_days: list[int] = schedule.get("days", [0, 1, 2, 3, 4])
    if weekday not in allowed_days:
        return False

    start_str = schedule.get("start", "09:00")
    end_str = schedule.get("end", "18:00")
    try:
        sh, sm = int(start_str.split(":")[0]), int(start_str.split(":")[1])
        eh, em = int(end_str.split(":")[0]), int(end_str.split(":")[1])
    except Exception:
        return True

    current_minutes = now_local.hour * 60 + now_local.minute
    return (sh * 60 + sm) <= current_minutes <= (eh * 60 + em)


async def maybe_digest_or_dispatch(
    db: AsyncSession,
    incident: Incident,
    channel: AlertChannel,
    rule,
    event_type: str,
    ctx: dict[str, Any],
) -> None:
    """Gère la logique digest : accumule dans Redis ou envoie immédiatement.

    Le flush est géré par le background flusher (_digest_flusher_loop) qui
    survit aux redémarrages — contrairement à asyncio.call_later (in-memory).
    """
    from whatisup.core.redis import get_redis

    # Business hours check — suppress off-hours alerts if configured
    if rule.schedule and rule.schedule.get("offhours_suppress"):
        if not _is_within_business_hours(rule.schedule):
            logger.info(
                "alert_suppressed_offhours",
                rule_id=str(rule.id),
                incident_id=str(incident.id),
            )
            return

    if not rule.digest_minutes or rule.digest_minutes <= 0:
        await dispatch_alert(db, incident, channel, event_type, ctx=ctx)
        return

    redis = get_redis()
    rule_id_str = str(rule.id)
    events_key = f"whatisup:digest:{rule_id_str}"
    ctx_key = f"whatisup:digest_ctx:{rule_id_str}"
    schedule_key = "whatisup:digest_schedule"
    ttl = rule.digest_minutes * 60

    event_payload = json.dumps(
        {
            "incident_id": str(incident.id),
            "monitor_id": str(incident.monitor_id),
            "event_type": event_type,
            "scope": incident.scope.value,
            "started_at": incident.started_at.isoformat(),
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        }
    )

    count = await redis.lpush(events_key, event_payload)
    await redis.expire(events_key, ttl + 300)  # +5 min de marge pour le flusher

    if count == 1:
        # Premier événement : flush au prochain bucket arrondi (fenêtre glissante)
        now_ts = datetime.now(UTC).timestamp()
        flush_at = (int(now_ts) // ttl + 1) * ttl
        await redis.zadd(schedule_key, {rule_id_str: flush_at})

        # Stocker le contexte (channel_ids + monitor ctx) pour le flusher
        ctx_payload = json.dumps(
            {
                "channel_ids": [str(c.id) for c in rule.channels],
                "ctx": ctx,
            }
        )
        await redis.setex(ctx_key, ttl + 300, ctx_payload)

        logger.info(
            "digest_scheduled",
            rule_id=rule_id_str,
            digest_minutes=rule.digest_minutes,
        )
    # count > 1 → la fenêtre est déjà ouverte, accumuler sans reprogrammer


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
    # Deduplication: skip if same incident+channel was alerted within last 60s
    recent_dup = (
        await db.execute(
            select(AlertEvent)
            .where(
                AlertEvent.incident_id == incident.id,
                AlertEvent.channel_id == channel.id,
                AlertEvent.status == AlertEventStatus.sent,
                AlertEvent.sent_at >= datetime.now(UTC) - timedelta(seconds=60),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent_dup:
        logger.info(
            "alert_deduplicated",
            incident_id=str(incident.id),
            channel_id=str(channel.id),
        )
        return

    settings = get_settings()
    now = datetime.now(UTC)
    status = AlertEventStatus.sent
    response_body = None
    ctx = ctx or {}
    # Decrypt secrets at dispatch time (config stored encrypted at rest)
    decrypted_config = decrypt_channel_config(channel.config)

    try:
        from whatisup.services.channels import CHANNEL_REGISTRY

        handler = CHANNEL_REGISTRY.get(channel.type.value)
        if handler is not None:
            response_body = await handler.send(
                incident, channel, event_type, ctx, decrypted_config, settings
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


