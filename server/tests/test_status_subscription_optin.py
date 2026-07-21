"""C1 — double opt-in et notification des abonnés d'une page de statut.

Avant ce lot, `StatusSubscription` était une impasse : la table se remplissait
mais n'était relue nulle part, donc aucun abonné ne recevait jamais de mail et
le jeton de désinscription n'était délivré par aucun canal. Ces tests pinnent
le flux de bout en bout ainsi que les deux garde-fous : une inscription reste
inerte tant qu'elle n'est pas confirmée, et un jeton de confirmation ne sert
qu'une fois.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from whatisup.models.status_subscription import StatusSubscription


async def _ok_mail(to, subject, body):
    """Stub d'envoi : le SMTP n'a pas sa place dans ces tests."""
    return True


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _public_group(client: AsyncClient, user_token: str, slug: str) -> dict:
    resp = await client.post(
        "/api/v1/groups/",
        json={"name": f"Group {slug}", "public_slug": slug},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _fetch_sub(db_session, email: str) -> StatusSubscription | None:
    return (
        await db_session.execute(
            select(StatusSubscription).where(StatusSubscription.email == email)
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_subscription_starts_unconfirmed(
    client: AsyncClient, user_token: str, db_session, monkeypatch
) -> None:
    """La page est publique : un tiers peut soumettre l'adresse de quelqu'un
    d'autre. L'abonnement ne doit donc rien recevoir avant confirmation."""
    sent: list[str] = []

    async def _capture(to, subject, body):
        sent.append(to)
        return True

    monkeypatch.setattr("whatisup.services.status_subscription._send_mail", _capture)

    await _public_group(client, user_token, "optin1")
    resp = await client.post(
        "/api/v1/public/pages/optin1/subscribe",
        json={"email": "victim@example.com"},
    )
    assert resp.status_code == 201

    sub = await _fetch_sub(db_session, "victim@example.com")
    assert sub is not None
    assert sub.confirmed_at is None, "l'abonnement ne doit pas être actif d'emblée"
    assert sub.confirm_token, "un jeton de confirmation doit être émis"


@pytest.mark.asyncio
async def test_confirm_activates_and_burns_the_token(
    client: AsyncClient, user_token: str, db_session, monkeypatch
) -> None:
    monkeypatch.setattr("whatisup.services.status_subscription._send_mail", _ok_mail)
    await _public_group(client, user_token, "optin2")
    await client.post(
        "/api/v1/public/pages/optin2/subscribe",
        json={"email": "ok@example.com"},
    )
    sub = await _fetch_sub(db_session, "ok@example.com")
    token = sub.confirm_token

    resp = await client.get(f"/api/v1/public/pages/optin2/confirm?token={token}")
    assert resp.status_code == 200

    # Pas de `refresh()` ici : le fixture de test remplace `get_db` par la
    # session du test *sans* commit, donc recharger depuis la base écraserait
    # la mutation encore en attente. L'endpoint a travaillé sur cette instance.
    assert sub.confirmed_at is not None
    assert sub.confirm_token is None, "le jeton doit être consommé"

    # Rejouer le lien (il traîne dans une boîte mail) ne doit plus rien activer.
    replay = await client.get(f"/api/v1/public/pages/optin2/confirm?token={token}")
    assert replay.status_code == 404


@pytest.mark.asyncio
async def test_confirm_rejects_a_token_from_another_page(
    client: AsyncClient, user_token: str, db_session, monkeypatch
) -> None:
    """Le jeton est lié à son groupe : pas de confirmation croisée."""
    monkeypatch.setattr("whatisup.services.status_subscription._send_mail", _ok_mail)
    await _public_group(client, user_token, "optin3a")
    await _public_group(client, user_token, "optin3b")
    await client.post(
        "/api/v1/public/pages/optin3a/subscribe",
        json={"email": "cross@example.com"},
    )
    sub = await _fetch_sub(db_session, "cross@example.com")

    resp = await client.get(f"/api/v1/public/pages/optin3b/confirm?token={sub.confirm_token}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resubscribing_reissues_the_confirmation(
    client: AsyncClient, user_token: str, db_session, monkeypatch
) -> None:
    """Un mail de confirmation perdu ne doit pas enfermer l'adresse."""
    sent: list[str] = []

    async def _capture(to, subject, body):
        sent.append(to)
        return True

    monkeypatch.setattr("whatisup.services.status_subscription._send_mail", _capture)
    await _public_group(client, user_token, "optin4")
    await client.post("/api/v1/public/pages/optin4/subscribe", json={"email": "retry@example.com"})
    first = (await _fetch_sub(db_session, "retry@example.com")).confirm_token

    resp = await client.post(
        "/api/v1/public/pages/optin4/subscribe", json={"email": "retry@example.com"}
    )
    assert resp.status_code == 201
    sub = await _fetch_sub(db_session, "retry@example.com")
    assert sub.confirm_token != first, "un nouveau jeton doit être émis"
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_subscribe_does_not_reveal_existing_addresses(
    client: AsyncClient, user_token: str, monkeypatch
) -> None:
    """Réponse identique qu'on soit déjà abonné ou non (anti-énumération)."""
    monkeypatch.setattr("whatisup.services.status_subscription._send_mail", _ok_mail)
    await _public_group(client, user_token, "optin5")
    first = await client.post(
        "/api/v1/public/pages/optin5/subscribe", json={"email": "known@example.com"}
    )
    second = await client.post(
        "/api/v1/public/pages/optin5/subscribe", json={"email": "known@example.com"}
    )
    assert first.status_code == second.status_code
    assert first.json() == second.json()


@pytest.mark.asyncio
async def test_unsubscribe_removes_the_subscription(
    client: AsyncClient, user_token: str, db_session, monkeypatch
) -> None:
    monkeypatch.setattr("whatisup.services.status_subscription._send_mail", _ok_mail)
    await _public_group(client, user_token, "optin6")
    await client.post("/api/v1/public/pages/optin6/subscribe", json={"email": "bye@example.com"})
    sub = await _fetch_sub(db_session, "bye@example.com")

    resp = await client.get(f"/api/v1/public/pages/optin6/unsubscribe?token={sub.token}")
    assert resp.status_code == 200
    assert await _fetch_sub(db_session, "bye@example.com") is None
