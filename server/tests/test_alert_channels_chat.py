"""Tests for Discord, Mattermost, and Teams alert channels."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from whatisup.services.channels.discord import _COLOR_GREEN, _COLOR_RED, DiscordChannel
from whatisup.services.channels.mattermost import MattermostChannel
from whatisup.services.channels.teams import TeamsChannel


@pytest.fixture
def fake_incident():
    return SimpleNamespace(
        monitor_id="00000000-0000-0000-0000-000000000001",
        started_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        duration_seconds=420,
        affected_probe_ids=[],
        scope=None,
    )


@pytest.fixture
def ctx():
    return {"monitor_name": "korben.info", "check_type": "http", "probe_names": {}}


def _patch_http(monkeypatch, captured: dict, status_code: int = 204):
    """Patch httpx.AsyncClient.post + validate_webhook_url so no network IO occurs."""

    class _Resp:
        def __init__(self):
            self.status_code = status_code

        def raise_for_status(self) -> None:
            return None

    async def _fake_post(self, url, json=None, **_kw):
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
    monkeypatch.setattr(
        "whatisup.services.channels.discord.validate_webhook_url", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "whatisup.services.channels.mattermost.validate_webhook_url",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "whatisup.services.channels.teams.validate_webhook_url", AsyncMock(return_value=None)
    )


# ── Mock IncidentScope import in _helpers (used by scope_label_en) ────────────


@pytest.fixture(autouse=True)
def _patch_scope_global(monkeypatch):
    """Make scope comparison in _helpers fall through to the geographic branch."""
    # IncidentScope.global_ won't equal None so scope_label_en returns a geo string,
    # which is fine — we only check that send() succeeds and produces a payload.
    yield


# ── Discord ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discord_test_posts_embed(monkeypatch) -> None:
    captured: dict = {}
    _patch_http(monkeypatch, captured)
    ok, msg = await DiscordChannel().test({"webhook_url": "https://discord.example/hook"}, None)
    assert ok is True
    assert "HTTP 204" in msg
    assert captured["url"] == "https://discord.example/hook"
    assert "embeds" in captured["json"]
    assert captured["json"]["embeds"][0]["title"] == "WhatIsUp — Channel test"


@pytest.mark.asyncio
async def test_discord_send_red_for_alert(monkeypatch, fake_incident, ctx) -> None:
    captured: dict = {}
    _patch_http(monkeypatch, captured)
    await DiscordChannel().send(
        fake_incident, None, "incident_opened", ctx, {"webhook_url": "https://d.x/h"}, None
    )
    embed = captured["json"]["embeds"][0]
    assert embed["color"] == _COLOR_RED
    assert "ALERT" in embed["title"]
    field_names = {f["name"] for f in embed["fields"]}
    assert {"Monitor", "Type", "Scope", "Started"}.issubset(field_names)


@pytest.mark.asyncio
async def test_discord_send_green_for_resolved(monkeypatch, fake_incident, ctx) -> None:
    captured: dict = {}
    _patch_http(monkeypatch, captured)
    await DiscordChannel().send(
        fake_incident, None, "incident_resolved", ctx, {"webhook_url": "https://d.x/h"}, None
    )
    embed = captured["json"]["embeds"][0]
    assert embed["color"] == _COLOR_GREEN
    assert "RESOLVED" in embed["title"]
    duration_field = [f for f in embed["fields"] if f["name"] == "Duration"]
    assert duration_field and duration_field[0]["value"] == "420s"


# ── Mattermost ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mattermost_test_posts_text(monkeypatch) -> None:
    captured: dict = {}
    _patch_http(monkeypatch, captured)
    ok, _ = await MattermostChannel().test({"webhook_url": "https://mm.example/hook"}, None)
    assert ok is True
    assert captured["json"]["username"] == "WhatIsUp"
    assert "Channel test" in captured["json"]["text"]


@pytest.mark.asyncio
async def test_mattermost_send_attachment_color(monkeypatch, fake_incident, ctx) -> None:
    captured: dict = {}
    _patch_http(monkeypatch, captured)
    await MattermostChannel().send(
        fake_incident, None, "incident_opened", ctx, {"webhook_url": "https://mm/h"}, None
    )
    att = captured["json"]["attachments"][0]
    assert att["color"] == "#dc3545"
    assert "ALERT" in att["title"]


# ── Teams ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_teams_test_posts_adaptive_card(monkeypatch) -> None:
    captured: dict = {}
    _patch_http(monkeypatch, captured)
    ok, _ = await TeamsChannel().test({"webhook_url": "https://teams.example/hook"}, None)
    assert ok is True
    att = captured["json"]["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert att["content"]["type"] == "AdaptiveCard"


@pytest.mark.asyncio
async def test_teams_send_attention_for_alert(monkeypatch, fake_incident, ctx) -> None:
    captured: dict = {}
    _patch_http(monkeypatch, captured)
    await TeamsChannel().send(
        fake_incident, None, "incident_opened", ctx, {"webhook_url": "https://t/h"}, None
    )
    body = captured["json"]["attachments"][0]["content"]["body"]
    title_block = body[0]
    assert title_block["color"] == "attention"
    assert "ALERT" in title_block["text"]
    facts = body[1]["facts"]
    titles = {f["title"] for f in facts}
    assert {"Monitor", "Type", "Scope", "Started"}.issubset(titles)


@pytest.mark.asyncio
async def test_teams_send_good_for_resolved(monkeypatch, fake_incident, ctx) -> None:
    captured: dict = {}
    _patch_http(monkeypatch, captured)
    await TeamsChannel().send(
        fake_incident, None, "incident_resolved", ctx, {"webhook_url": "https://t/h"}, None
    )
    body = captured["json"]["attachments"][0]["content"]["body"]
    assert body[0]["color"] == "good"
    assert "RESOLVED" in body[0]["text"]
