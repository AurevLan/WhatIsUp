"""Alert dispatch service — email, webhook, Telegram, Slack."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
import zoneinfo
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import aiosmtplib
import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.metrics import observe_alert_dispatch
from whatisup.core.security import decrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertChannelType, AlertEvent, AlertEventStatus
from whatisup.models.incident import Incident
from whatisup.services.channels._helpers import redact_secrets, ssrf_safe_client
from whatisup.services.channels._helpers import validate_webhook_url as _validate_webhook_url
from whatisup.services.stats import fetch_latest_results

logger = structlog.get_logger(__name__)

#: String values of the pushed-metric conditions. Compared as strings rather
#: than enum members: ``simulate_rule`` receives ORM rules whose ``condition``
#: is an ``AlertCondition``, and the surrounding branches already compare it to
#: plain strings.
_METRIC_CONDITION_VALUES = frozenset({"metric_above", "metric_below", "metric_absent"})

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
        # Never echo a raw provider error: it can carry the channel's own
        # credential (audit F6). Redact against the decrypted config.
        detail = redact_secrets(str(exc), decrypted_config)
        logger.warning("channel_test_failed", channel_id=str(channel.id), error=detail)
        return False, detail


# ── Rule simulation ────────────────────────────────────────────────────────────


async def simulate_rule(db: AsyncSession, rule) -> dict:
    """Evaluate a rule against the current state of its monitors.

    Returns a dict with: would_fire, reason, monitor_name, affected_monitors.
    Does NOT send any alert.

    The per-condition logic lives in ``services/conditions`` next to the
    dispatch logic it has to agree with — see that package's ``base.py``. What
    is left here is what every condition shares: resolving the rule's monitors,
    fetching their latest check once, and shaping the answer.
    """
    from whatisup.models.monitor import Monitor
    from whatisup.services.conditions import PreviewContext, get_handler

    handler = get_handler(rule.condition)

    # Collect monitors targeted by this rule
    if rule.monitor_id:
        monitors = (
            (await db.execute(select(Monitor).where(Monitor.id == rule.monitor_id))).scalars().all()
        )
    elif rule.group_id:
        monitors = (
            (await db.execute(select(Monitor).where(Monitor.group_id == rule.group_id)))
            .scalars()
            .all()
        )
    else:
        return _preview_payload(False, "Aucun monitor ciblé", [], monitors=[])

    if not monitors:
        return _preview_payload(False, "Aucun monitor trouvé", [], monitors=[])

    if handler is None:
        return _preview_payload(
            False,
            f"Simulation non supportée pour la condition '{rule.condition}'",
            [],
            monitors=monitors,
        )

    # Latest CheckResult per monitor — via ``fetch_latest_results``, the LATERAL
    # form from #218. The hand-rolled ``max(checked_at) GROUP BY`` self-join that
    # used to live here aggregates *every historical row* of the listed monitors
    # and carries no time bound, so on the partitioned check_results (A-1) it
    # prunes nothing. Skipped entirely when the condition reads no check row —
    # the three pushed-metric conditions never do.
    latest: dict[uuid.UUID, Any] = {}
    if handler.preview_reads_checks:
        latest = await fetch_latest_results(db, [m.id for m in monitors])

    outcome = await handler.preview(
        PreviewContext(
            db=db,
            rule=rule,
            monitors=list(monitors),
            monitors_by_id={m.id: m for m in monitors},
            latest=latest,
        )
    )
    return _preview_payload(outcome.would_fire, outcome.reason, outcome.affected, monitors=monitors)


def _preview_payload(would_fire: bool, reason: str, affected: list[str], *, monitors) -> dict:
    """Shape ``simulate_rule``'s answer — the wire format the UI reads."""
    return {
        "would_fire": would_fire,
        "reason": reason,
        "monitor_name": monitors[0].name if len(monitors) == 1 else None,
        "affected_monitors": affected,
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
        except Exception as exc:
            logger.warning("digest_event_parse_error", raw=str(raw)[:100], error=str(exc))

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
            # Bound before the try so the except never redacts against the
            # previous channel's config if decryption itself fails.
            decrypted_config: dict = {}
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
                    # Shared helper: keeps the bot_token out of any exception
                    # this POST can raise (audit F6).
                    from whatisup.services.channels.telegram import _post as _telegram_post

                    await _telegram_post(
                        decrypted_config,
                        {
                            "chat_id": decrypted_config["chat_id"],
                            "text": summary_text,
                            "parse_mode": "Markdown",
                        },
                    )
                elif channel.type == AlertChannelType.slack:
                    await _validate_webhook_url(decrypted_config["webhook_url"])
                    async with ssrf_safe_client(timeout=10) as client:
                        await client.post(
                            decrypted_config["webhook_url"],
                            json={"text": summary_text},
                        )
                elif channel.type == AlertChannelType.discord:
                    await _validate_webhook_url(decrypted_config["webhook_url"])
                    async with ssrf_safe_client(timeout=10) as client:
                        await client.post(
                            decrypted_config["webhook_url"],
                            json={"content": summary_text[:1900]},
                        )
                elif channel.type == AlertChannelType.mattermost:
                    await _validate_webhook_url(decrypted_config["webhook_url"])
                    async with ssrf_safe_client(timeout=10) as client:
                        await client.post(
                            decrypted_config["webhook_url"],
                            json={"username": "WhatIsUp", "text": summary_text},
                        )
                elif channel.type == AlertChannelType.teams:
                    await _validate_webhook_url(decrypted_config["webhook_url"])
                    async with ssrf_safe_client(timeout=10) as client:
                        await client.post(
                            decrypted_config["webhook_url"],
                            json={
                                "type": "message",
                                "attachments": [
                                    {
                                        "contentType": "application/vnd.microsoft.card.adaptive",
                                        "content": {
                                            "type": "AdaptiveCard",
                                            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                                            "version": "1.5",
                                            "body": [
                                                {
                                                    "type": "TextBlock",
                                                    "text": summary_text,
                                                    "wrap": True,
                                                }
                                            ],
                                        },
                                    }
                                ],
                            },
                        )
                elif channel.type == AlertChannelType.webhook:
                    await _validate_webhook_url(decrypted_config["url"])
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
                    async with ssrf_safe_client(timeout=10) as client:
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
                    error=redact_secrets(str(exc), decrypted_config),
                )

        # Clean up DB-persisted digest window
        try:
            from whatisup.models.digest_window import DigestWindow

            rule_uuid = uuid.UUID(rule_id)
            dw = (
                await db.execute(select(DigestWindow).where(DigestWindow.rule_id == rule_uuid))
            ).scalar_one_or_none()
            if dw:
                await db.delete(dw)
        except Exception as exc:
            logger.warning("digest_window_cleanup_failed", rule_id=rule_id, error=str(exc))

        await db.commit()


