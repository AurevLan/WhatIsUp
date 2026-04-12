"""CORS allowance for the Capacitor mobile app origins.

The mobile app loads its bundled assets from a stable internal origin
(``https://localhost`` on Android, ``capacitor://localhost`` on iOS) and then
calls the user's self-hosted backend. The server must accept those origins
without the user having to add them to ``CORS_ALLOWED_ORIGINS`` manually.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    ["https://localhost", "capacitor://localhost"],
)
async def test_mobile_origin_allowed_on_preflight(client: AsyncClient, origin: str) -> None:
    resp = await client.options(
        "/api/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code in (200, 204), resp.text
    assert resp.headers.get("access-control-allow-origin") == origin


@pytest.mark.asyncio
async def test_unknown_origin_not_allowed(client: AsyncClient) -> None:
    resp = await client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Either an explicit reject (no allow header) or a non-matching value.
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example.com"
