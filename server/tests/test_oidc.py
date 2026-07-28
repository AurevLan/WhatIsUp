"""Tests for OIDC auth endpoints (disabled paths + callback session parity)."""

from __future__ import annotations

import hashlib
import json

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.api.v1.auth as auth_module
from whatisup.models.user import User

# ── oidc/config ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_config_when_disabled(client: AsyncClient) -> None:
    """GET /oidc/config returns enabled=false when no OIDC env vars are set."""
    resp = await client.get("/api/v1/auth/oidc/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert data["enabled"] is False


# ── oidc/login ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_login_when_disabled(client: AsyncClient) -> None:
    """GET /oidc/login returns 404 when OIDC is not enabled."""
    resp = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 404
    assert "not enabled" in resp.json()["detail"].lower()


# ── oidc/callback ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_callback_invalid_state_when_disabled(client: AsyncClient) -> None:
    """GET /oidc/callback returns 404 when OIDC is not enabled (checked before state)."""
    resp = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "fake_code", "state": "bad_state"},
        follow_redirects=False,
    )
    # OIDC is disabled → endpoint raises 404 before even validating state
    assert resp.status_code == 404
    assert "not enabled" in resp.json()["detail"].lower()


# ── oidc/callback — session metadata parity with classic login ───────────────


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeHttpxClient:
    """Stands in for httpx.AsyncClient inside oidc_callback (token + userinfo).

    ``userinfo_overrides`` lets a test tweak the claims the fake IdP returns
    (e.g. drop ``email_verified``).
    """

    userinfo_overrides: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> _FakeHttpxClient:
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, **kwargs) -> _FakeResponse:
        return _FakeResponse({"access_token": "provider-access-token"})

    async def get(self, url, **kwargs) -> _FakeResponse:
        return _FakeResponse(
            {
                "sub": "oidc-sub-123",
                "email": "sso.user@test.com",
                "email_verified": True,
                "preferred_username": "sso_user",
                "name": "SSO User",
                **self.userinfo_overrides,
            }
        )


