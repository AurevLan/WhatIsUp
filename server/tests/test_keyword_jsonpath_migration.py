"""Migration regression test — plan cap v2, 6f-2 (F5).

`keyword`/`json_path` disappear from `CheckType`. The one live `keyword`
monitor on the real instance must survive migration `a6f2b3c4d5e6` as an
`http` monitor that still checks *exactly* the same thing: same URL, same
keyword, same negate flag. This loads the migration module directly (it
lives under `alembic/versions/`, outside the `whatisup` package) and drives
its extracted helper functions against a throwaway SQLite database built
from the real ORM metadata — not the full Alembic upgrade chain, which is
Postgres-oriented (partitions, JSONB) and out of reach for a fast unit test.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa

from whatisup.models import Base

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "a6f2b3c4d5e6_keyword_jsonpath_as_http_assertions.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_migration_6f2_under_test", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fresh_sqlite_engine() -> sa.engine.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _insert_monitor(conn: sa.engine.Connection, monitors: sa.Table, **overrides) -> uuid.UUID:
    monitor_id = uuid.uuid4()
    values = {
        "id": monitor_id,
        "name": "monitor",
        "url": "https://example.com",
        "owner_id": uuid.uuid4(),
        "check_type": "http",
    }
    values.update(overrides)
    conn.execute(monitors.insert().values(**values))
    return monitor_id


def _fetch(conn: sa.engine.Connection, monitors: sa.Table, monitor_id: uuid.UUID):
    return conn.execute(sa.select(monitors).where(monitors.c.id == monitor_id)).one()


def test_live_keyword_monitor_survives_as_http_with_same_assertion() -> None:
    """The point of this lot: a monitor that checked '"status": "ok"' in the
    body before the migration must check the exact same thing after it."""
    migration = _load_migration()
    engine = _fresh_sqlite_engine()
    monitors = Base.metadata.tables["monitors"]

    with engine.begin() as conn:
        monitor_id = _insert_monitor(
            conn,
            monitors,
            name="Site vitrine",
            check_type="keyword",
            keyword='"status": "ok"',
            keyword_negate=False,
        )

        migration._retype_keyword_and_json_path_monitors(conn)

        row = _fetch(conn, monitors, monitor_id)
        assert row.check_type == "http"
        # The assertion itself — the thing the operator actually configured —
        # is untouched: same keyword, same negate flag, so the probe (which
        # never gates the keyword check on check_type) evaluates it exactly
        # as before.
        assert row.keyword == '"status": "ok"'
        assert row.keyword_negate is False


def test_json_path_monitor_migrates_to_http_too() -> None:
    migration = _load_migration()
    engine = _fresh_sqlite_engine()
    monitors = Base.metadata.tables["monitors"]

    with engine.begin() as conn:
        monitor_id = _insert_monitor(
            conn,
            monitors,
            check_type="json_path",
            expected_json_path="$.status",
            expected_json_value="ok",
        )

        migration._retype_keyword_and_json_path_monitors(conn)

        row = _fetch(conn, monitors, monitor_id)
        assert row.check_type == "http"
        assert row.expected_json_path == "$.status"
        assert row.expected_json_value == "ok"


def test_untouched_check_types_are_not_migrated() -> None:
    migration = _load_migration()
    engine = _fresh_sqlite_engine()
    monitors = Base.metadata.tables["monitors"]

    with engine.begin() as conn:
        tcp_id = _insert_monitor(conn, monitors, check_type="tcp", tcp_port=443)
        http_id = _insert_monitor(conn, monitors, check_type="http")

        migration._retype_keyword_and_json_path_monitors(conn)

        assert _fetch(conn, monitors, tcp_id).check_type == "tcp"
        assert _fetch(conn, monitors, http_id).check_type == "http"


def test_downgrade_restores_keyword_check_type() -> None:
    migration = _load_migration()
    engine = _fresh_sqlite_engine()
    monitors = Base.metadata.tables["monitors"]

    with engine.begin() as conn:
        monitor_id = _insert_monitor(
            conn,
            monitors,
            check_type="keyword",
            keyword="healthy",
            keyword_negate=True,
        )
        migration._retype_keyword_and_json_path_monitors(conn)
        assert _fetch(conn, monitors, monitor_id).check_type == "http"

        migration._restore_keyword_and_json_path_check_types(conn)

        row = _fetch(conn, monitors, monitor_id)
        assert row.check_type == "keyword"
        assert row.keyword == "healthy"
        assert row.keyword_negate is True


def test_downgrade_prefers_json_path_when_both_assertions_are_set() -> None:
    """A new capability this lot adds: an http monitor can carry *both* a
    keyword and a json_path assertion at once — something the old two-type
    model never allowed. Downgrading it must not silently drop the json_path
    half, since the old checker only gated json_path fields on check_type
    (the keyword check ran unconditionally either way — see http.py)."""
    migration = _load_migration()
    engine = _fresh_sqlite_engine()
    monitors = Base.metadata.tables["monitors"]

    with engine.begin() as conn:
        monitor_id = _insert_monitor(
            conn,
            monitors,
            check_type="http",
            keyword="healthy",
            expected_json_path="$.status",
            expected_json_value="ok",
        )

        migration._restore_keyword_and_json_path_check_types(conn)

        row = _fetch(conn, monitors, monitor_id)
        assert row.check_type == "json_path"
        assert row.keyword == "healthy"
        assert row.expected_json_path == "$.status"
