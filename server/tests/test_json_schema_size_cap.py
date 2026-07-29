"""S5 — `json_schema` borné à l'entrée (audit F8, versant serveur).

La sonde évalue ce schéma contre le corps de la réponse sous un budget CPU
borné : au-delà d'une certaine taille elle refuse d'évaluer. Sans plafond côté
API, le monitor était accepté puis échouait silencieusement à chaque cycle.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _monitor(json_schema: dict) -> dict:
    return {
        "name": "schema monitor",
        "url": "https://example.com",
        "check_type": "json_path",
        "json_schema": json_schema,
    }


@pytest.mark.asyncio
async def test_oversized_json_schema_is_rejected(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json=_monitor({"type": "object", "description": "x" * 70_000}),
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_oversized_json_schema_rejected_on_update(
    client: AsyncClient, user_token: str
) -> None:
    created = await client.post(
        "/api/v1/monitors/",
        json=_monitor({"type": "object"}),
        headers=_auth(user_token),
    )
    assert created.status_code in (200, 201)

    resp = await client.patch(
        f"/api/v1/monitors/{created.json()['id']}",
        json={"json_schema": {"type": "object", "description": "x" * 70_000}},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reasonable_json_schema_still_accepted(client: AsyncClient, user_token: str) -> None:
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "pattern": "^ok$"}},
        "required": ["status"],
    }
    resp = await client.post("/api/v1/monitors/", json=_monitor(schema), headers=_auth(user_token))

    assert resp.status_code in (200, 201)
    assert resp.json()["json_schema"] == schema
