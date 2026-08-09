"""Acknowledging an incident from a chat message (plan V2, B-3).

Until now an ack was UI-only: an on-call engineer woken by a Slack message had
to find a laptop. This module lets the button in that message do it.

Why a provider signature is not enough
──────────────────────────────────────
Slack signs its requests, and Telegram lets us pin a secret token on the
webhook. Verifying that proves **the request came from the provider**. It does
not prove **which incident the button was for** — the incident id travels in the
payload, and the payload is only as trustworthy as whoever assembled it.

Concretely: an attacker who runs their own Slack app knows their own signing
secret. They can craft a perfectly-signed interaction naming *someone else's*
incident id. A server that only checks the provider signature would acknowledge
it — silencing another tenant's page, which is the most damaging thing this
endpoint could possibly do.

So every button carries a token **we** minted, binding the incident to the
channel it was sent through. Two independent proofs:

* the provider signature says the request is genuinely from Slack/Telegram;
* our token says this button is one we issued, for this incident, on this
  channel, and not too long ago.

Neither alone is sufficient, and the endpoint refuses if either is missing.

Deliberately not a bearer credential
────────────────────────────────────
The token authorises *one action on one incident*, not a session. It carries no
user identity: **who** is acknowledging is resolved separately, from the chat
identity the provider reports, matched against ``UserContact``. A leaked token
therefore lets someone acknowledge one incident they were already being paged
about — not read anything, not act as anyone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
import uuid

import structlog

from whatisup.core.config import get_settings

logger = structlog.get_logger(__name__)

#: How long a button stays live. Long enough for a night shift to wake up and
#: tap it, short enough that a message forwarded into a public channel months
#: later is inert.
TOKEN_TTL_SECONDS = 24 * 3600

#: Bytes of HMAC kept in the token. The wire format has to fit Telegram's
#: **64-byte** ``callback_data`` limit, which a full 32-byte digest blows
#: through twice over. 10 bytes leaves 80 bits — forging one costs 2^80 work
#: against a token that authorises a single action, on a single incident, for a
#: single day. The alternative, keeping server-side state keyed by a short id,
#: would put an ack behind Redis being up; this stays stateless.
_SIG_BYTES = 10

#: 16 (incident) + 16 (channel) + 4 (expiry, u32) + 10 (mac) = 46 bytes,
#: 62 base64url characters. Two to spare.
_PAYLOAD_BYTES = 36


class AckTokenError(Exception):
    """The token is absent, malformed, forged or expired."""


def _signing_key() -> bytes:
    """Key material for ack tokens.

    Derived from ``SECRET_KEY`` rather than reusing it raw, so a token can never
    be confused with a JWT signed by the same secret — different purpose,
    different key.
    """
    settings = get_settings()
    return hashlib.sha256(f"channel-ack:{settings.secret_key}".encode()).digest()


def _mac(payload: bytes) -> bytes:
    return hmac.new(_signing_key(), payload, hashlib.sha256).digest()[:_SIG_BYTES]


def make_ack_token(incident_id: uuid.UUID, channel_id: uuid.UUID, *, now: int | None = None) -> str:
    """Mint a token binding one incident to the channel it is announced on."""
    expires_at = int(now or time.time()) + TOKEN_TTL_SECONDS
    payload = incident_id.bytes + channel_id.bytes + struct.pack(">I", expires_at)
    return base64.urlsafe_b64encode(payload + _mac(payload)).decode().rstrip("=")


def verify_ack_token(token: str, *, now: int | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    """Return ``(incident_id, channel_id)`` or raise ``AckTokenError``.

    The signature is checked **before** the expiry, and compared in constant
    time, so neither the validity of a forged token nor its age leaks through
    timing.
    """
    try:
        raw = base64.urlsafe_b64decode((token or "") + "=" * (-len(token or "") % 4))
    except Exception as exc:  # noqa: BLE001 - any decode failure is just a bad token
        raise AckTokenError("malformed token") from exc
    if len(raw) != _PAYLOAD_BYTES + _SIG_BYTES:
        raise AckTokenError("malformed token")

    payload, signature = raw[:_PAYLOAD_BYTES], raw[_PAYLOAD_BYTES:]
    if not hmac.compare_digest(signature, _mac(payload)):
        raise AckTokenError("bad signature")

    incident_id = uuid.UUID(bytes=payload[:16])
    channel_id = uuid.UUID(bytes=payload[16:32])
    (expires_at,) = struct.unpack(">I", payload[32:36])
    if int(now or time.time()) > expires_at:
        raise AckTokenError("expired token")
    return incident_id, channel_id


def signing_secret_configured(config: dict) -> bool:
    """Whether this channel can host interactive buttons at all.

    A channel with no signing secret cannot have its callbacks verified, so it
    gets **no buttons** rather than dead ones: a button that silently fails to
    acknowledge is worse than no button, because the engineer stops looking for
    another way to do it.
    """
    return bool((config or {}).get("signing_secret"))


def verify_slack_signature(
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    *,
    now: int | None = None,
    tolerance: int = 300,
) -> bool:
    """Slack's ``v0`` scheme, with the replay window Slack documents.

    The timestamp is part of the signed string, so widening the window is the
    only way to make a captured request replayable — hence the five minutes
    Slack recommends rather than something more permissive.
    """
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(now or time.time()) - sent_at) > tolerance:
        return False

    basestring = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_telegram_secret(expected_secret: str, provided: str | None) -> bool:
    """Telegram's ``secret_token`` header, compared in constant time.

    Telegram does not sign the body; it echoes back a secret we set on
    ``setWebhook``. That is weaker than Slack's scheme — which is exactly why
    the ack token matters here, since the header alone says nothing about
    *which* incident the update refers to.
    """
    if not expected_secret or not provided:
        return False
    return hmac.compare_digest(expected_secret, provided)
