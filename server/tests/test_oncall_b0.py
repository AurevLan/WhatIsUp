"""On-call rotations, escalation policies and contacts — B-0 model + API (plan V2).

Coverage is weighted towards the two hazards this module introduces, because
both fail silently rather than loudly:

- **Borrowed carriers** — referencing another tenant's ``AlertChannel`` would
  send messages through their Fernet-encrypted bot token.
- **Paging strangers** — putting an arbitrary user on a rotation or an
  escalation rung turns on-call config into an authenticated spam primitive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.user import User
from whatisup.schemas.oncall import (
    EscalationLevelIn,
    EscalationPolicyCreate,
    OnCallScheduleCreate,
    UserContactCreate,
)

TEST_PASSWORD = "TestPassword123!"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    """A second non-admin user sharing no team with `regular_user`."""
    u = User(
        email="stranger@test.com",
        username="stranger",
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def stranger_token(client: AsyncClient, stranger: User) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": stranger.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _make_channel(client: AsyncClient, token: str, name: str) -> str:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={"name": name, "type": "email", "config": {"to": ["ops@example.com"]}},
        headers=_auth(token),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# ── Schema-level validation ───────────────────────────────────────────────────


def test_messaging_contact_requires_a_carrier_channel() -> None:
    """Telegram/Slack need the bot token that only an AlertChannel holds."""
    with pytest.raises(ValueError, match="via_channel_id"):
        UserContactCreate(method="telegram", value="12345")

    # email/push carry themselves and must NOT name a channel
    with pytest.raises(ValueError, match="must be omitted"):
        UserContactCreate(method="email", value="a@b.com", via_channel_id=uuid.uuid4())

    assert UserContactCreate(method="email", value="a@b.com").via_channel_id is None
    assert (
        UserContactCreate(method="telegram", value="12345", via_channel_id=uuid.uuid4()).method
        == "telegram"
    )


def test_escalation_level_target_must_match_its_discriminator() -> None:
    """A level whose target_type disagrees with its FK would page nobody."""
    with pytest.raises(ValueError, match="target_schedule_id"):
        EscalationLevelIn(position=0, target_type="schedule", target_channel_id=uuid.uuid4())

    with pytest.raises(ValueError, match="target_channel_id"):
        EscalationLevelIn(position=0, target_type="channel")

    # Two targets at once is just as wrong as none.
    with pytest.raises(ValueError, match="exactly"):
        EscalationLevelIn(
            position=0,
            target_type="channel",
            target_channel_id=uuid.uuid4(),
            target_user_id=uuid.uuid4(),
        )


def test_escalation_positions_must_be_contiguous() -> None:
    """A ladder jumping 0 → 2 reads as "there is a level 1" to its author."""
    with pytest.raises(ValueError, match="contiguous"):
        EscalationPolicyCreate(
            name="gappy",
            levels=[
                EscalationLevelIn(
                    position=0, target_type="channel", target_channel_id=uuid.uuid4()
                ),
                EscalationLevelIn(
                    position=2, target_type="channel", target_channel_id=uuid.uuid4()
                ),
            ],
        )

    with pytest.raises(ValueError, match="unique"):
        EscalationPolicyCreate(
            name="dupe",
            levels=[
                EscalationLevelIn(
                    position=0, target_type="channel", target_channel_id=uuid.uuid4()
                ),
                EscalationLevelIn(
                    position=0, target_type="channel", target_channel_id=uuid.uuid4()
                ),
            ],
        )


def test_schedule_rejects_bad_timezone_and_handoff() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="unknown timezone"):
        OnCallScheduleCreate(name="s", start_at=now, timezone="Mars/Olympus")
    with pytest.raises(ValueError, match="HH:MM"):
        OnCallScheduleCreate(name="s", start_at=now, handoff_time="25:00")
    with pytest.raises(ValueError, match="only once"):
        OnCallScheduleCreate(
            name="s",
            start_at=now,
            participants=[
                {"user_id": (dup := uuid.uuid4()), "position": 0},
                {"user_id": dup, "position": 1},
            ],
        )


# ── Contacts ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contact_crud_is_scoped_to_its_owner(
    client: AsyncClient, user_token: str, stranger_token: str
) -> None:
    created = await client.post(
        "/api/v1/contacts/",
        json={"method": "email", "value": "oncall@example.com", "label": "perso"},
        headers=_auth(user_token),
    )
    assert created.status_code == 201
    contact_id = created.json()["id"]

    mine = await client.get("/api/v1/contacts/", headers=_auth(user_token))
    assert [c["value"] for c in mine.json()] == ["oncall@example.com"]

    # The other user must not see it, nor reach it by id.
    theirs = await client.get("/api/v1/contacts/", headers=_auth(stranger_token))
    assert theirs.json() == []
    for resp in (
        await client.patch(
            f"/api/v1/contacts/{contact_id}",
            json={"label": "stolen"},
            headers=_auth(stranger_token),
        ),
        await client.delete(f"/api/v1/contacts/{contact_id}", headers=_auth(stranger_token)),
    ):
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_contact_cannot_borrow_another_tenants_channel(
    client: AsyncClient, user_token: str, stranger_token: str
) -> None:
    """The carrier channel holds the bot token — it must not be borrowable."""
    victim_channel = await _make_channel(client, stranger_token, "Victim channel")

    resp = await client.post(
        "/api/v1/contacts/",
        json={"method": "telegram", "value": "999", "via_channel_id": victim_channel},
        headers=_auth(user_token),
    )
    assert resp.status_code in (403, 404), resp.text


# ── Schedules ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_roundtrip_with_participants(
    client: AsyncClient, user_token: str, regular_user: User
) -> None:
    start = datetime.now(UTC).replace(microsecond=0)
    resp = await client.post(
        "/api/v1/oncall/schedules/",
        json={
            "name": "Prod rotation",
            "timezone": "Europe/Paris",
            "rotation_type": "weekly",
            "handoff_time": "09:00",
            "start_at": start.isoformat(),
            "participants": [{"user_id": str(regular_user.id), "position": 0}],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["timezone"] == "Europe/Paris"
    assert [p["position"] for p in body["participants"]] == [0]

    schedule_id = body["id"]
    listed = await client.get("/api/v1/oncall/schedules/", headers=_auth(user_token))
    assert [s["id"] for s in listed.json()] == [schedule_id]

    # Clearing the roster is expressed as an explicit empty list.
    cleared = await client.patch(
        f"/api/v1/oncall/schedules/{schedule_id}",
        json={"participants": []},
        headers=_auth(user_token),
    )
    assert cleared.status_code == 200
    assert cleared.json()["participants"] == []


@pytest.mark.asyncio
async def test_cannot_put_a_stranger_on_a_rotation(
    client: AsyncClient, user_token: str, stranger: User
) -> None:
    """Otherwise on-call config becomes a way to page arbitrary accounts."""
    resp = await client.post(
        "/api/v1/oncall/schedules/",
        json={
            "name": "Spam rotation",
            "start_at": datetime.now(UTC).isoformat(),
            "participants": [{"user_id": str(stranger.id), "position": 0}],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_schedule_is_invisible_to_other_tenants(
    client: AsyncClient, user_token: str, stranger_token: str, regular_user: User
) -> None:
    created = await client.post(
        "/api/v1/oncall/schedules/",
        json={
            "name": "Private rotation",
            "start_at": datetime.now(UTC).isoformat(),
            "participants": [{"user_id": str(regular_user.id), "position": 0}],
        },
        headers=_auth(user_token),
    )
    schedule_id = created.json()["id"]

    assert (
        await client.get("/api/v1/oncall/schedules/", headers=_auth(stranger_token))
    ).json() == []
    got = await client.get(f"/api/v1/oncall/schedules/{schedule_id}", headers=_auth(stranger_token))
    assert got.status_code == 403


@pytest.mark.asyncio
async def test_override_window_and_cross_schedule_scoping(
    client: AsyncClient, user_token: str, stranger_token: str, regular_user: User
) -> None:
    created = await client.post(
        "/api/v1/oncall/schedules/",
        json={"name": "Rot", "start_at": datetime.now(UTC).isoformat()},
        headers=_auth(user_token),
    )
    schedule_id = created.json()["id"]

    now = datetime.now(UTC)
    inverted = await client.post(
        f"/api/v1/oncall/schedules/{schedule_id}/overrides",
        json={
            "user_id": str(regular_user.id),
            "starts_at": (now + timedelta(hours=2)).isoformat(),
            "ends_at": now.isoformat(),
        },
        headers=_auth(user_token),
    )
    assert inverted.status_code == 422

    ok = await client.post(
        f"/api/v1/oncall/schedules/{schedule_id}/overrides",
        json={
            "user_id": str(regular_user.id),
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=8)).isoformat(),
            "reason": "swap",
        },
        headers=_auth(user_token),
    )
    assert ok.status_code == 201, ok.text
    override_id = ok.json()["id"]

    # Another tenant must not reach the override, even knowing its id.
    denied = await client.delete(
        f"/api/v1/oncall/schedules/{schedule_id}/overrides/{override_id}",
        headers=_auth(stranger_token),
    )
    assert denied.status_code == 403


# ── Escalation policies ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_roundtrip_and_level_ordering(
    client: AsyncClient, user_token: str, regular_user: User
) -> None:
    channel_id = await _make_channel(client, user_token, "L1 channel")

    resp = await client.post(
        "/api/v1/escalation-policies/",
        json={
            "name": "Prod ladder",
            "repeat_count": 1,
            "levels": [
                {
                    "position": 1,
                    "delay_minutes": 15,
                    "target_type": "user",
                    "target_user_id": str(regular_user.id),
                },
                {
                    "position": 0,
                    "delay_minutes": 0,
                    "target_type": "channel",
                    "target_channel_id": channel_id,
                },
            ],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Levels come back ordered by position regardless of submission order.
    assert [level["position"] for level in body["levels"]] == [0, 1]
    assert body["levels"][1]["delay_minutes"] == 15


@pytest.mark.asyncio
async def test_policy_cannot_target_another_tenants_channel(
    client: AsyncClient, user_token: str, stranger_token: str
) -> None:
    victim_channel = await _make_channel(client, stranger_token, "Victim L1")

    resp = await client.post(
        "/api/v1/escalation-policies/",
        json={
            "name": "Borrowed ladder",
            "levels": [
                {"position": 0, "target_type": "channel", "target_channel_id": victim_channel}
            ],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.asyncio
async def test_policy_cannot_target_a_stranger(
    client: AsyncClient, user_token: str, stranger: User
) -> None:
    resp = await client.post(
        "/api/v1/escalation-policies/",
        json={
            "name": "Spam ladder",
            "levels": [{"position": 0, "target_type": "user", "target_user_id": str(stranger.id)}],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 403, resp.text


# ── AlertRule wiring ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_rule_accepts_and_returns_escalation_policy(
    client: AsyncClient, user_token: str
) -> None:
    channel_id = await _make_channel(client, user_token, "Rule channel")
    monitor = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "EscMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()
    policy = (
        await client.post(
            "/api/v1/escalation-policies/",
            json={
                "name": "Ladder",
                "levels": [
                    {"position": 0, "target_type": "channel", "target_channel_id": channel_id}
                ],
            },
            headers=_auth(user_token),
        )
    ).json()

    created = await client.post(
        "/api/v1/alerts/rules",
        json={
            "monitor_id": monitor["id"],
            "condition": "all_down",
            "channel_ids": [channel_id],
            "escalation_policy_id": policy["id"],
        },
        headers=_auth(user_token),
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["escalation_policy_id"] == policy["id"]

    # Detaching is an explicit null, not an omission.
    detached = await client.patch(
        f"/api/v1/alerts/rules/{created.json()['id']}",
        json={"escalation_policy_id": None},
        headers=_auth(user_token),
    )
    assert detached.status_code == 200
    assert detached.json()["escalation_policy_id"] is None


@pytest.mark.asyncio
async def test_alert_rule_cannot_borrow_another_tenants_policy(
    client: AsyncClient, user_token: str, stranger_token: str
) -> None:
    victim_channel = await _make_channel(client, stranger_token, "Victim ladder channel")
    victim_policy = (
        await client.post(
            "/api/v1/escalation-policies/",
            json={
                "name": "Victim ladder",
                "levels": [
                    {
                        "position": 0,
                        "target_type": "channel",
                        "target_channel_id": victim_channel,
                    }
                ],
            },
            headers=_auth(stranger_token),
        )
    ).json()

    my_channel = await _make_channel(client, user_token, "My channel")
    monitor = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "BorrowMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()

    resp = await client.post(
        "/api/v1/alerts/rules",
        json={
            "monitor_id": monitor["id"],
            "condition": "all_down",
            "channel_ids": [my_channel],
            "escalation_policy_id": victim_policy["id"],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.asyncio
async def test_alert_rule_persists_schedule_and_anomaly_threshold(
    client: AsyncClient, user_token: str
) -> None:
    """Regression: both fields were declared on the schema but never assigned.

    ``POST /alerts/rules`` and ``PATCH /alerts/rules/{id}`` accepted them and
    dropped them on the floor — only the matrix endpoint honoured them.
    """
    channel_id = await _make_channel(client, user_token, "Sched channel")
    monitor = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "SchedMon", "url": "https://example.com"},
            headers=_auth(user_token),
        )
    ).json()

    business_hours = {
        "timezone": "Europe/Paris",
        "days": [0, 1, 2, 3, 4],
        "start": "09:00",
        "end": "18:00",
        "offhours_suppress": True,
    }
    created = await client.post(
        "/api/v1/alerts/rules",
        json={
            "monitor_id": monitor["id"],
            "condition": "all_down",
            "channel_ids": [channel_id],
            "schedule": business_hours,
            "anomaly_zscore_threshold": 2.5,
        },
        headers=_auth(user_token),
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["schedule"] == business_hours
    assert created.json()["anomaly_zscore_threshold"] == 2.5

    updated = await client.patch(
        f"/api/v1/alerts/rules/{created.json()['id']}",
        json={"anomaly_zscore_threshold": 4.0},
        headers=_auth(user_token),
    )
    assert updated.status_code == 200
    assert updated.json()["anomaly_zscore_threshold"] == 4.0
