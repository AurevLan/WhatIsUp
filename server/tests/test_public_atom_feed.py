"""Plan cap V2, étape 5d — public Atom feed for a status page.

Covers incidents (5c scope — availability only), announcements with their
update thread (5b), and published maintenance windows (5a). The two
requirements that make this lot: the feed is generated with a real XML
serializer (`xml.etree.ElementTree`) so operator-authored text can never
break or inject into the document, and it must never republish the monitor
inventory closed off in 5c (URL, TCP port, DNS record type, final URL,
check_type).
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.result import CheckResult, CheckStatus

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_group(client: AsyncClient, token: str, *, name: str, slug: str) -> str:
    resp = await client.post(
        "/api/v1/groups/",
        json={"name": name, "public_slug": slug},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_monitor(
    client: AsyncClient, token: str, group_id: str, *, name: str, **extra
) -> str:
    payload = {"name": name, "url": "https://example.com", "group_id": group_id, **extra}
    resp = await client.post("/api/v1/monitors/", json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_incident(
    *, monitor_id: uuid.UUID, resolved: bool, verdict: str | None = None
) -> Incident:
    now = datetime.now(UTC)
    return Incident(
        id=uuid.uuid4(),
        monitor_id=monitor_id,
        started_at=now - timedelta(hours=1),
        resolved_at=now if resolved else None,
        duration_seconds=3600 if resolved else None,
        scope=IncidentScope.geographic,
        affected_probe_ids=[],
        network_verdict=verdict,
        network_verdict_computed_at=now if verdict else None,
    )


async def _get_feed(client: AsyncClient, slug: str) -> tuple[ET.Element, str]:
    resp = await client.get(f"/api/v1/public/pages/{slug}/feed.atom")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/atom+xml")
    root = ET.fromstring(resp.text)  # noqa: S314 — our own generated feed, not attacker input
    return root, resp.text


def _entries(root: ET.Element) -> list[ET.Element]:
    return root.findall(f"{ATOM_NS}entry")


def _child_text(entry: ET.Element, tag: str) -> str | None:
    el = entry.find(f"{ATOM_NS}{tag}")
    return el.text if el is not None else None


# ---------------------------------------------------------------------------
# The most important test of the lot: injection must stay data, not markup.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atom_feed_escapes_injected_xml(client: AsyncClient, user_token: str) -> None:
    """An announcement message containing `<`, `&`, `"` and `]]>` must
    produce a feed that (a) still parses as well-formed XML and (b) carries
    the content back verbatim as text — never interpreted as markup."""
    gid = await _make_group(client, user_token, name="InjectGrp", slug="inject-atom")

    malicious = 'Rolling <restart> upgrade & "quoted" value ]]> end <bogus>tag</bogus>'
    resp = await client.post(
        f"/api/v1/groups/{gid}/announcements",
        json={"title": "Maintenance notice", "status": "investigating", "message": malicious},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text

    root, raw = await _get_feed(client, "inject-atom")

    # The raw bytes must never contain an unescaped `<restart>` or `<bogus>`
    # sibling/child element — only the escaped form is acceptable.
    assert "<restart>" not in raw
    assert "<bogus>" not in raw

    entries = _entries(root)
    assert len(entries) == 1
    summary = _child_text(entries[0], "summary")
    assert summary is not None
    # Parsed back through a real XML parser, the content must be exactly
    # what was written — proof the injection was escaped, not interpreted.
    assert malicious in summary

    # No extra elements were smuggled in: the entry has exactly the fields
    # this endpoint emits, nothing injected by the payload.
    child_tags = {child.tag for child in entries[0]}
    allowed = ("id", "title", "updated", "published", "link", "summary")
    assert child_tags <= {f"{ATOM_NS}{t}" for t in allowed}


@pytest.mark.asyncio
async def test_atom_feed_escapes_maintenance_public_message(
    client: AsyncClient, user_token: str
) -> None:
    gid = await _make_group(client, user_token, name="InjectMaintGrp", slug="inject-maint-atom")
    now = datetime.now(UTC)
    resp = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "internal-runbook-name",
            "description": "internal detail",
            "public_message": "Downtime window & <script>alert(1)</script> ]]>",
            "group_id": gid,
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text

    root, raw = await _get_feed(client, "inject-maint-atom")
    assert "<script>" not in raw

    entries = _entries(root)
    assert len(entries) == 1
    summary = _child_text(entries[0], "summary")
    assert "Downtime window & <script>alert(1)</script> ]]>" in summary


# ---------------------------------------------------------------------------
# Non-leak: the inventory closed off in 5c must never resurface here.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atom_feed_never_leaks_monitor_inventory(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    gid = await _make_group(client, user_token, name="LeakAtomGrp", slug="leak-atom")

    http_id = await _make_monitor(
        client,
        user_token,
        gid,
        name="Storefront",
        url="https://nginx-front-02.internal.example.net/health",
    )
    tcp_id = await _make_monitor(
        client,
        user_token,
        gid,
        name="DB Replica",
        url="http://db-replica-07.internal.example.net",
        check_type="tcp",
        tcp_port=54321,
    )
    dns_id = await _make_monitor(
        client,
        user_token,
        gid,
        name="MX Record",
        url="http://mail.example.net",
        check_type="dns",
        dns_record_type="TXT",
        dns_expected_value="v=spf1-super-secret-marker",
    )

    # Open incidents on all three so they actually surface as feed entries —
    # an empty feed would pass this test trivially.
    db_session.add(_make_incident(monitor_id=uuid.UUID(http_id), resolved=False))
    db_session.add(_make_incident(monitor_id=uuid.UUID(tcp_id), resolved=False))
    db_session.add(_make_incident(monitor_id=uuid.UUID(dns_id), resolved=True))
    db_session.add(
        CheckResult(
            id=uuid.uuid4(),
            monitor_id=uuid.UUID(http_id),
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
            final_url="https://redirect-target-secret.internal.example.net/",
        )
    )
    await db_session.commit()

    _, raw = await _get_feed(client, "leak-atom")

    forbidden = [
        "nginx-front-02",
        "db-replica-07",
        "redirect-target-secret",
        "54321",
        "spf1-super-secret-marker",
        "tcp_port",
        "dns_record_type",
        "check_type",
        "final_url",
        "example.net",
    ]
    for needle in forbidden:
        assert needle not in raw, f"atom feed leaked {needle!r}"

    # Sanity: monitors are still named in the feed.
    for expected_name in ("Storefront", "DB Replica", "MX Record"):
        assert expected_name in raw


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atom_feed_scoped_per_group(client: AsyncClient, user_token: str) -> None:
    gid_a = await _make_group(client, user_token, name="FeedGroupA", slug="feed-group-a")
    gid_b = await _make_group(client, user_token, name="FeedGroupB", slug="feed-group-b")

    await client.post(
        f"/api/v1/groups/{gid_a}/announcements",
        json={"title": "Only A", "status": "investigating", "message": "A-only announcement"},
        headers=_auth(user_token),
    )
    await client.post(
        f"/api/v1/groups/{gid_b}/announcements",
        json={"title": "Only B", "status": "investigating", "message": "B-only announcement"},
        headers=_auth(user_token),
    )

    root_a, raw_a = await _get_feed(client, "feed-group-a")
    root_b, raw_b = await _get_feed(client, "feed-group-b")

    titles_a = {_child_text(e, "title") for e in _entries(root_a)}
    titles_b = {_child_text(e, "title") for e in _entries(root_b)}

    assert titles_a == {"Only A"}
    assert titles_b == {"Only B"}
    assert "Only B" not in raw_a
    assert "Only A" not in raw_b


# ---------------------------------------------------------------------------
# Stable ids, moving `updated`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atom_feed_entry_id_stable_and_updated_moves(
    client: AsyncClient, user_token: str, fake_redis: FakeRedis
) -> None:
    gid = await _make_group(client, user_token, name="StableIdGrp", slug="stable-id-atom")
    resp = await client.post(
        f"/api/v1/groups/{gid}/announcements",
        json={"title": "Ongoing work", "status": "investigating", "message": "Looking into it"},
        headers=_auth(user_token),
    )
    ann_id = resp.json()["id"]

    cache_key = f"whatisup:public:feed:{gid}"

    root1, _ = await _get_feed(client, "stable-id-atom")
    entry1 = _entries(root1)[0]
    id1 = _child_text(entry1, "id")
    updated1 = _child_text(entry1, "updated")

    # Bust the cache and post a follow-up update — the announcement's
    # `updated_at` bumps (see api/v1/status_announcements.py), which must be
    # reflected in the feed.
    await fake_redis.delete(cache_key)
    await client.post(
        f"/api/v1/groups/{gid}/announcements/{ann_id}/updates",
        json={"status": "monitoring", "message": "Mitigated, monitoring", "is_public": True},
        headers=_auth(user_token),
    )

    root2, _ = await _get_feed(client, "stable-id-atom")
    entry2 = _entries(root2)[0]
    id2 = _child_text(entry2, "id")
    updated2 = _child_text(entry2, "updated")

    assert id1 == id2
    assert updated1 != updated2


@pytest.mark.asyncio
async def test_atom_feed_is_cached(
    client: AsyncClient, user_token: str, fake_redis: FakeRedis
) -> None:
    gid = await _make_group(client, user_token, name="CacheAtomGrp", slug="cache-atom")
    await client.post(
        f"/api/v1/groups/{gid}/announcements",
        json={"title": "First", "status": "investigating", "message": "msg"},
        headers=_auth(user_token),
    )

    first = await client.get("/api/v1/public/pages/cache-atom/feed.atom")
    assert first.status_code == 200

    cache_key = f"whatisup:public:feed:{gid}"
    assert await fake_redis.exists(cache_key)

    # A second announcement stays invisible until the cache is evicted.
    await client.post(
        f"/api/v1/groups/{gid}/announcements",
        json={"title": "Second", "status": "investigating", "message": "msg2"},
        headers=_auth(user_token),
    )
    cached = await client.get("/api/v1/public/pages/cache-atom/feed.atom")
    root = ET.fromstring(cached.text)
    assert {_child_text(e, "title") for e in _entries(root)} == {"First"}

    await fake_redis.delete(cache_key)
    fresh = await client.get("/api/v1/public/pages/cache-atom/feed.atom")
    root = ET.fromstring(fresh.text)
    assert {_child_text(e, "title") for e in _entries(root)} == {"First", "Second"}
