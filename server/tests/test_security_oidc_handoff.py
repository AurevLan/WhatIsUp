"""S7 / F11 — the OIDC login must be bound to the browser that started it.

Before this lot, ``/auth/oidc/callback`` redirected to
``/oidc-callback#access_token=…&refresh_token=…``. Anyone could complete their
*own* SSO login, copy the fragment, and send a victim a link that logged the
victim's browser into the attacker's account (login CSRF / session fixation).

Two mechanisms close it, and both are asserted here:

* a ``wiu_oidc_nonce`` HttpOnly cookie planted before the redirect to the IdP
  and required on the way back — a flow that did not start in this browser is
  refused at the callback;
* a one-time opaque code instead of the token pair, exchanged by the frontend
  against ``POST /auth/oidc/exchange`` — that exchange checks the same cookie,
  so a fabricated ``#code=…`` link is worthless without it.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.api.v1.auth as auth_module
from whatisup.models.user import User

NONCE_COOKIE = "wiu_oidc_nonce"


# ── Provider stubs ────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeHttpxClient:
    """Stands in for httpx.AsyncClient inside oidc_callback (token + userinfo)."""

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
                "sub": "oidc-sub-f11",
                "email": "f11.user@test.com",
                "email_verified": True,
                "preferred_username": "f11_user",
                "name": "F11 User",
            }
        )


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


@pytest.fixture
def oidc_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_resolve_oidc_settings", _fake_settings)
    monkeypatch.setattr(auth_module, "_oidc_discover", _fake_discover)
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _FakeHttpxClient)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_state(fake_redis: FakeRedis, state: str, nonce: str) -> None:
    """Write the Redis entry exactly as /oidc/login would."""
    await fake_redis.setex(
        f"whatisup:oidc:state:{state}",
        300,
        json.dumps(
            {
                "verifier": "verifier123",
                "nonce": hashlib.sha256(nonce.encode()).hexdigest(),
            }
        ),
    )


async def _callback(
    client: AsyncClient, state: str, cookie: str | None = None, ua: str = "OIDC-Device"
):
    headers = {"User-Agent": ua}
    if cookie is not None:
        headers["Cookie"] = f"{NONCE_COOKIE}={cookie}"
    return await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "authcode", "state": state},
        headers=headers,
        follow_redirects=False,
    )


def _fragment_param(location: str, name: str) -> str | None:
    fragment = urlparse(location).fragment
    return parse_qs(fragment).get(name, [None])[0]


def _error_param(location: str) -> str | None:
    return parse_qs(urlparse(location).query).get("error", [None])[0]


# ── /oidc/login — the browser gets its nonce ──────────────────────────────────


@pytest.mark.asyncio
async def test_login_plants_nonce_cookie_and_stores_its_hash(
    client: AsyncClient, fake_redis: FakeRedis, oidc_enabled: None
) -> None:
    resp = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 302

    raw_cookie = resp.headers["set-cookie"]
    assert raw_cookie.startswith(f"{NONCE_COOKIE}=")
    assert "HttpOnly" in raw_cookie
    assert "Path=/api/v1/auth/oidc" in raw_cookie
    nonce = client.cookies[NONCE_COOKIE]

    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    stored = json.loads(await fake_redis.get(f"whatisup:oidc:state:{state}"))
    # Redis holds the fingerprint, never the cookie value itself.
    assert stored["nonce"] == hashlib.sha256(nonce.encode()).hexdigest()
    assert stored["nonce"] != nonce
    assert stored["verifier"]


@pytest.mark.asyncio
async def test_login_cookie_survives_a_split_origin_deployment(
    client: AsyncClient, oidc_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Front on its own host → the exchange is cross-site, so SameSite=Lax
    would drop the cookie and break every SSO login. Such a deployment must
    get SameSite=None (which requires Secure, hence HTTPS-only production)."""

    class _Settings:
        is_production = True
        cors_allowed_origins = ["https://status.example.com"]

    monkeypatch.setattr(auth_module, "get_settings", lambda: _Settings())

    resp = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)

    raw_cookie = resp.headers["set-cookie"]
    assert "SameSite=none" in raw_cookie
    assert "Secure" in raw_cookie


# ── /oidc/callback — refuses flows started elsewhere ──────────────────────────


@pytest.mark.asyncio
async def test_callback_without_nonce_cookie_is_refused(
    client: AsyncClient, fake_redis: FakeRedis, oidc_enabled: None
) -> None:
    """The attacker holds a valid state but the victim's browser has no cookie."""
    await _seed_state(fake_redis, "state-a", "nonce-a")

    resp = await _callback(client, "state-a", cookie=None)

    assert resp.status_code == 302
    assert _error_param(resp.headers["location"]) == "state_mismatch"
    assert not await fake_redis.keys("whatisup:oidc:handoff:*")


@pytest.mark.asyncio
async def test_callback_with_foreign_nonce_cookie_is_refused(
    client: AsyncClient, fake_redis: FakeRedis, oidc_enabled: None
) -> None:
    await _seed_state(fake_redis, "state-b", "nonce-b")

    resp = await _callback(client, "state-b", cookie="some-other-nonce")

    assert _error_param(resp.headers["location"]) == "state_mismatch"
    assert not await fake_redis.keys("whatisup:oidc:handoff:*")


