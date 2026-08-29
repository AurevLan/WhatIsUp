"""Coverage for background services that open their own DB sessions.

retention / heartbeat / renotify all reach for ``get_session_factory()`` at
runtime (they run from FastAPI lifespan loops, not request handlers).  We
patch the global session factory so they reuse the same in-memory test
session that owns the seed data, then assert on the side effects.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.core.database as db_mod
import whatisup.services.heartbeat as heartbeat_mod
from whatisup.models.alert import (
    AlertCondition,
    AlertRule,
)
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.heartbeat import check_heartbeats
from whatisup.services.renotify import check_renotify
from whatisup.services.retention import purge_old_results


class _SessionCtx:
    """Async context manager that hands out the same session across services."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_args) -> None:  # noqa: D401
        return None


class _FactoryStub:
    def __init__(self, session: AsyncSession):
        self._session = session

    def __call__(self) -> _SessionCtx:
        return _SessionCtx(self._session)


@pytest_asyncio.fixture
async def bg_session(service_db: AsyncSession, monkeypatch):
    """Force background-loop services to use the test session."""
    monkeypatch.setattr(db_mod, "_async_session_factory", _FactoryStub(service_db))
    # Stub _fire_alerts at the source so heartbeat (top-level import) and
    # renotify (lazy import) both see the no-op.
    from whatisup.services import heartbeat as hb_mod
    from whatisup.services import incident as inc_mod

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(hb_mod, "_fire_alerts", _noop)
    monkeypatch.setattr(inc_mod, "_fire_alerts", _noop)
    return service_db


# ── retention ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retention_disabled_when_zero(bg_session: AsyncSession) -> None:
    """retention_days=0 short-circuits without touching the DB."""
    deleted = await purge_old_results(0)
    assert deleted == 0


