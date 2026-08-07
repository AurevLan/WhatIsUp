"""check_results partition helpers (plan V2, A-1) — backend-agnostic parts.

The DDL itself needs a real PostgreSQL and lives in ``test_partitions_pg.py``
(run by the ``Alembic migrations`` CI job). What is covered here is everything
that decides *which* partition gets created or destroyed — the arithmetic and
the bound parsing — plus the guarantee that none of it fires on SQLite.

The bound parser deserves direct tests because it is the last thing standing
between the retention job and a ``DROP TABLE`` on live data: anything it cannot
date must come back as "not droppable".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.core.database as db_mod
import whatisup.services.retention as retention_mod
from tests.test_background_services import _FactoryStub
from whatisup.core import partitions as p
from whatisup.models.monitor import Monitor
from whatisup.models.user import User
from whatisup.services.retention import purge_old_results

# ── Month arithmetic ─────────────────────────────────────────────────────────


def test_month_start_normalises_to_first_instant_utc() -> None:
    assert p.month_start(datetime(2026, 8, 6, 13, 45, 12, 7, tzinfo=UTC)) == datetime(
        2026, 8, 1, tzinfo=UTC
    )


def test_month_start_converts_other_timezones() -> None:
    # 2026-09-01 00:30 in UTC+2 is still August in UTC.
    tz = timezone(timedelta(hours=2))
    assert p.month_start(datetime(2026, 9, 1, 0, 30, tzinfo=tz)) == datetime(2026, 8, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
        # 31-day month followed by a 28-day one, and the year rollover: the
        # "+32 days then floor" trick has to survive both.
        (datetime(2026, 1, 31, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
        (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)),
        (datetime(2026, 12, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ],
)
def test_next_month(start: datetime, expected: datetime) -> None:
    assert p.next_month(start) == expected


def test_twelve_consecutive_months_are_distinct_and_ordered() -> None:
    start = datetime(2026, 3, 1, tzinfo=UTC)
    names = []
    for _ in range(14):
        names.append(p.partition_name(start))
        start = p.next_month(start)
    assert len(set(names)) == 14
    assert names[:3] == [
        "check_results_2026_03",
        "check_results_2026_04",
        "check_results_2026_05",
    ]
    assert names[10] == "check_results_2027_01"


# ── Partition bound parsing ──────────────────────────────────────────────────


def test_parse_upper_bound_monthly() -> None:
    bound = "FOR VALUES FROM ('2026-08-01 00:00:00+00') TO ('2026-09-01 00:00:00+00')"
    assert p._parse_upper_bound(bound) == datetime(2026, 9, 1, tzinfo=UTC)


def test_parse_upper_bound_legacy_open_lower_end() -> None:
    bound = "FOR VALUES FROM (MINVALUE) TO ('2026-09-01 00:00:00+00')"
    assert p._parse_upper_bound(bound) == datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "bound",
    [
        "DEFAULT",
        "FOR VALUES FROM ('2026-08-01 00:00:00+00') TO (MAXVALUE)",
        "FOR VALUES FROM ('2026-08-01 00:00:00+00') TO ('not-a-date')",
        "",
        "gibberish",
    ],
)
def test_unparseable_bounds_are_never_droppable(bound: str) -> None:
    """None means "cannot prove it expired" — the retention job must skip it."""
    assert p._parse_upper_bound(bound) is None


# ── No-ops outside PostgreSQL ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_helpers_are_noops_on_sqlite(service_db: AsyncSession) -> None:
    assert await p.list_check_result_partitions(service_db) == []
    assert await p.ensure_check_result_partitions(service_db) == []
    assert await p.drop_expired_check_result_partitions(service_db, datetime.now(UTC)) == []


def test_include_object_filter_is_inert_on_sqlite() -> None:
    class _Conn:
        class dialect:  # noqa: D106
            name = "sqlite"

    include = p.make_alembic_include_object(_Conn())
    assert include(None, "check_results_2026_08", "table", True, None) is True


def test_include_object_hides_reflected_partitions_only() -> None:
    class _Result:
        @staticmethod
        def all():
            return [("check_results_2026_08",), ("check_results_legacy",)]

    class _Conn:
        class dialect:  # noqa: D106
            name = "postgresql"

        @staticmethod
        def execute(*_args, **_kwargs):
            return _Result()

    include = p.make_alembic_include_object(_Conn())
    # Partitions found by reflection: hidden, otherwise autogenerate proposes
    # to drop them and the model-drift gate fails on a correct schema.
    assert include(None, "check_results_2026_08", "table", True, None) is False
    assert include(None, "check_results_legacy", "table", True, None) is False
    # The parent table and everything else stay visible.
    assert include(None, "check_results", "table", True, None) is True
    assert include(None, "monitors", "table", True, None) is True
    # Objects coming from the model side are never filtered.
    assert include(None, "check_results_2026_08", "table", False, None) is True


def test_include_object_hides_indexes_of_hidden_partitions() -> None:
    class _Result:
        @staticmethod
        def all():
            return [("check_results_2026_08",)]

    class _Conn:
        class dialect:  # noqa: D106
            name = "postgresql"

        @staticmethod
        def execute(*_args, **_kwargs):
            return _Result()

    class _Index:
        def __init__(self, table_name: str):
            self.table = type("T", (), {"name": table_name})()

    include = p.make_alembic_include_object(_Conn())
    assert include(_Index("check_results_2026_08"), "some_idx", "index", True, None) is False
    parent_idx = _Index("check_results")
    assert include(parent_idx, "ix_check_results_monitor_checked", "index", True, None) is True


# ── Retention: which cutoff reaches the partition dropper ────────────────────


@pytest_asyncio.fixture
async def retention_session(service_db: AsyncSession, monkeypatch):
    monkeypatch.setattr(db_mod, "_async_session_factory", _FactoryStub(service_db))
    return service_db


@pytest.mark.asyncio
async def test_partition_cutoff_uses_the_longest_retention_in_force(
    retention_session: AsyncSession, monkeypatch
) -> None:
    """A monitor keeping a year of history must protect the whole partition.

    Partitions hold every monitor's rows side by side, so the drop can only be
    justified by the *longest* retention configured anywhere. Using the global
    one would silently destroy history a user explicitly asked to keep.
    """
    owner = User(email="ret@example.com", username="retuser", hashed_password="x")
    retention_session.add(owner)
    await retention_session.flush()
    retention_session.add_all(
        [
            Monitor(name="keep-a-year", url="http://a", owner_id=owner.id, data_retention_days=365),
            Monitor(name="keep-a-week", url="http://b", owner_id=owner.id, data_retention_days=7),
        ]
    )
    await retention_session.flush()

    captured: dict[str, datetime] = {}

    async def _fake_drop(db, cutoff):
        captured["cutoff"] = cutoff
        return []

    monkeypatch.setattr(retention_mod, "drop_expired_check_result_partitions", _fake_drop)

    before = datetime.now(UTC)
    await purge_old_results(90)

    assert "cutoff" in captured
    age = before - captured["cutoff"]
    assert timedelta(days=364) < age < timedelta(days=366)


@pytest.mark.asyncio
async def test_partition_cutoff_falls_back_to_the_global_retention(
    retention_session: AsyncSession, monkeypatch
) -> None:
    captured: dict[str, datetime] = {}

    async def _fake_drop(db, cutoff):
        captured["cutoff"] = cutoff
        return []

    monkeypatch.setattr(retention_mod, "drop_expired_check_result_partitions", _fake_drop)

    before = datetime.now(UTC)
    await purge_old_results(30)

    age = before - captured["cutoff"]
    assert timedelta(days=29) < age < timedelta(days=31)


@pytest.mark.asyncio
async def test_retention_disabled_drops_nothing(
    retention_session: AsyncSession, monkeypatch
) -> None:
    """``data_retention_days = 0`` means keep forever — including partitions."""
    called = False

    async def _fake_drop(db, cutoff):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(retention_mod, "drop_expired_check_result_partitions", _fake_drop)
    assert await purge_old_results(0) == 0
    assert called is False