async def flush_pending_digests() -> None:
    """Background task: flush all digest windows whose scheduled time has passed.

    Called every 30 s from the lifespan loop. Survives server restarts because
    the schedule is stored in a Redis sorted set (not in-memory call_later).
    """
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
            except Exception as exc:
                logger.warning("digest_ctx_parse_failed", rule_id=rule_id_str, error=str(exc))
                continue

            channel_ids = [uuid.UUID(cid) for cid in ctx_data.get("channel_ids", [])]
            if not channel_ids:
                continue

            channels = (await db.execute(select(AC).where(AC.id.in_(channel_ids)))).scalars().all()
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
    except Exception as exc:
        logger.error("business_hours_parse_failed", start=start_str, end=end_str, error=str(exc))
        return False

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

    # V2-02-02 — Network partition guard: skip dispatch if the verdict says the
    # outage is only visible from one ASN / one geographic zone (i.e. transit
    # issue, not a real service down). The rule must opt in.
    if getattr(rule, "suppress_on_network_partition", False) and incident.network_verdict in {
        "network_partition_asn",
        "network_partition_geo",
    }:
        logger.info(
            "alert_suppressed_network_partition",
            rule_id=str(rule.id),
            incident_id=str(incident.id),
            verdict=incident.network_verdict,
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

    event_data = json.loads(event_payload)
    count = await redis.lpush(events_key, event_payload)
    await redis.expire(events_key, ttl + 300)  # +5 min de marge pour le flusher

    # Always update context so digest reflects the latest monitor info
    ctx_data = {
        "channel_ids": [str(c.id) for c in rule.channels],
        "ctx": ctx,
    }
    ctx_payload = json.dumps(ctx_data)
    await redis.setex(ctx_key, ttl + 300, ctx_payload)

    if count == 1:
        # Premier événement : flush au prochain bucket arrondi (fenêtre glissante)
        now_ts = datetime.now(UTC).timestamp()
        flush_at_ts = (int(now_ts) // ttl + 1) * ttl
        await redis.zadd(schedule_key, {rule_id_str: flush_at_ts})

        logger.info(
            "digest_scheduled",
            rule_id=rule_id_str,
            digest_minutes=rule.digest_minutes,
        )
    # count > 1 → la fenêtre est déjà ouverte, accumuler sans reprogrammer

    # Dual-write to DB for persistence across Redis restarts
    await _upsert_digest_window(db, rule.id, event_data, ctx_data, ttl)


async def _upsert_digest_window(
    db: AsyncSession,
    rule_id: uuid.UUID,
    event_data: dict,
    ctx_data: dict,
    ttl: int,
) -> None:
    """Persist digest window to DB for recovery if Redis is lost."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from whatisup.core.database import dialect_name
    from whatisup.models.digest_window import DigestWindow

    now = datetime.now(UTC)
    flush_at = datetime.fromtimestamp((int(now.timestamp()) // ttl + 1) * ttl, tz=UTC)

    if dialect_name(db) == "postgresql":
        stmt = (
            pg_insert(DigestWindow)
            .values(
                id=uuid.uuid4(),
                rule_id=rule_id,
                flush_at=flush_at,
                events_json=[event_data],
                ctx_json=ctx_data,
                created_at=now,
            )
            .on_conflict_do_update(
                index_elements=["rule_id"],
                set_={
                    "events_json": DigestWindow.events_json.op("||")(json.dumps([event_data])),
                    "ctx_json": ctx_data,
                },
            )
        )
        await db.execute(stmt)
    else:
        # SQLite fallback — no JSONB `||` operator, so append in Python.
        existing = (
            await db.execute(select(DigestWindow).where(DigestWindow.rule_id == rule_id))
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                DigestWindow(
                    id=uuid.uuid4(),
                    rule_id=rule_id,
                    flush_at=flush_at,
                    events_json=[event_data],
                    ctx_json=ctx_data,
                    created_at=now,
                )
            )
        else:
            existing.events_json = [*(existing.events_json or []), event_data]
            existing.ctx_json = ctx_data


async def recover_digest_windows() -> None:
    """On startup, flush any stale DB-persisted digest windows missed during downtime."""
    from whatisup.core.database import get_session_factory
    from whatisup.core.redis import get_redis
    from whatisup.models.alert import AlertChannel as AC
    from whatisup.models.digest_window import DigestWindow

    redis = get_redis()
    now = datetime.now(UTC)

    async with get_session_factory()() as db:
        stale_windows = (
            (await db.execute(select(DigestWindow).where(DigestWindow.flush_at <= now)))
            .scalars()
            .all()
        )

        for window in stale_windows:
            # Check if Redis already has events for this rule (server might still be running)
            events_key = f"whatisup:digest:{window.rule_id}"
            redis_count = await redis.llen(events_key)
            if redis_count > 0:
                # Redis has data — delete stale DB row, Redis flusher will handle it
                await db.delete(window)
                continue

            # Redis lost data — recover from DB
            ctx_data = window.ctx_json or {}
            channel_ids = [uuid.UUID(cid) for cid in ctx_data.get("channel_ids", [])]
            if channel_ids and window.events_json:
                channels = (
                    (await db.execute(select(AC).where(AC.id.in_(channel_ids)))).scalars().all()
                )
                if channels:
                    logger.info(
                        "digest_recovered_from_db",
                        rule_id=str(window.rule_id),
                        event_count=len(window.events_json),
                    )
                    await _flush_digest(
                        str(window.rule_id), list(channels), ctx_data.get("ctx", {})
                    )

            await db.delete(window)

        await db.commit()


async def _is_silenced(
    db: AsyncSession,
    incident: Incident,
    channel: AlertChannel,
) -> bool:
    """Return True if any active AlertSilence covers this incident's monitor.

    A silence matches when:
      - it is currently within its [starts_at, ends_at] window, AND
      - it belongs to the channel owner, AND
      - its monitor_id is None (catch-all) OR matches incident.monitor_id.

    Channel.owner_id is the right scope (not incident.monitor.owner_id) because
    silences are an on-call ergonomic — the user who owns the destination wants
    quiet, even if the monitor itself is shared.
    """
    from whatisup.models.silence import AlertSilence

    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(AlertSilence.id)
            .where(
                AlertSilence.owner_id == channel.owner_id,
                AlertSilence.starts_at <= now,
                AlertSilence.ends_at > now,
                or_(
                    AlertSilence.monitor_id.is_(None),
                    AlertSilence.monitor_id == incident.monitor_id,
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


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
    # T1-01: silenced incidents short-circuit before any external send.
    if await _is_silenced(db, incident, channel):
        logger.info(
            "alert_silenced",
            incident_id=str(incident.id),
            channel_id=str(channel.id),
        )
        return

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

    dispatch_start = time.perf_counter()
    try:
        from whatisup.services.channels import CHANNEL_REGISTRY

        handler = CHANNEL_REGISTRY.get(channel.type.value)
        if handler is None:
            logger.error(
                "alert_handler_not_found",
                channel_id=str(channel.id),
                channel_type=channel.type.value,
            )
            status = AlertEventStatus.failed
            response_body = f"No handler for channel type: {channel.type.value}"
        else:
            response_body = await handler.send(
                incident, channel, event_type, ctx, decrypted_config, settings
            )
    except Exception as exc:
        logger.error(
            "alert_dispatch_failed",
            channel_id=str(channel.id),
            channel_type=channel.type.value,
            error=redact_secrets(str(exc), decrypted_config),
        )
        status = AlertEventStatus.failed
        response_body = type(exc).__name__
    observe_alert_dispatch(
        channel.type.value,
        time.perf_counter() - dispatch_start,
        success=status == AlertEventStatus.sent,
    )

    event = AlertEvent(
        incident_id=incident.id,
        channel_id=channel.id,
        sent_at=now,
        status=status,
        response_body=response_body,
    )
    db.add(event)