@pytest.mark.asyncio
async def test_callback_refuses_pre_upgrade_state_entries(
    client: AsyncClient, fake_redis: FakeRedis, oidc_enabled: None
) -> None:
    """A login started just before the upgrade stored a bare verifier string.

    Accepting it would mean accepting a flow with no browser binding, so it is
    refused — the user simply restarts the login (5-minute window)."""
    await fake_redis.setex("whatisup:oidc:state:legacy", 300, "verifier123")

    resp = await _callback(client, "legacy", cookie="anything")

    assert _error_param(resp.headers["location"]) == "invalid_state"
    assert not await fake_redis.keys("whatisup:oidc:handoff:*")


@pytest.mark.asyncio
async def test_callback_returns_an_opaque_code_never_tokens(
    client: AsyncClient, fake_redis: FakeRedis, oidc_enabled: None
) -> None:
    await _seed_state(fake_redis, "state-c", "nonce-c")

    resp = await _callback(client, "state-c", cookie="nonce-c")

    location = resp.headers["location"]
    assert "access_token" not in location and "refresh_token" not in location
    code = _fragment_param(location, "code")
    assert code
    # No session is opened yet: the tokens are minted at the exchange.
    assert not await fake_redis.keys("whatisup:refresh:*")
    assert await fake_redis.get(f"whatisup:oidc:handoff:{code}")


# ── /oidc/exchange — the cookie is required again ─────────────────────────────


async def _login_up_to_code(
    client: AsyncClient, fake_redis: FakeRedis, state: str, nonce: str
) -> str:
    await _seed_state(fake_redis, state, nonce)
    resp = await _callback(client, state, cookie=nonce)
    assert resp.status_code == 302, resp.text
    code = _fragment_param(resp.headers["location"], "code")
    assert code
    return code


@pytest.mark.asyncio
async def test_exchange_without_the_cookie_is_rejected_and_burns_the_code(
    client: AsyncClient, fake_redis: FakeRedis, oidc_enabled: None
) -> None:
    """This is the forged-link scenario: the victim opens `#code=…` from the
    attacker's own SSO login. Without the attacker's HttpOnly cookie the
    exchange fails, and the code is consumed so it cannot be retried."""
    code = await _login_up_to_code(client, fake_redis, "state-d", "nonce-d")

    resp = await client.post("/api/v1/auth/oidc/exchange", json={"code": code})
    assert resp.status_code == 401

    retry = await client.post(
        "/api/v1/auth/oidc/exchange",
        json={"code": code},
        headers={"Cookie": f"{NONCE_COOKIE}=nonce-d"},
    )
    assert retry.status_code == 401
    assert not await fake_redis.keys("whatisup:refresh:*")


@pytest.mark.asyncio
async def test_exchange_with_a_mismatched_cookie_is_rejected(
    client: AsyncClient, fake_redis: FakeRedis, oidc_enabled: None
) -> None:
    code = await _login_up_to_code(client, fake_redis, "state-e", "nonce-e")

    resp = await client.post(
        "/api/v1/auth/oidc/exchange",
        json={"code": code},
        headers={"Cookie": f"{NONCE_COOKIE}=attacker-nonce"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_exchange_rejects_an_unknown_code(client: AsyncClient, oidc_enabled: None) -> None:
    resp = await client.post(
        "/api/v1/auth/oidc/exchange",
        json={"code": "x" * 43},
        headers={"Cookie": f"{NONCE_COOKIE}=whatever"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_exchange_issues_tokens_once_for_the_originating_browser(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    oidc_enabled: None,
) -> None:
    code = await _login_up_to_code(client, fake_redis, "state-f", "nonce-f")

    resp = await client.post(
        "/api/v1/auth/oidc/exchange",
        json={"code": code},
        headers={"Cookie": f"{NONCE_COOKIE}=nonce-f", "User-Agent": "Exchange-Device"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]

    user = (
        await db_session.execute(select(User).where(User.oidc_sub == "oidc-sub-f11"))
    ).scalar_one()

    # Session metadata describes the browser that actually opened the session…
    rh = hashlib.sha256(body["refresh_token"].encode()).hexdigest()[:32]
    meta = json.loads(await fake_redis.get(f"whatisup:refresh:{user.id}:{rh}"))
    assert meta["ua"] == "Exchange-Device"
    assert meta["created_at"] and "ip" in meta

    # …the nonce cookie is cleared…
    assert NONCE_COOKIE in resp.headers.get("set-cookie", "")

    # …and the code is single-use.
    replay = await client.post(
        "/api/v1/auth/oidc/exchange",
        json={"code": code},
        headers={"Cookie": f"{NONCE_COOKIE}=nonce-f"},
    )
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_exchange_refuses_a_deactivated_user(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    oidc_enabled: None,
) -> None:
    code = await _login_up_to_code(client, fake_redis, "state-g", "nonce-g")

    user = (
        await db_session.execute(select(User).where(User.oidc_sub == "oidc-sub-f11"))
    ).scalar_one()
    user.is_active = False
    await db_session.flush()

    resp = await client.post(
        "/api/v1/auth/oidc/exchange",
        json={"code": code},
        headers={"Cookie": f"{NONCE_COOKIE}=nonce-g"},
    )
    assert resp.status_code == 401
