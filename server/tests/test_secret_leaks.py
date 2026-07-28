"""F6 / F18 — credentials must not leak into logs, API errors or the database.

F6: the Telegram bot_token rides in the Bot API URL path, and httpx puts the
request URL in HTTPStatusError, so an ordinary 401/429 wrote the plaintext
token into the server logs and into the /test endpoint's response.

F18: custom_headers is documented as the place to put an Authorization header,
yet it was the only secret category still persisted verbatim.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.security import (
    decrypt_custom_headers,
    encrypt_custom_headers,
)
from whatisup.models.monitor import Monitor
from whatisup.services.channels._helpers import redact_secrets

BOT_TOKEN = "123456789:AAFakeTokenForTestsOnly_notReal"  # noqa: S105 — dummy


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fernet_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "fernet_key", key)
    return key


# ── F6 — secrets scrubbed from error strings ──────────────────────────────────


def test_redact_secrets_blanks_a_token_lifted_from_a_url() -> None:
    config = {"bot_token": BOT_TOKEN, "chat_id": "42"}
    raw = (
        "Client error '401 Unauthorized' for url "
        f"'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'"
    )
    scrubbed = redact_secrets(raw, config)
    assert BOT_TOKEN not in scrubbed
    assert "***" in scrubbed
    assert "401 Unauthorized" in scrubbed  # the useful part survives


def test_redact_secrets_covers_every_secret_config_key() -> None:
    config = {
        "secret": "hmac-shared-secret-value",
        "api_key": "opsgenie-api-key-value",
        "integration_key": "pagerduty-integration-key",
        "password": "smtp-password-value",
        "webhook_url": "https://hooks.slack.com/services/T000/B000/XXXXtokenXXXX",
        "chat_id": "not-a-secret",
    }
    text = " ".join(config.values())
    scrubbed = redact_secrets(text, config)
    for key, value in config.items():
        if key == "chat_id":
            assert value in scrubbed
        else:
            assert value not in scrubbed


def test_redact_secrets_leaves_short_values_alone() -> None:
    """A 3-char 'secret' would blank unrelated substrings everywhere."""
    assert redact_secrets("error at pos 42", {"secret": "42"}) == "error at pos 42"


def test_redact_secrets_tolerates_missing_config() -> None:
    assert redact_secrets("boom", None) == "boom"
    assert redact_secrets("", {"secret": "x" * 20}) == ""


@pytest.mark.asyncio
async def test_telegram_send_error_never_carries_the_token(monkeypatch) -> None:
    """The channel raises on the status code alone — no URL, no token."""
    import httpx

    from whatisup.services.channels.telegram import _post

    class _Resp:
        status_code = 401

    class _Client:
        def __init__(self, *a, **kw) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def post(self, url, **kwargs) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    with pytest.raises(RuntimeError) as excinfo:
        await _post({"bot_token": BOT_TOKEN, "chat_id": "1"}, {"text": "x"})

    assert BOT_TOKEN not in str(excinfo.value)
    assert "401" in str(excinfo.value)


# ── F18 — custom_headers encrypted at rest ────────────────────────────────────


def test_encrypt_custom_headers_roundtrip(fernet_key: str) -> None:
    headers = {"Authorization": "Bearer prod-token", "X-Trace-Id": "abc123"}
    encrypted = encrypt_custom_headers(headers)
    assert encrypted["Authorization"] != "Bearer prod-token"
    assert set(encrypted) == set(headers)  # header names stay in the clear
    assert decrypt_custom_headers(encrypted) == headers


def test_decrypt_custom_headers_falls_back_to_legacy_plaintext(fernet_key: str) -> None:
    """Rows written before encryption existed must keep working — no migration."""
    assert decrypt_custom_headers({"Authorization": "Bearer legacy"}) == {
        "Authorization": "Bearer legacy"
    }


def test_encrypt_custom_headers_noop_without_fernet_key(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "fernet_key", "")
    headers = {"Authorization": "Bearer x"}
    assert encrypt_custom_headers(headers) == headers


@pytest.mark.asyncio
async def test_created_monitor_stores_headers_encrypted(
    client: AsyncClient, user_token: str, db_session: AsyncSession, fernet_key: str
) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Protected",
            "url": "https://api.example.com",
            "custom_headers": {"Authorization": "Bearer prod-token"},
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text
    # The owner still reads the real value back — the edit form re-submits it.
    assert resp.json()["custom_headers"]["Authorization"] == "Bearer prod-token"

    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.name == "Protected"))
    ).scalar_one()
    assert monitor.custom_headers["Authorization"] != "Bearer prod-token"
    assert decrypt_custom_headers(monitor.custom_headers) == {
        "Authorization": "Bearer prod-token"
    }


@pytest.mark.asyncio
async def test_updated_monitor_stores_headers_encrypted(
    client: AsyncClient, user_token: str, db_session: AsyncSession, fernet_key: str
) -> None:
    created = await client.post(
        "/api/v1/monitors/",
        json={"name": "ToProtect", "url": "https://api.example.com"},
        headers=_auth(user_token),
    )
    monitor_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"custom_headers": {"Authorization": "Bearer rotated"}},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_headers"]["Authorization"] == "Bearer rotated"

    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.name == "ToProtect"))
    ).scalar_one()
    assert monitor.custom_headers["Authorization"] != "Bearer rotated"


@pytest.mark.asyncio
async def test_imported_monitor_stores_headers_encrypted(
    client: AsyncClient, user_token: str, db_session: AsyncSession, fernet_key: str
) -> None:
    resp = await client.post(
        "/api/v1/monitors/import",
        json=[
            {
                "name": "Imported",
                "url": "https://api.example.com",
                "custom_headers": {"Authorization": "Bearer imported-token"},
            }
        ],
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1

    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.name == "Imported"))
    ).scalar_one()
    assert monitor.custom_headers["Authorization"] != "Bearer imported-token"


@pytest.mark.asyncio
async def test_edit_roundtrip_preserves_headers(
    client: AsyncClient, user_token: str, db_session: AsyncSession, fernet_key: str
) -> None:
    """Read back, re-submit unchanged, read again — the value must survive.

    This is why custom_headers are decrypted rather than masked in MonitorOut:
    the edit form does exactly this on every save.
    """
    created = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Roundtrip",
            "url": "https://api.example.com",
            "custom_headers": {"Authorization": "Bearer keep-me"},
        },
        headers=_auth(user_token),
    )
    monitor_id = created.json()["id"]
    read_back = created.json()["custom_headers"]

    resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"custom_headers": read_back, "name": "Roundtrip renamed"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_headers"]["Authorization"] == "Bearer keep-me"


@pytest.mark.asyncio
async def test_probe_config_receives_decrypted_headers(
    client: AsyncClient, user_token: str, db_session: AsyncSession, fernet_key: str
) -> None:
    """The probe must get a usable header, not ciphertext."""
    from whatisup.core.security import decrypt_custom_headers as _decrypt

    await client.post(
        "/api/v1/monitors/",
        json={
            "name": "ForProbe",
            "url": "https://api.example.com",
            "custom_headers": {"Authorization": "Bearer probe-token"},
        },
        headers=_auth(user_token),
    )
    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.name == "ForProbe"))
    ).scalar_one()
    assert _decrypt(monitor.custom_headers)["Authorization"] == "Bearer probe-token"
