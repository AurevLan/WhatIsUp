"""Per-channel-type config validators for Discord, Mattermost, Teams."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from whatisup.schemas.alert import AlertChannelCreate


def _payload(ctype: str, config: dict) -> dict:
    return {"name": f"my {ctype}", "type": ctype, "config": config}


def test_discord_accepts_official_webhook() -> None:
    AlertChannelCreate.model_validate(
        _payload("discord", {"webhook_url": "https://discord.com/api/webhooks/123/abc"})
    )


def test_discord_rejects_wrong_host() -> None:
    with pytest.raises(ValidationError):
        AlertChannelCreate.model_validate(
            _payload("discord", {"webhook_url": "https://example.com/hook"})
        )


def test_mattermost_accepts_self_hosted() -> None:
    AlertChannelCreate.model_validate(
        _payload("mattermost", {"webhook_url": "https://mattermost.example.com/hooks/abcdef"})
    )


def test_mattermost_rejects_non_http() -> None:
    with pytest.raises(ValidationError):
        AlertChannelCreate.model_validate(
            _payload("mattermost", {"webhook_url": "ftp://example.com/hook"})
        )


def test_teams_requires_https() -> None:
    AlertChannelCreate.model_validate(
        _payload(
            "teams",
            {
                "webhook_url": (
                    "https://prod-01.westus.logic.azure.com/workflows/abc/triggers/manual"
                )
            },
        )
    )


def test_teams_rejects_http() -> None:
    with pytest.raises(ValidationError):
        AlertChannelCreate.model_validate(
            _payload("teams", {"webhook_url": "http://example.com/hook"})
        )
