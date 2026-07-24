"""F4 / F13 / F14 — the client IP must not be forgeable through X-Forwarded-For.

The API used to run ProxyHeadersMiddleware with ``trusted_hosts="*"``, which
makes uvicorn take the *leftmost* X-Forwarded-For entry — the one the client
itself put there. Every per-IP rate limit (the login throttle included) and
every audit-log source IP was therefore forgeable by rotating a header. The
bundled nginx made it worse by *appending* to the header instead of
overwriting it, so the attacker's value stayed leftmost.

Two halves, tested here: the backend now trusts a restricted list and resolves
the last untrusted hop, and the shipped nginx config overwrites the header at
the trust boundary.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import whatisup.services.lockout as lockout
from whatisup.core.config import Settings, get_settings
from whatisup.models.audit_log import AuditLog
from whatisup.models.user import User

NGINX_CONF = Path(__file__).resolve().parents[2] / "nginx" / "whatisup.conf"


def _nginx_directives() -> str:
    """The conf with comment lines stripped — they discuss the banned directive."""
    return "\n".join(
        line for line in NGINX_CONF.read_text().splitlines() if not line.strip().startswith("#")
    )


# ── Settings ──────────────────────────────────────────────────────────────────


def test_default_trusted_list_covers_private_ranges() -> None:
    """The default must let the bundled docker-compose stack work as shipped."""
    hosts = Settings(secret_key="x" * 32).trusted_proxy_list
    assert "127.0.0.1" in hosts
    assert "172.16.0.0/12" in hosts
    assert hosts != ["*"]


def test_trusted_list_parsing_ignores_blanks() -> None:
    settings = Settings(secret_key="x" * 32, trusted_proxy_ips=" 10.0.0.1 , ,10.1.0.0/16, ")
    assert settings.trusted_proxy_list == ["10.0.0.1", "10.1.0.0/16"]


def test_empty_trusted_list_trusts_nobody() -> None:
    settings = Settings(secret_key="x" * 32, trusted_proxy_ips="")
    assert settings.trusted_proxy_list == []


def test_wildcard_trust_refused_in_production() -> None:
    """'*' is the old always-trust behaviour — it must not ship to production."""
    with pytest.raises(ValueError, match="TRUSTED_PROXY_IPS"):
        Settings(
            secret_key="x" * 32,
            environment="production",
            cors_allowed_origins=["https://app.example.com"],
            fernet_key=Fernet.generate_key().decode(),
            trusted_proxy_ips="*",
        )


def test_wildcard_trust_allowed_outside_production() -> None:
    """Kept as an escape hatch for dev/debug setups."""
    assert Settings(secret_key="x" * 32, trusted_proxy_ips="*").trusted_proxy_list == ["*"]


# ── Middleware resolution ─────────────────────────────────────────────────────


async def _echo_client_app(scope, receive, send) -> None:
    """Minimal ASGI app that returns whatever scope['client'] ended up as."""
    host = scope["client"][0] if scope.get("client") else ""
    body = host.encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _resolved_client(peer: str, forwarded_for: str | None) -> str:
    app = ProxyHeadersMiddleware(_echo_client_app, trusted_hosts=get_settings().trusted_proxy_list)
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    transport = ASGITransport(app=app, client=(peer, 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return (await ac.get("/", headers=headers)).text


@pytest.mark.asyncio
async def test_spoofed_leftmost_entry_is_ignored() -> None:
    """A proxy that appends leaves the attacker's value leftmost — ignore it."""
    resolved = await _resolved_client("172.18.0.4", "9.9.9.9, 203.0.113.7")
    assert resolved == "203.0.113.7"


@pytest.mark.asyncio
async def test_overwritten_header_yields_the_real_client() -> None:
    """What the fixed nginx sends: a single entry, the actual peer."""
    assert await _resolved_client("172.18.0.4", "203.0.113.7") == "203.0.113.7"


@pytest.mark.asyncio
async def test_forwarded_header_from_untrusted_peer_is_ignored() -> None:
    """Reaching the API directly means the header carries no authority at all."""
    assert await _resolved_client("203.0.113.9", "9.9.9.9") == "203.0.113.9"


@pytest.mark.asyncio
async def test_chain_of_spoofed_entries_cannot_hide_the_client() -> None:
    """Padding the header with fake hops does not push the real client out."""
    resolved = await _resolved_client("172.18.0.4", "9.9.9.9, 8.8.8.8, 203.0.113.7")
    assert resolved == "203.0.113.7"


@pytest.mark.asyncio
async def test_app_does_not_always_trust() -> None:
    """Guard against someone restoring trusted_hosts='*' on the real app."""
    from whatisup.main import app

    middleware = ProxyHeadersMiddleware(
        _echo_client_app, trusted_hosts=get_settings().trusted_proxy_list
    )
    assert middleware.trusted_hosts.always_trust is False
    assert any(m.cls is ProxyHeadersMiddleware for m in app.user_middleware)


# ── End to end: the audit log records the real client ─────────────────────────


@pytest.mark.asyncio
async def test_lockout_audit_records_real_ip_not_spoofed_one(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    admin_user: User,
) -> None:
    """Login lockout must be attributed to the appended hop, not the client's claim."""
    headers = {"X-Forwarded-For": "9.9.9.9, 203.0.113.7"}
    for _ in range(lockout.LOCKOUT_THRESHOLD):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": admin_user.email, "password": "WrongPassword9!"},
            headers=headers,
        )
        assert resp.status_code == 401

    entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "user.login_lockout"))
    ).scalar_one()
    assert entry.ip_address == "203.0.113.7"


# ── nginx: the trust boundary must overwrite, not append ──────────────────────


def test_nginx_never_appends_forwarded_for() -> None:
    assert "$proxy_add_x_forwarded_for" not in _nginx_directives(), (
        "nginx must overwrite X-Forwarded-For with $remote_addr at the trust "
        "boundary — appending keeps the client-supplied value in the chain"
    )


def test_nginx_sets_forwarded_headers_on_api_and_ws() -> None:
    """Without an explicit proxy_set_header, nginx forwards the client's own."""
    conf = _nginx_directives()
    for location in ("location /api/", "location /ws/"):
        start = conf.index(location)
        block = conf[start : conf.index("}", start)]
        assert "proxy_set_header X-Forwarded-For $remote_addr;" in block, location
        assert "proxy_set_header X-Forwarded-Proto $scheme;" in block, location
