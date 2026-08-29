"""Acknowledging from Slack / Telegram (plan V2, B-3).

These are the only unauthenticated mutating endpoints in the product, so this
file is mostly about what they **refuse**. The headline case is the last one:
an attacker who runs their own Slack app knows their own signing secret and can
produce a perfectly-signed request naming someone else's incident. Verifying the
provider signature alone would accept it — and silencing a stranger's page is
the most damaging thing this endpoint could do.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import encrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertChannelType
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.oncall import ContactMethod, UserContact
from whatisup.models.user import User
from whatisup.services.channel_ack import (
    AckTokenError,
    make_ack_token,
    verify_ack_token,
    verify_slack_signature,
    verify_telegram_secret,
)

pytestmark = pytest.mark.asyncio

SECRET = "slack-signing-secret"
SLACK_UID = "U123456"


@pytest_asyncio.fixture
async def setup(db_session: AsyncSession):
    """A monitor with an open incident, a signed channel, and a linked user."""
    owner = User(email="oncaller@example.com", username="oncaller", hashed_password="x")
    stranger = User(email="stranger@example.com", username="stranger", hashed_password="x")
    db_session.add_all([owner, stranger])
    await db_session.flush()

    monitor = Monitor(name="api", url="http://api", owner_id=owner.id)
    db_session.add(monitor)
    await db_session.flush()

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    channel = AlertChannel(
        owner_id=owner.id,
        name="ops",
        type=AlertChannelType.slack,
        config=encrypt_channel_config(
            {"webhook_url": "https://hooks.slack.com/x", "signing_secret": SECRET}
        ),
    )
    db_session.add_all([incident, channel])
    await db_session.flush()

    db_session.add(
        UserContact(
            user_id=owner.id,
            method=ContactMethod.slack,
            value=SLACK_UID,
            via_channel_id=channel.id,
        )
    )
    await db_session.flush()
    await db_session.commit()
    return {
        "owner": owner,
        "stranger": stranger,
        "monitor": monitor,
        "incident": incident,
        "channel": channel,
    }


def _slack_body(token: str, user_id: str = SLACK_UID) -> str:
    payload = {
        "user": {"id": user_id},
        "actions": [{"action_id": "whatisup_ack", "value": token}],
    }
    return f"payload={json.dumps(payload)}"


def _slack_headers(body: str, secret: str = SECRET, ts: int | None = None) -> dict:
    ts = ts or int(time.time())
    base = f"v0:{ts}:{body}".encode()
    sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": str(ts),
        "X-Slack-Signature": sig,
        "Content-Type": "application/x-www-form-urlencoded",
    }


# ── The token itself ──────────────────────────────────────────────────────────


def test_token_round_trips():
    inc, ch = uuid.uuid4(), uuid.uuid4()
    assert verify_ack_token(make_ack_token(inc, ch)) == (inc, ch)


def test_token_fits_telegrams_callback_data_limit():
    """64 bytes is a hard protocol limit — over it, the button cannot exist."""
    assert len(make_ack_token(uuid.uuid4(), uuid.uuid4())) <= 64


@pytest.mark.parametrize("bad", ["", "nonsense", "a.b.c.d", "x" * 80])
def test_malformed_tokens_are_refused(bad):
    with pytest.raises(AckTokenError):
        verify_ack_token(bad)


def test_a_flipped_bit_invalidates_the_token():
    token = make_ack_token(uuid.uuid4(), uuid.uuid4())
    tampered = ("A" if token[0] != "A" else "B") + token[1:]
    with pytest.raises(AckTokenError):
        verify_ack_token(tampered)


def test_an_expired_token_is_refused():
    token = make_ack_token(uuid.uuid4(), uuid.uuid4(), now=1_000_000)
    with pytest.raises(AckTokenError):
        verify_ack_token(token, now=1_000_000 + 24 * 3600 + 5)


# ── Provider signatures ───────────────────────────────────────────────────────


def test_slack_signature_accepts_only_the_real_thing():
    body = b"payload=x"
    ts = str(int(time.time()))
    base = b"v0:" + ts.encode() + b":" + body
    good = "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()

    assert verify_slack_signature(SECRET, ts, body, good) is True
    assert verify_slack_signature("other-secret", ts, body, good) is False
    assert verify_slack_signature(SECRET, ts, b"payload=tampered", good) is False
    assert verify_slack_signature(SECRET, ts, body, "v0=deadbeef") is False
    assert verify_slack_signature("", ts, body, good) is False


def test_slack_signature_rejects_a_replayed_request():
    """The timestamp is inside the signed string; the window is what bounds replay."""
    body = b"payload=x"
    old = int(time.time()) - 3600
    base = b"v0:" + str(old).encode() + b":" + body
    sig = "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()
    assert verify_slack_signature(SECRET, str(old), body, sig) is False


def test_telegram_secret_compare():
    assert verify_telegram_secret("s3cret", "s3cret") is True
    assert verify_telegram_secret("s3cret", "other") is False
    assert verify_telegram_secret("s3cret", None) is False
    # No secret configured must never mean "accept anything".
    assert verify_telegram_secret("", "anything") is False


# ── The endpoint ──────────────────────────────────────────────────────────────


async def test_a_valid_callback_acknowledges(client: AsyncClient, setup, db_session):
    token = make_ack_token(setup["incident"].id, setup["channel"].id)
    body = _slack_body(token)
    resp = await client.post("/api/v1/callbacks/slack", content=body, headers=_slack_headers(body))

    assert resp.status_code == 200
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_at is not None
    assert setup["incident"].acked_by_id == setup["owner"].id


async def test_an_unsigned_callback_is_refused(client: AsyncClient, setup, db_session):
    token = make_ack_token(setup["incident"].id, setup["channel"].id)
    body = _slack_body(token)
    resp = await client.post(
        "/api/v1/callbacks/slack",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 403
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_at is None


async def test_a_wrongly_signed_callback_is_refused(client: AsyncClient, setup, db_session):
    token = make_ack_token(setup["incident"].id, setup["channel"].id)
    body = _slack_body(token)
    resp = await client.post(
        "/api/v1/callbacks/slack", content=body, headers=_slack_headers(body, secret="wrong")
    )
    assert resp.status_code == 403
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_at is None


async def test_a_forged_token_is_refused(client: AsyncClient, setup, db_session):
    """Correct provider signature, token we never minted."""
    body = _slack_body("Zm9yZ2VkLXRva2VuLXRoYXQtaXMtdGhlLXJpZ2h0LWxlbmd0aC0xMjM0NTY3OA")
    resp = await client.post("/api/v1/callbacks/slack", content=body, headers=_slack_headers(body))
    assert resp.status_code == 403
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_at is None


async def test_an_unknown_chat_identity_cannot_acknowledge(client: AsyncClient, setup, db_session):
    """Being in the Slack workspace is not being a WhatIsUp user."""
    token = make_ack_token(setup["incident"].id, setup["channel"].id)
    body = _slack_body(token, user_id="U-NOBODY")
    resp = await client.post("/api/v1/callbacks/slack", content=body, headers=_slack_headers(body))
    assert resp.status_code == 403
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_at is None


async def test_a_user_without_access_to_the_monitor_cannot_acknowledge(
    client: AsyncClient, setup, db_session
):
    """Linked chat identity, but no business with this monitor."""
    db_session.add(
        UserContact(
            user_id=setup["stranger"].id,
            method=ContactMethod.slack,
            value="U-STRANGER",
            via_channel_id=setup["channel"].id,
        )
    )
    await db_session.commit()

    token = make_ack_token(setup["incident"].id, setup["channel"].id)
    body = _slack_body(token, user_id="U-STRANGER")
    resp = await client.post("/api/v1/callbacks/slack", content=body, headers=_slack_headers(body))
    assert resp.status_code == 403
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_at is None


async def test_a_signature_from_another_channel_cannot_ack_this_incident(
    client: AsyncClient, setup, db_session
):
    """The cross-tenant hole this whole design exists to close.

    The attacker owns a channel, so they know its signing secret and can sign
    perfectly. What they cannot do is mint a token binding *our* incident to
    *their* channel — and since the channel comes from the token, the signature
    is then checked against the wrong secret and fails.
    """
    attacker_secret = "attacker-signing-secret"
    attacker_channel = AlertChannel(
        owner_id=setup["stranger"].id,
        name="attacker",
        type=AlertChannelType.slack,
        config=encrypt_channel_config(
            {"webhook_url": "https://hooks.slack.com/y", "signing_secret": attacker_secret}
        ),
    )
    db_session.add(attacker_channel)
    await db_session.commit()

    # A token naming the victim's incident but the attacker's channel is not
    # something they can produce — but even if the binding were theirs to
    # choose, the signature is verified against the channel *in the token*.
    token = make_ack_token(setup["incident"].id, attacker_channel.id)
    body = _slack_body(token)
    resp = await client.post(
        "/api/v1/callbacks/slack", content=body, headers=_slack_headers(body, secret=SECRET)
    )
    # Signed with the victim channel's secret, but the token says the attacker's
    # channel → verified against the wrong secret → refused.
    assert resp.status_code == 403
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_at is None


async def test_a_channel_without_a_signing_secret_refuses_callbacks(
    client: AsyncClient, setup, db_session
):
    """No secret means no verification, which means no ack — never "accept unsigned"."""
    plain = AlertChannel(
        owner_id=setup["owner"].id,
        name="plain",
        type=AlertChannelType.slack,
        config=encrypt_channel_config({"webhook_url": "https://hooks.slack.com/z"}),
    )
    db_session.add(plain)
    await db_session.commit()

    token = make_ack_token(setup["incident"].id, plain.id)
    body = _slack_body(token)
    resp = await client.post("/api/v1/callbacks/slack", content=body, headers=_slack_headers(body))
    assert resp.status_code == 403


async def test_rejections_do_not_say_why(client: AsyncClient, setup):
    """An unauthenticated endpoint that distinguishes failures is an oracle."""
    real = make_ack_token(setup["incident"].id, setup["channel"].id)
    unknown = make_ack_token(uuid.uuid4(), setup["channel"].id)

    bodies = [_slack_body(real, user_id="U-NOBODY"), _slack_body(unknown)]
    details = set()
    for body in bodies:
        resp = await client.post(
            "/api/v1/callbacks/slack", content=body, headers=_slack_headers(body)
        )
        assert resp.status_code == 403
        details.add(resp.json().get("detail"))
    assert len(details) == 1


# ── Contact lookup scoped to the channel (audit hardening) ────────────────────


async def test_two_users_claiming_the_same_handle_are_refused(
    client: AsyncClient, setup, db_session
):
    """A contact is self-declared and unverified — two users can claim it.

    Neither should be credited: picking one arbitrarily would let whichever
    user declared the handle second silently start acknowledging the other's
    incidents, with no error the victim could ever see (anti-oracle).
    """
    db_session.add(
        UserContact(
            user_id=setup["stranger"].id,
            method=ContactMethod.slack,
            value=SLACK_UID,
            via_channel_id=setup["channel"].id,
        )
    )
    await db_session.commit()

    token = make_ack_token(setup["incident"].id, setup["channel"].id)
    body = _slack_body(token)
    resp = await client.post("/api/v1/callbacks/slack", content=body, headers=_slack_headers(body))

    assert resp.status_code == 403
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_at is None


async def test_a_handle_declared_on_a_different_channel_does_not_resolve(
    client: AsyncClient, setup, db_session
):
    """The lookup is scoped to the channel the token was minted for.

    Same (method, value) pair, but the contact was declared against a
    different channel than the one that issued this token — it must not
    resolve, or the channel scope is decorative rather than enforced.
    """
    other_channel = AlertChannel(
        owner_id=setup["owner"].id,
        name="other",
        type=AlertChannelType.slack,
        config=encrypt_channel_config(
            {"webhook_url": "https://hooks.slack.com/other", "signing_secret": "other-secret"}
        ),
    )
    db_session.add(other_channel)
    await db_session.flush()

    # A second user claims the victim's handle, but on the *other* channel —
    # this must not interfere with the nominal ack on `setup["channel"]`.
    db_session.add(
        UserContact(
            user_id=setup["stranger"].id,
            method=ContactMethod.slack,
            value=SLACK_UID,
            via_channel_id=other_channel.id,
        )
    )
    await db_session.commit()

    token = make_ack_token(setup["incident"].id, setup["channel"].id)
    body = _slack_body(token)
    resp = await client.post("/api/v1/callbacks/slack", content=body, headers=_slack_headers(body))

    assert resp.status_code == 200
    await db_session.refresh(setup["incident"])
    assert setup["incident"].acked_by_id == setup["owner"].id
