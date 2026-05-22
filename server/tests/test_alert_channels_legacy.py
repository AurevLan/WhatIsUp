"""Coverage for slack/telegram/webhook/pagerduty/opsgenie/signal channels.

Mirrors the discord/mattermost/teams test pattern: patches
``httpx.AsyncClient.post`` and ``validate_webhook_url`` so the suite exercises
the real send/test code paths without leaving the test host.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from whatisup.models.incident import IncidentScope
from whatisup.services.channels.opsgenie import OpsgenieChannel
from whatisup.services.channels.pagerduty import PagerDutyChannel
from whatisup.services.channels.signal import SignalChannel
from whatisup.services.channels.slack import SlackChannel
from whatisup.services.channels.telegram import TelegramChannel
from whatisup.services.channels.webhook import WebhookChannel


class _Resp:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self) -> None:  # noqa: D401
        return None


@pytest.fixture
def fake_incident():
    return SimpleNamespace(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        monitor_id=uuid.UUID("87654321-4321-8765-4321-876543218765"),
        started_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        resolved_at=None,
        duration_seconds=None,
        affected_probe_ids=[],
        scope=IncidentScope.global_,
    )


@pytest.fixture
def resolved_incident(fake_incident):
    fake_incident.resolved_at = datetime(2026, 5, 3, 12, 7, 0, tzinfo=UTC)
    fake_incident.duration_seconds = 420
    return fake_incident


@pytest.fixture
def ctx():
    return {"monitor_name": "korben.info", "check_type": "http", "probe_names": {}}


@pytest.fixture
def patch_http(monkeypatch):
    """Capture httpx.AsyncClient.post calls + stub validate_webhook_url."""
    captured: dict = {"calls": []}

    async def _fake_post(self, url, json=None, content=None, headers=None, **_kw):
        captured["calls"].append({"url": url, "json": json, "content": content, "headers": headers})
        return _Resp(200)

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
    for mod in (
        "whatisup.services.channels.webhook",
        "whatisup.services.channels.slack",
        "whatisup.services.channels.signal",
    ):
        monkeypatch.setattr(f"{mod}.validate_webhook_url", AsyncMock(return_value=None))
    return captured


# ── Slack ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slack_test_posts_attachment(patch_http) -> None:
    ok, msg = await SlackChannel().test({"webhook_url": "https://hooks.slack/x"}, None)
    assert ok is True and "HTTP 200" in msg
    payload = patch_http["calls"][0]["json"]
    assert payload["attachments"][0]["title"].startswith("WhatIsUp")


@pytest.mark.asyncio
async def test_slack_send_red_for_alert(patch_http, fake_incident, ctx) -> None:
    await SlackChannel().send(
        fake_incident, None, "incident_opened", ctx, {"webhook_url": "https://h/x"}, None
    )
    att = patch_http["calls"][0]["json"]["attachments"][0]
    assert att["color"] == "#dc3545"
    assert "ALERT" in att["title"]


@pytest.mark.asyncio
async def test_slack_send_resolved_shows_duration(patch_http, resolved_incident, ctx) -> None:
    await SlackChannel().send(
        resolved_incident, None, "incident_resolved", ctx, {"webhook_url": "https://h/x"}, None
    )
    fields = {
        f["title"]: f["value"] for f in patch_http["calls"][0]["json"]["attachments"][0]["fields"]
    }
    assert "Duration" in fields
    assert "420s" in fields["Duration"]


# ── Telegram ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_test_posts_html(patch_http) -> None:
    ok, msg = await TelegramChannel().test({"bot_token": "12345:abc", "chat_id": "100"}, None)
    assert ok and "HTTP 200" in msg
    payload = patch_http["calls"][0]["json"]
    assert payload["parse_mode"] == "HTML"
    assert "WhatIsUp" in payload["text"]


@pytest.mark.asyncio
async def test_telegram_send_includes_monitor_name(patch_http, fake_incident, ctx) -> None:
    await TelegramChannel().send(
        fake_incident, None, "incident_opened", ctx, {"bot_token": "x:y", "chat_id": "1"}, None
    )
    text = patch_http["calls"][0]["json"]["text"]
    assert "korben.info" in text
    assert "HTTP" in text  # check_type uppercased


@pytest.mark.asyncio
async def test_telegram_send_resolved_includes_duration(patch_http, resolved_incident, ctx) -> None:
    await TelegramChannel().send(
        resolved_incident,
        None,
        "incident_resolved",
        ctx,
        {"bot_token": "x:y", "chat_id": "1"},
        None,
    )
    text = patch_http["calls"][0]["json"]["text"]
    assert "Résolu" in text
    assert "420s" in text


# ── Webhook ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_test_signs_when_secret_present(patch_http) -> None:
    ok, _ = await WebhookChannel().test({"url": "https://hook.example", "secret": "shared"}, None)
    assert ok is True
    headers = patch_http["calls"][0]["headers"]
    assert "X-WhatIsUp-Signature" in headers
    assert headers["X-WhatIsUp-Signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_webhook_send_emits_json_payload(patch_http, fake_incident, ctx) -> None:
    await WebhookChannel().send(
        fake_incident,
        SimpleNamespace(webhook_template=None),
        "incident_opened",
        ctx,
        {"url": "https://hook"},
        None,
    )
    call = patch_http["calls"][0]
    assert call["headers"]["Content-Type"] == "application/json"
    body = json.loads(call["content"])
    assert body["monitor_name"] == "korben.info"
    assert body["event_type"] == "incident.opened"
    assert body["scope"] == "global"


@pytest.mark.asyncio
async def test_webhook_send_with_template_uses_text_plain(patch_http, fake_incident, ctx) -> None:
    channel = SimpleNamespace(webhook_template="Monitor $monitor_name is $status")
    await WebhookChannel().send(
        fake_incident, channel, "incident_opened", ctx, {"url": "https://hook"}, None
    )
    call = patch_http["calls"][0]
    assert call["headers"]["Content-Type"] == "text/plain"
    assert call["content"].decode() == "Monitor korben.info is down"


@pytest.mark.asyncio
async def test_webhook_send_with_json_template_uses_application_json(
    patch_http, fake_incident, ctx
) -> None:
    channel = SimpleNamespace(webhook_template='{"name":"$monitor_name"}')
    await WebhookChannel().send(
        fake_incident, channel, "incident_opened", ctx, {"url": "https://hook"}, None
    )
    assert patch_http["calls"][0]["headers"]["Content-Type"] == "application/json"


# ── PagerDuty ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pagerduty_test_skipped_non_production() -> None:
    settings = SimpleNamespace(is_production=False)
    ok, msg = await PagerDutyChannel().test({"integration_key": "k"}, settings)
    assert ok is True
    assert "skipped:non_production" in msg


@pytest.mark.asyncio
async def test_pagerduty_test_posts_in_production(patch_http) -> None:
    settings = SimpleNamespace(is_production=True)
    ok, msg = await PagerDutyChannel().test({"integration_key": "k"}, settings)
    assert ok is True and "HTTP 200" in msg
    payload = patch_http["calls"][0]["json"]
    assert payload["routing_key"] == "k"
    assert payload["event_action"] == "trigger"


@pytest.mark.asyncio
async def test_pagerduty_send_skipped_non_production(patch_http, fake_incident, ctx) -> None:
    settings = SimpleNamespace(is_production=False)
    result = await PagerDutyChannel().send(
        fake_incident, None, "incident_opened", ctx, {"integration_key": "k"}, settings
    )
    assert result == "skipped:non_production"
    assert patch_http["calls"] == []


@pytest.mark.asyncio
async def test_pagerduty_send_resolved_emits_resolve_action(
    patch_http, resolved_incident, ctx
) -> None:
    settings = SimpleNamespace(is_production=True)
    await PagerDutyChannel().send(
        resolved_incident, None, "incident_resolved", ctx, {"integration_key": "k"}, settings
    )
    assert patch_http["calls"][0]["json"]["event_action"] == "resolve"


# ── Opsgenie ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_opsgenie_test_skipped_non_production() -> None:
    settings = SimpleNamespace(is_production=False)
    ok, msg = await OpsgenieChannel().test({"api_key": "x"}, settings)
    assert ok is True
    assert "skipped" in msg


@pytest.mark.asyncio
async def test_opsgenie_test_us_region(patch_http) -> None:
    settings = SimpleNamespace(is_production=True)
    await OpsgenieChannel().test({"api_key": "x", "region": "us"}, settings)
    assert "api.opsgenie.com" in patch_http["calls"][0]["url"]


@pytest.mark.asyncio
async def test_opsgenie_test_eu_region(patch_http) -> None:
    settings = SimpleNamespace(is_production=True)
    await OpsgenieChannel().test({"api_key": "x", "region": "eu"}, settings)
    assert "api.eu.opsgenie.com" in patch_http["calls"][0]["url"]


@pytest.mark.asyncio
async def test_opsgenie_send_resolved_closes_alert(patch_http, resolved_incident, ctx) -> None:
    settings = SimpleNamespace(is_production=True)
    await OpsgenieChannel().send(
        resolved_incident, None, "incident_resolved", ctx, {"api_key": "x"}, settings
    )
    url = patch_http["calls"][0]["url"]
    assert url.endswith(f"/whatisup-{resolved_incident.id}/close")


@pytest.mark.asyncio
async def test_opsgenie_send_skipped_non_production(patch_http, fake_incident, ctx) -> None:
    settings = SimpleNamespace(is_production=False)
    result = await OpsgenieChannel().send(
        fake_incident, None, "incident_opened", ctx, {"api_key": "x"}, settings
    )
    assert result == "skipped:non_production"


@pytest.mark.asyncio
async def test_opsgenie_send_creates_alert(patch_http, fake_incident, ctx) -> None:
    settings = SimpleNamespace(is_production=True)
    await OpsgenieChannel().send(
        fake_incident, None, "incident_opened", ctx, {"api_key": "x"}, settings
    )
    payload = patch_http["calls"][0]["json"]
    assert payload["alias"] == f"whatisup-{fake_incident.id}"


# ── Signal ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signal_test_posts_to_v2_send(patch_http) -> None:
    ok, _ = await SignalChannel().test(
        {
            "api_url": "https://signal.api/",
            "sender_number": "+1234",
            "recipients": ["+5678"],
        },
        None,
    )
    assert ok is True
    call = patch_http["calls"][0]
    assert call["url"].endswith("/v2/send")
    assert call["json"]["number"] == "+1234"


@pytest.mark.asyncio
async def test_signal_send_includes_duration_when_resolved(
    patch_http, resolved_incident, ctx
) -> None:
    await SignalChannel().send(
        resolved_incident,
        None,
        "incident_resolved",
        ctx,
        {"api_url": "https://signal", "sender_number": "+1", "recipients": ["+2"]},
        None,
    )
    msg = patch_http["calls"][0]["json"]["message"]
    assert "Résolu" in msg
    assert "420s" in msg