@pytest.mark.asyncio
async def test_oidc_callback_stores_session_metadata(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful OIDC callback must store the refresh session with the same
    UA/IP/created_at metadata as the classic login flow (active-sessions UI)."""

    async def _fake_settings(db) -> dict:
        return {
            "enabled": True,
            "issuer_url": "https://idp.example.com",
            "client_id": "whatisup",
            "client_secret": "secret",
            "redirect_uri": None,
            "scopes": "openid email profile",
            "auto_provision": True,
        }

    async def _fake_discover(issuer: str) -> dict:
        return {
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }

    monkeypatch.setattr(auth_module, "_resolve_oidc_settings", _fake_settings)
    monkeypatch.setattr(auth_module, "_oidc_discover", _fake_discover)
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _FakeHttpxClient)

    # Seed the PKCE state exactly as /oidc/login would (verifier + nonce
    # fingerprint — the browser binding added by S7, see
    # test_security_oidc_handoff.py)
    nonce = "nonce-session-parity"
    await fake_redis.setex(
        "whatisup:oidc:state:teststate",
        300,
        json.dumps(
            {"verifier": "verifier123", "nonce": hashlib.sha256(nonce.encode()).hexdigest()}
        ),
    )

    resp = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "authcode", "state": "teststate"},
        headers={"User-Agent": "OIDC-Device", "Cookie": f"wiu_oidc_nonce={nonce}"},
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    # Tokens are minted at the exchange, so that is where the session metadata
    # is recorded — the callback only hands back a one-time code.
    code = resp.headers["location"].split("#code=")[1]
    exchange = await client.post(
        "/api/v1/auth/oidc/exchange",
        json={"code": code},
        headers={"User-Agent": "OIDC-Device", "Cookie": f"wiu_oidc_nonce={nonce}"},
    )
    assert exchange.status_code == 200, exchange.text
    refresh_token = exchange.json()["refresh_token"]

    user = (
        await db_session.execute(select(User).where(User.oidc_sub == "oidc-sub-123"))
    ).scalar_one()

    # Session stored under the same key scheme as store_refresh_session…
    _rh = hashlib.sha256(refresh_token.encode()).hexdigest()[:32]
    raw = await fake_redis.get(f"whatisup:refresh:{user.id}:{_rh}")
    assert raw is not None
    # …and carries JSON metadata (not the legacy bare "1")
    meta = json.loads(raw)
    assert meta["ua"] == "OIDC-Device"
    assert meta["created_at"]
    assert "ip" in meta


# ── F16 — email_verified gate on identity binding ────────────────────────────


async def _fake_oidc_settings(db) -> dict:
    return {
        "enabled": True,
        "issuer_url": "https://idp.example.com",
        "client_id": "whatisup",
        "client_secret": "secret",
        "redirect_uri": None,
        "scopes": "openid email profile",
        "auto_provision": True,
    }


async def _fake_oidc_discover(issuer: str) -> dict:
    return {
        "authorization_endpoint": "https://idp.example.com/authorize",
        "token_endpoint": "https://idp.example.com/token",
        "userinfo_endpoint": "https://idp.example.com/userinfo",
    }


async def _run_callback(
    client: AsyncClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    userinfo_overrides: dict,
    state: str = "f16state",
):
    monkeypatch.setattr(auth_module, "_resolve_oidc_settings", _fake_oidc_settings)
    monkeypatch.setattr(auth_module, "_oidc_discover", _fake_oidc_discover)
    monkeypatch.setattr(_FakeHttpxClient, "userinfo_overrides", userinfo_overrides)
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _FakeHttpxClient)
    await fake_redis.setex(f"whatisup:oidc:state:{state}", 300, "verifier123")
    return await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "authcode", "state": state},
        follow_redirects=False,
    )


@pytest.mark.asyncio
async def test_oidc_callback_refuses_unverified_email(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An IdP that does not assert email_verified must not bind an identity.

    Otherwise an attacker who signs up at the IdP with the victim's address
    takes over the victim's local account (audit F16).
    """
    victim = User(
        email="sso.user@test.com",
        username="victim_local",
        hashed_password="x",
    )
    db_session.add(victim)
    await db_session.commit()

    resp = await _run_callback(
        client, fake_redis, monkeypatch, {"email_verified": False}, state="f16-false"
    )
    assert resp.status_code == 302
    assert "error=email_not_verified" in resp.headers["location"]
    assert "access_token" not in resp.headers["location"]

    await db_session.refresh(victim)
    assert victim.oidc_sub is None  # no identity was bound to the local account


@pytest.mark.asyncio
async def test_oidc_callback_refuses_missing_email_verified_claim(
    client: AsyncClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    """A missing email_verified claim is treated as unverified (fail closed)."""
    resp = await _run_callback(
        client,
        fake_redis,
        monkeypatch,
        {"email_verified": None},
        state="f16-missing",
    )
    assert resp.status_code == 302
    assert "error=email_not_verified" in resp.headers["location"]

    user = (
        await db_session.execute(select(User).where(User.email == "sso.user@test.com"))
    ).scalar_one_or_none()
    assert user is None  # auto-provisioning did not run either


@pytest.mark.asyncio
async def test_oidc_callback_accepts_string_true_email_verified(
    client: AsyncClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    """Providers that serialise email_verified as the string "true" still work."""
    resp = await _run_callback(
        client, fake_redis, monkeypatch, {"email_verified": "true"}, state="f16-str"
    )
    assert resp.status_code == 302
    assert "#access_token=" in resp.headers["location"]

    user = (
        await db_session.execute(select(User).where(User.oidc_sub == "oidc-sub-123"))
    ).scalar_one()
    assert user.email == "sso.user@test.com"
