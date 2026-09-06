"""Plan cap V2, étape 5b — status page announcements, decoupled from `Incident`.

Decisions under test (see plan_cap_v2.md § 5b and CLAUDE.md "Deux familles
d'incidents"):
- A `StatusAnnouncement` is a human narration on a group's public status
  page — never an `Incident`. Creating, updating, threading, or closing one
  must leave uptime/SLA/incident computation byte-for-byte unchanged.
- It appears on its own group's public page only, never another group's.
- Its update thread renders in order; a closed announcement stays visible
  but is not presented as active.
- Admin CRUD is guarded by the same group-visibility rule as every other
  group-scoped resource (owner, or team member — never a stranger).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.incident import Incident
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_group_and_monitor(
    client: AsyncClient, token: str, *, slug: str, monitor_name: str
) -> tuple[str, str]:
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={"name": slug, "public_slug": slug},
            headers=_auth(token),
        )
    ).json()
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": monitor_name,
                "url": "https://example.com",
                "group_id": grp["id"],
            },
            headers=_auth(token),
        )
    ).json()
    return grp["id"], mon["id"]


async def _create_announcement(
    client: AsyncClient,
    token: str,
    group_id: str,
    *,
    title: str = "Investigating reported slowness",
    status: str = "investigating",
    message: str = "Users report slowness; probes see nothing yet.",
) -> dict:
    resp = await client.post(
        f"/api/v1/groups/{group_id}/announcements",
        json={"title": title, "status": status, "message": message},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Admin CRUD ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_announcement_seeds_first_update(client: AsyncClient, user_token: str) -> None:
    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-create", monitor_name="AnnMon1"
    )
    ann = await _create_announcement(client, user_token, group_id)
    assert ann["title"] == "Investigating reported slowness"
    assert ann["status"] == "investigating"
    assert ann["ended_at"] is None
    assert len(ann["updates"]) == 1
    assert ann["updates"][0]["message"] == "Users report slowness; probes see nothing yet."
    assert ann["updates"][0]["status"] == "investigating"


@pytest.mark.asyncio
async def test_list_announcements(client: AsyncClient, user_token: str) -> None:
    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-list", monitor_name="AnnMon2"
    )
    await _create_announcement(client, user_token, group_id, title="First")
    await _create_announcement(client, user_token, group_id, title="Second")

    resp = await client.get(f"/api/v1/groups/{group_id}/announcements", headers=_auth(user_token))
    assert resp.status_code == 200
    titles = {a["title"] for a in resp.json()}
    assert titles == {"First", "Second"}


@pytest.mark.asyncio
async def test_update_thread_appends_in_order(client: AsyncClient, user_token: str) -> None:
    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-thread", monitor_name="AnnMon3"
    )
    ann = await _create_announcement(client, user_token, group_id)

    resp1 = await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/updates",
        json={"status": "identified", "message": "Root cause found.", "is_public": True},
        headers=_auth(user_token),
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/updates",
        json={"status": "resolved", "message": "Fixed.", "is_public": True},
        headers=_auth(user_token),
    )
    assert resp2.status_code == 201

    listed = (
        await client.get(f"/api/v1/groups/{group_id}/announcements", headers=_auth(user_token))
    ).json()
    ann_out = next(a for a in listed if a["id"] == ann["id"])
    # Initial post + 2 thread entries, oldest first.
    assert [u["message"] for u in ann_out["updates"]] == [
        "Users report slowness; probes see nothing yet.",
        "Root cause found.",
        "Fixed.",
    ]
    # The announcement's own current state tracks the latest post.
    assert ann_out["status"] == "resolved"


@pytest.mark.asyncio
async def test_close_announcement(client: AsyncClient, user_token: str) -> None:
    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-close", monitor_name="AnnMon4"
    )
    ann = await _create_announcement(client, user_token, group_id)

    close_resp = await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/close",
        headers=_auth(user_token),
    )
    assert close_resp.status_code == 200
    assert close_resp.json()["ended_at"] is not None

    # Closing twice is rejected rather than silently no-op-ing.
    second_close = await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/close",
        headers=_auth(user_token),
    )
    assert second_close.status_code == 400

    # Cannot post to a closed announcement.
    post_after_close = await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/updates",
        json={"status": "resolved", "message": "Too late.", "is_public": True},
        headers=_auth(user_token),
    )
    assert post_after_close.status_code == 400

    # Still consultable, not presented as active.
    listed = (
        await client.get(f"/api/v1/groups/{group_id}/announcements", headers=_auth(user_token))
    ).json()
    ann_out = next(a for a in listed if a["id"] == ann["id"])
    assert ann_out["ended_at"] is not None


@pytest.mark.asyncio
async def test_update_title(client: AsyncClient, user_token: str) -> None:
    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-title", monitor_name="AnnMon5"
    )
    ann = await _create_announcement(client, user_token, group_id, title="Typo")
    resp = await client.patch(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}",
        json={"title": "Fixed title"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Fixed title"


# ── Cross-tenant visibility ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_other_user_cannot_create_or_list_announcements(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    other = User(
        email="other-tenant@test.com",
        username="other-tenant",
        hashed_password=hash_password("OtherPass1!"),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(other)
    await db_session.flush()
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": other.email, "password": "OtherPass1!"},
    )
    other_token = login.json()["access_token"]

    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-tenant", monitor_name="AnnMon6"
    )

    create_resp = await client.post(
        f"/api/v1/groups/{group_id}/announcements",
        json={"title": "Hijack", "status": "investigating", "message": "x"},
        headers=_auth(other_token),
    )
    assert create_resp.status_code == 403

    list_resp = await client.get(
        f"/api/v1/groups/{group_id}/announcements", headers=_auth(other_token)
    )
    assert list_resp.status_code == 403


# ── Public page ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_public_status_shows_announcement_for_own_group_only(
    client: AsyncClient, user_token: str
) -> None:
    group_a, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-pub-a", monitor_name="PubMonA"
    )
    group_b, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-pub-b", monitor_name="PubMonB"
    )
    await _create_announcement(client, user_token, group_a, title="Only on A")

    resp_a = await client.get("/api/v1/public/pages/ann-pub-a/status")
    assert resp_a.status_code == 200
    titles_a = [a["title"] for a in resp_a.json()["announcements"]]
    assert titles_a == ["Only on A"]

    resp_b = await client.get("/api/v1/public/pages/ann-pub-b/status")
    assert resp_b.status_code == 200
    assert resp_b.json()["announcements"] == []
    assert "Only on A" not in resp_b.text


@pytest.mark.asyncio
async def test_public_status_thread_order_and_privacy(client: AsyncClient, user_token: str) -> None:
    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-pub-thread", monitor_name="PubMonThread"
    )
    ann = await _create_announcement(client, user_token, group_id, message="Public post one.")

    await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/updates",
        json={"status": "investigating", "message": "Internal-only note.", "is_public": False},
        headers=_auth(user_token),
    )
    await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/updates",
        json={"status": "resolved", "message": "Public post two.", "is_public": True},
        headers=_auth(user_token),
    )

    resp = await client.get("/api/v1/public/pages/ann-pub-thread/status")
    assert resp.status_code == 200
    payload = resp.json()["announcements"][0]
    # Private update never leaks, and order is preserved.
    assert [u["message"] for u in payload["updates"]] == ["Public post one.", "Public post two."]
    assert "Internal-only note." not in resp.text


@pytest.mark.asyncio
async def test_public_status_closed_announcement_not_presented_as_active(
    client: AsyncClient, user_token: str
) -> None:
    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="ann-pub-closed", monitor_name="PubMonClosed"
    )
    ann = await _create_announcement(client, user_token, group_id)
    await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/close",
        headers=_auth(user_token),
    )

    resp = await client.get("/api/v1/public/pages/ann-pub-closed/status")
    assert resp.status_code == 200
    payload = resp.json()["announcements"][0]
    assert payload["is_active"] is False
    assert payload["ended_at"] is not None


# ── The test that matters: zero impact on stats ─────────────────────────────


@pytest.mark.asyncio
async def test_announcement_lifecycle_does_not_change_stats(
    client: AsyncClient, user_token: str, db_session: AsyncSession, fake_redis
) -> None:
    """Full lifecycle (create → thread → resolve-post → close) around a
    monitor with a mixed up/down history must not move uptime, SLA, or the
    incident count by a single bit. This is the regression the decoupling
    from `Incident` (plan_cap_v2.md § 5b) exists to prevent — see CLAUDE.md
    "Deux familles d'incidents" / the C-4 saga it explicitly avoids replaying.
    """
    from whatisup.services.stats import (
        compute_daily_history_bulk,
        compute_uptime,
        compute_uptime_bulk,
    )

    group_id, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="ann-stats", monitor_name="StatsMon"
    )
    monitor_uuid = uuid.UUID(monitor_id)

    now = datetime.now(UTC)
    for i in range(20):
        check_status = CheckStatus.down if i % 5 == 0 else CheckStatus.up
        db_session.add(
            CheckResult(
                id=uuid.uuid4(),
                monitor_id=monitor_uuid,
                checked_at=now - timedelta(minutes=i),
                status=check_status,
                response_time_ms=120.0,
            )
        )
    await db_session.commit()

    async def snapshot() -> tuple[dict, dict, list]:
        await fake_redis.flushall()
        uptime = await compute_uptime(db_session, monitor_uuid, period_hours=24)
        bulk = await compute_uptime_bulk(db_session, [monitor_uuid], period_hours=24)
        history = await compute_daily_history_bulk(db_session, [monitor_uuid], days=90)
        return uptime.model_dump(), bulk, history

    before = await snapshot()

    ann = await _create_announcement(client, user_token, group_id)
    await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/updates",
        json={"status": "identified", "message": "Narrowed it down.", "is_public": True},
        headers=_auth(user_token),
    )
    await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/updates",
        json={"status": "resolved", "message": "All clear.", "is_public": True},
        headers=_auth(user_token),
    )
    await client.post(
        f"/api/v1/groups/{group_id}/announcements/{ann['id']}/close",
        headers=_auth(user_token),
    )

    after = await snapshot()
    assert before == after

    # No Incident was ever created — the whole point of not making this an
    # `Incident` in the first place.
    incident_count = (
        await db_session.execute(
            select(func.count()).select_from(Incident).where(Incident.monitor_id == monitor_uuid)
        )
    ).scalar_one()
    assert incident_count == 0

    # The public read-model agrees: no incidents, unchanged uptime figure.
    status_resp = await client.get("/api/v1/public/pages/ann-stats/status")
    assert status_resp.json()["incidents_30d"] == []
    monitors_resp = await client.get("/api/v1/public/pages/ann-stats/monitors")
    assert monitors_resp.json()[0]["uptime_24h"] == before[0]["uptime_percent"]
