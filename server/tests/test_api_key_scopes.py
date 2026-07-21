"""C2 — portées des clés API.

Une clé API valait jusqu'ici un mot de passe : elle rendait un `User` avec tous
ses droits. Une clé destinée à une intégration en lecture (extension, script de
supervision, tableau de bord tiers) pouvait donc supprimer des monitors.

Les portées se vérifient sur la méthode HTTP, dans `get_current_user` — passage
obligé de toute route authentifiée, donc aucune ne peut être oubliée. Ces tests
pinnent les deux moitiés du contrat : une clé en lecture seule lit mais n'écrit
pas, et une clé complète continue de tout faire.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_key(client: AsyncClient, user_token: str, name: str, scopes=None) -> dict:
    body: dict = {"name": name}
    if scopes is not None:
        body["scopes"] = scopes
    resp = await client.post("/api/v1/api-keys/", json=body, headers=_auth(user_token))
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_key_defaults_to_full_access(client: AsyncClient, user_token: str) -> None:
    """Défaut inchangé : les clés déjà distribuées gardent leurs droits."""
    key = await _create_key(client, user_token, "default")
    assert key["scopes"] == ["read", "write"]


@pytest.mark.asyncio
async def test_read_only_key_can_read(client: AsyncClient, user_token: str) -> None:
    key = await _create_key(client, user_token, "ro", ["read"])
    resp = await client.get("/api/v1/monitors/", headers={"X-Api-Key": key["key"]})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_read_only_key_cannot_write(client: AsyncClient, user_token: str) -> None:
    key = await _create_key(client, user_token, "ro-write", ["read"])
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Nope", "url": "https://example.com", "check_type": "http"},
        headers={"X-Api-Key": key["key"]},
    )
    assert resp.status_code == 403
    assert "read-only" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_read_only_key_cannot_delete(client: AsyncClient, user_token: str) -> None:
    """DELETE est la méthode qui fait le plus de dégâts : elle doit être bloquée."""
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Victim", "url": "https://example.com", "check_type": "http"},
            headers=_auth(user_token),
        )
    ).json()
    key = await _create_key(client, user_token, "ro-del", ["read"])

    resp = await client.delete(f"/api/v1/monitors/{mon['id']}", headers={"X-Api-Key": key["key"]})
    assert resp.status_code == 403

    # Le monitor est toujours là.
    still = await client.get(f"/api/v1/monitors/{mon['id']}", headers=_auth(user_token))
    assert still.status_code == 200


@pytest.mark.asyncio
async def test_full_key_can_write(client: AsyncClient, user_token: str) -> None:
    key = await _create_key(client, user_token, "rw", ["read", "write"])
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Allowed", "url": "https://example.com", "check_type": "http"},
        headers={"X-Api-Key": key["key"]},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_jwt_sessions_are_unaffected(client: AsyncClient, user_token: str) -> None:
    """Les portées ne concernent que les clés API, pas les sessions."""
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Via JWT", "url": "https://example.com", "check_type": "http"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_scope_validation_rejects_unknown_and_readless(
    client: AsyncClient, user_token: str
) -> None:
    unknown = await client.post(
        "/api/v1/api-keys/",
        json={"name": "bad", "scopes": ["admin"]},
        headers=_auth(user_token),
    )
    assert unknown.status_code == 422

    # Une clé sans lecture serait inerte : refusée plutôt qu'émise pour rien.
    readless = await client.post(
        "/api/v1/api-keys/",
        json={"name": "bad2", "scopes": ["write"]},
        headers=_auth(user_token),
    )
    assert readless.status_code == 422


@pytest.mark.asyncio
async def test_scopes_are_listed(client: AsyncClient, user_token: str) -> None:
    await _create_key(client, user_token, "listed", ["read"])
    resp = await client.get("/api/v1/api-keys/", headers=_auth(user_token))
    assert resp.status_code == 200
    assert any(k["scopes"] == ["read"] for k in resp.json())
