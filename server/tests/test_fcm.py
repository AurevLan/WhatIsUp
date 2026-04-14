"""FCM helper unit tests — payload encryption + service-account loading.

Network calls (Google OAuth2 token exchange + FCM HTTP v1 send) are mocked
via httpx so the tests stay hermetic.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from whatisup.services import fcm


def _generate_test_private_key() -> str:
    """Generate a throwaway RSA-2048 private key in PEM format for JWT signing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


_TEST_PRIVATE_KEY = _generate_test_private_key()


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_PATH", raising=False)
    yield


def test_load_service_account_returns_none_when_unconfigured() -> None:
    assert fcm.load_service_account() is None
    assert fcm.is_enabled() is False


def test_load_service_account_from_env_json(monkeypatch) -> None:
    sa_json = json.dumps(
        {
            "project_id": "whatisup-mobile",
            "client_email": "test@whatisup-mobile.iam.gserviceaccount.com",
            "private_key": _TEST_PRIVATE_KEY,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    monkeypatch.setenv("FCM_SERVICE_ACCOUNT_JSON", sa_json)
    sa = fcm.load_service_account()
    assert sa is not None
    assert sa.project_id == "whatisup-mobile"
    assert sa.client_email.endswith("@whatisup-mobile.iam.gserviceaccount.com")
    assert fcm.is_enabled() is True


def test_load_service_account_invalid_json_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("FCM_SERVICE_ACCOUNT_JSON", "{not json")
    assert fcm.load_service_account() is None


def test_encrypt_payload_round_trip() -> None:
    key = Fernet.generate_key().decode()
    payload = {"title": "Foo", "body": "Bar", "monitor_id": "abc"}
    ciphertext = fcm._encrypt_payload(payload, key)
    # Ciphertext is opaque and clearly larger than the plaintext
    assert isinstance(ciphertext, str)
    assert "Foo" not in ciphertext
    assert "Bar" not in ciphertext
    # Round-trip via Fernet directly
    decrypted = json.loads(Fernet(key.encode()).decrypt(ciphertext.encode()))
    assert decrypted == payload


@pytest.mark.asyncio
async def test_send_to_devices_returns_zero_when_disabled() -> None:
    out = await fcm.send_to_devices(
        [("token1", Fernet.generate_key().decode())], {"x": 1}
    )
    assert out == {"sent": 0, "failed": 0, "invalid_tokens": []}


@pytest.mark.asyncio
async def test_send_to_devices_happy_path(monkeypatch, fake_redis) -> None:
    """Mock Google's token endpoint and FCM send endpoint and verify the
    dispatcher signs a JWT, exchanges it for a bearer, and pushes the
    encrypted payload to each token."""
    sa_json = json.dumps(
        {
            "project_id": "whatisup-mobile",
            "client_email": "test@whatisup-mobile.iam.gserviceaccount.com",
            "private_key": _TEST_PRIVATE_KEY,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    monkeypatch.setenv("FCM_SERVICE_ACCOUNT_JSON", sa_json)

    # Wire fake redis as the cache backend
    import whatisup.core.redis as redis_module

    redis_module._redis = fake_redis

    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200, json={"access_token": "fake-token", "expires_in": 3600}
            )
        if request.url.host == "fcm.googleapis.com":
            return httpx.Response(200, json={"name": "projects/x/messages/abc"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def mock_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_async_client)

    devices = [
        ("token-A", Fernet.generate_key().decode()),
        ("token-B", Fernet.generate_key().decode()),
    ]
    result = await fcm.send_to_devices(devices, {"title": "x", "body": "y"})

    assert result == {"sent": 2, "failed": 0, "invalid_tokens": []}
    # 1 token exchange + 2 push calls
    assert len(captured_requests) == 3
    hosts = [urlparse(str(r.url)).hostname for r in captured_requests]
    assert "oauth2.googleapis.com" in hosts
    assert hosts.count("fcm.googleapis.com") == 2

    redis_module._redis = None


@pytest.mark.asyncio
async def test_send_to_devices_marks_invalid_tokens(monkeypatch, fake_redis) -> None:
    sa_json = json.dumps(
        {
            "project_id": "whatisup-mobile",
            "client_email": "test@whatisup-mobile.iam.gserviceaccount.com",
            "private_key": _TEST_PRIVATE_KEY,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    monkeypatch.setenv("FCM_SERVICE_ACCOUNT_JSON", sa_json)
    import whatisup.core.redis as redis_module

    redis_module._redis = fake_redis

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200, json={"access_token": "fake-token", "expires_in": 3600}
            )
        return httpx.Response(
            404, json={"error": {"status": "UNREGISTERED", "code": 404}}
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def mock_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_async_client)

    devices = [("dead-token", Fernet.generate_key().decode())]
    result = await fcm.send_to_devices(devices, {"title": "x"})

    assert result["sent"] == 0
    assert result["failed"] == 1
    assert result["invalid_tokens"] == ["dead-token"]

    redis_module._redis = None