@pytest.mark.asyncio
async def test_retention_global_only(
    bg_session: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    monitor = Monitor(name="m-keep", url="http://x", owner_id=test_user.id)
    bg_session.add(monitor)
    await bg_session.flush()

    now = datetime.now(UTC)
    # 5 old + 2 recent
    for d in range(5):
        bg_session.add(
            CheckResult(
                monitor_id=monitor.id,
                probe_id=test_probe.id,
                status=CheckStatus.up,
                checked_at=now - timedelta(days=30 + d),
            )
        )
    for _ in range(2):
        bg_session.add(
            CheckResult(
                monitor_id=monitor.id,
                probe_id=test_probe.id,
                status=CheckStatus.up,
                checked_at=now - timedelta(hours=1),
            )
        )
    await bg_session.flush()

    deleted = await purge_old_results(7)
    assert deleted == 5

    remaining = (
        (await bg_session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_retention_per_monitor_override(
    bg_session: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    """A monitor with data_retention_days=2 evicts its own old rows."""
    short = Monitor(name="m-short", url="http://x", owner_id=test_user.id, data_retention_days=2)
    long_m = Monitor(name="m-long", url="http://y", owner_id=test_user.id)
    bg_session.add_all([short, long_m])
    await bg_session.flush()

    now = datetime.now(UTC)
    # 3 rows older than 2 days on the short-retention monitor
    for d in range(3):
        bg_session.add(
            CheckResult(
                monitor_id=short.id,
                probe_id=test_probe.id,
                status=CheckStatus.up,
                checked_at=now - timedelta(days=3 + d),
            )
        )
    # 1 row 5 days old on the long-retention monitor — well within global 30d
    bg_session.add(
        CheckResult(
            monitor_id=long_m.id,
            probe_id=test_probe.id,
            status=CheckStatus.up,
            checked_at=now - timedelta(days=5),
        )
    )
    await bg_session.flush()

    deleted = await purge_old_results(30)
    assert deleted == 3  # only the short-retention rows


# ── heartbeat ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_opens_incident_when_overdue(
    bg_session: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(
        name="hb-overdue",
        url="http://hb",
        owner_id=test_user.id,
        check_type="heartbeat",
        heartbeat_slug="overdue",
        heartbeat_token="tok-overdue",
        heartbeat_interval_seconds=60,
        heartbeat_grace_seconds=30,
        last_heartbeat_at=datetime.now(UTC) - timedelta(hours=2),
    )
    bg_session.add(monitor)
    await bg_session.flush()

    await check_heartbeats()

    inc = (
        await bg_session.execute(select(Incident).where(Incident.monitor_id == monitor.id))
    ).scalar_one_or_none()
    assert inc is not None
    assert inc.resolved_at is None
    assert inc.scope == IncidentScope.global_


@pytest.mark.asyncio
async def test_heartbeat_one_failing_monitor_does_not_lose_the_others(
    bg_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure mid-loop must not roll back the incidents already opened.

    With a single commit at the end of the loop it did: the session was closed
    without committing and every incident of that tick vanished, alert included
    — the exact bug `renotify.py` and `metric_alerts.py` already fixed by
    committing per item.
    """
    for idx in range(3):
        bg_session.add(
            Monitor(
                name=f"hb-isolation-{idx}",
                url="http://hb",
                owner_id=test_user.id,
                check_type="heartbeat",
                heartbeat_slug=f"isolation-{idx}",
                heartbeat_token=f"tok-isolation-{idx}",
                heartbeat_interval_seconds=60,
                heartbeat_grace_seconds=30,
                last_heartbeat_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
    await bg_session.flush()

    # Blow up on the second monitor the loop touches, whichever that is.
    # `bg_session` already stubs `_fire_alerts` to a no-op; only the ORM state
    # is off-limits here, since a rollback in the loop expires it.
    fired = {"n": 0}

    async def exploding_fire(*_args, **_kwargs):
        fired["n"] += 1
        if fired["n"] == 2:
            raise RuntimeError("channel dispatch blew up")
        return None

    monkeypatch.setattr(heartbeat_mod, "_fire_alerts", exploding_fire)

    commits = {"n": 0}
    real_commit = bg_session.commit

    async def counting_commit():
        commits["n"] += 1
        await real_commit()

    # `bg_session` is the *test's* session, wrapped in an outer SAVEPOINT by
    # conftest: letting the service's rollback through would unwind the whole
    # test (fixtures included), which says nothing about the loop. Count it
    # instead — that it fires exactly once is the point.
    rollbacks = {"n": 0}

    async def counting_rollback():
        rollbacks["n"] += 1

    monkeypatch.setattr(bg_session, "commit", counting_commit)
    monkeypatch.setattr(bg_session, "rollback", counting_rollback)

    await check_heartbeats()

    # Before the fix the exception escaped the loop: the third monitor was
    # never looked at, and the single trailing commit never ran — so the
    # incident already flushed for the first monitor was silently dropped.
    assert fired["n"] == 3, "the loop must keep going after one monitor fails"
    assert commits["n"] == 2, "the two healthy monitors are each committed on their own"
    assert rollbacks["n"] == 1, "only the failing monitor is rolled back"


@pytest.mark.asyncio
async def test_heartbeat_resolves_incident_when_back(
    bg_session: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(
        name="hb-back",
        url="http://hb",
        owner_id=test_user.id,
        check_type="heartbeat",
        heartbeat_slug="back",
        heartbeat_token="tok-back",
        heartbeat_interval_seconds=3600,
        heartbeat_grace_seconds=60,
        last_heartbeat_at=datetime.now(UTC),  # just pinged
    )
    bg_session.add(monitor)
    await bg_session.flush()

    inc = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    bg_session.add(inc)
    await bg_session.flush()

    await check_heartbeats()

    refreshed = await bg_session.get(Incident, inc.id)
    assert refreshed.resolved_at is not None
    assert refreshed.duration_seconds is not None and refreshed.duration_seconds >= 0


@pytest.mark.asyncio
async def test_heartbeat_ignores_disabled_monitor(
    bg_session: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(
        name="hb-disabled",
        url="http://hb",
        owner_id=test_user.id,
        check_type="heartbeat",
        heartbeat_slug="disabled",
        heartbeat_token="tok-disabled",
        heartbeat_interval_seconds=60,
        heartbeat_grace_seconds=30,
        enabled=False,
        last_heartbeat_at=datetime.now(UTC) - timedelta(days=1),
    )
    bg_session.add(monitor)
    await bg_session.flush()

    await check_heartbeats()

    incidents = (
        (await bg_session.execute(select(Incident).where(Incident.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert incidents == []


@pytest.mark.asyncio
async def test_heartbeat_caps_batch_and_defers_the_rest(
    bg_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fleet bigger than the per-tick cap must not drop the tail outright:
    the most overdue monitors (oldest ``last_heartbeat_at``) are checked
    first, and whichever doesn't fit this tick is checked as soon as a slot
    frees up — here, once one of the processed monitors recovers and its
    fresher ``last_heartbeat_at`` moves it to the back of the ordering."""
    from whatisup.core.config import get_settings

    monkeypatch.setattr(get_settings(), "heartbeat_max_monitors_per_run", 2)

    now = datetime.now(UTC)
    monitors = []
    for idx, hours_overdue in enumerate([3, 2, 1]):  # most overdue first, by construction
        monitor = Monitor(
            name=f"hb-cap-{idx}",
            url="http://hb",
            owner_id=test_user.id,
            check_type="heartbeat",
            heartbeat_slug=f"cap-{idx}",
            heartbeat_token=f"tok-cap-{idx}",
            heartbeat_interval_seconds=60,
            heartbeat_grace_seconds=30,
            last_heartbeat_at=now - timedelta(hours=hours_overdue),
        )
        bg_session.add(monitor)
        monitors.append(monitor)
    await bg_session.flush()

    async def _open_incident(monitor: Monitor) -> Incident | None:
        return (
            await bg_session.execute(select(Incident).where(Incident.monitor_id == monitor.id))
        ).scalar_one_or_none()

    await check_heartbeats()

    # The two most overdue (idx 0 and 1) got checked; the least overdue (idx 2)
    # is deferred, not lost.
    assert await _open_incident(monitors[0]) is not None
    assert await _open_incident(monitors[1]) is not None
    assert await _open_incident(monitors[2]) is None

    # idx0 recovers — its `last_heartbeat_at` refreshes, moving it to the back
    # of the ordering and freeing a slot for idx2 on the next tick.
    monitors[0].last_heartbeat_at = datetime.now(UTC)
    await bg_session.flush()

    await check_heartbeats()
    assert await _open_incident(monitors[2]) is not None


# ── renotify ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_renotify_skips_when_no_open_incidents(bg_session: AsyncSession) -> None:
    """Empty-DB shortcut path — must not raise."""
    await check_renotify()  # no monitors, no rules — just exit


@pytest.mark.asyncio
async def test_renotify_skips_monitor_without_renotify_rule(
    bg_session: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(name="m1", url="http://x", owner_id=test_user.id)
    bg_session.add(monitor)
    await bg_session.flush()

    bg_session.add(
        Incident(
            monitor_id=monitor.id,
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
    )
    # Rule exists but does NOT set renotify_after_minutes
    bg_session.add(
        AlertRule(
            owner_id=test_user.id,
            monitor_id=monitor.id,
            condition=AlertCondition.any_down,
        )
    )
    await bg_session.flush()

    # Should be a noop — no exception, no call to _fire_alerts (we asserted via stub).
    await check_renotify()


@pytest.mark.asyncio
async def test_renotify_fires_for_eligible_incident(
    bg_session: AsyncSession, test_user: User, monkeypatch
) -> None:
    """Open incident + rule with renotify_after_minutes triggers a dispatch."""
    monitor = Monitor(name="m2", url="http://x", owner_id=test_user.id)
    bg_session.add(monitor)
    await bg_session.flush()

    bg_session.add(
        Incident(
            monitor_id=monitor.id,
            started_at=datetime.now(UTC) - timedelta(minutes=15),
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
    )
    bg_session.add(
        AlertRule(
            owner_id=test_user.id,
            monitor_id=monitor.id,
            condition=AlertCondition.any_down,
            renotify_after_minutes=5,
        )
    )
    await bg_session.flush()

    calls = []

    from whatisup.services import incident as inc_mod

    async def _spy(*args, **kwargs):
        calls.append(kwargs.get("event_type"))

    monkeypatch.setattr(inc_mod, "_fire_alerts", _spy)

    await check_renotify()
    assert calls == ["incident_renotify"]


@pytest.mark.asyncio
async def test_renotify_failure_does_not_discard_prior_incidents(
    bg_session: AsyncSession, test_user: User, monkeypatch
) -> None:
    """R-4: per-incident commit — one incident failing must not roll back the
    alert events already recorded for incidents processed before it."""
    for name in ("r4-a", "r4-b"):
        monitor = Monitor(name=name, url="http://x", owner_id=test_user.id)
        bg_session.add(monitor)
        await bg_session.flush()
        bg_session.add(
            Incident(
                monitor_id=monitor.id,
                started_at=datetime.now(UTC) - timedelta(minutes=15),
                scope=IncidentScope.global_,
                affected_probe_ids=[],
            )
        )
        bg_session.add(
            AlertRule(
                owner_id=test_user.id,
                monitor_id=monitor.id,
                condition=AlertCondition.any_down,
                renotify_after_minutes=5,
            )
        )
    await bg_session.flush()

    from whatisup.services import incident as inc_mod

    calls = {"n": 0}
    marker = datetime.now(UTC) + timedelta(hours=1)

    async def _spy(db, incident, *args, **kwargs):
        calls["n"] += 1
        # Mutate DB state like the real dispatch does (AlertEvent writes),
        # then blow up on the second incident.
        incident.snooze_until = marker
        if calls["n"] == 2:
            raise RuntimeError("dispatch exploded")

    monkeypatch.setattr(inc_mod, "_fire_alerts", _spy)

    await check_renotify()  # must not raise

    persisted = (
        (await bg_session.execute(select(Incident).where(Incident.snooze_until.isnot(None))))
        .scalars()
        .all()
    )
    # First incident committed before the second one failed and rolled back.
    assert calls["n"] == 2
    assert len(persisted) == 1


@pytest.mark.asyncio
async def test_renotify_caps_batch_and_defers_the_rest(
    bg_session: AsyncSession, test_user: User, monkeypatch
) -> None:
    """More open, renotify-eligible incidents than the per-tick cap: the
    oldest (longest-open, most urgent) fire this tick, and the rest fire once
    an older one leaves the open set (acked/resolved) — nothing is skipped."""
    from whatisup.core.config import get_settings

    monkeypatch.setattr(get_settings(), "renotify_max_incidents_per_run", 2)

    now = datetime.now(UTC)
    incidents = []
    for idx, minutes_open in enumerate([30, 20, 10]):  # oldest first, by construction
        monitor = Monitor(name=f"renotify-cap-{idx}", url="http://x", owner_id=test_user.id)
        bg_session.add(monitor)
        await bg_session.flush()
        incident = Incident(
            monitor_id=monitor.id,
            started_at=now - timedelta(minutes=minutes_open),
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
        bg_session.add(incident)
        bg_session.add(
            AlertRule(
                owner_id=test_user.id,
                monitor_id=monitor.id,
                condition=AlertCondition.any_down,
                renotify_after_minutes=5,
            )
        )
        incidents.append(incident)
    await bg_session.flush()

    from whatisup.services import incident as inc_mod

    fired_for: list = []

    async def _spy(db, incident, *args, **kwargs):
        fired_for.append(incident.id)

    monkeypatch.setattr(inc_mod, "_fire_alerts", _spy)

    await check_renotify()
    assert fired_for == [incidents[0].id, incidents[1].id]

    # The oldest incident acks — it leaves the open set, freeing a slot. Reset
    # the spy log so the second tick's firings are read on their own: incident
    # 1 is still open and eligible, so it renotifies again on every tick —
    # that's unrelated to the cap and would otherwise muddy this assertion.
    incidents[0].acked_at = datetime.now(UTC)
    await bg_session.flush()
    fired_for.clear()

    await check_renotify()
    assert incidents[2].id in fired_for, "the deferred incident must get its turn once a slot frees"
