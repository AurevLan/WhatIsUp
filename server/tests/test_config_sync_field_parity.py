"""Parity gate: `config_sync._MONITOR_EXPORT_FIELDS` vs `Monitor.__table__.columns`.

`_MONITOR_EXPORT_FIELDS` is a hand-maintained *allowlist* — the opposite of
`api/v1/monitors/import_export.py`'s `/monitors/export` endpoint, which
allowlists via the `MonitorOut` schema and only *denylists* a few known
runtime fields (`_EXPORT_STRIP_FIELDS`). An allowlist fails silently: a new
`Monitor` column is simply absent from every IaC export/import until someone
remembers to add it here — no error, no failing test, just a config that
quietly doesn't round-trip.

This test computes the real diff against `Monitor.__table__.columns` and
requires every column to be *either* in `_MONITOR_EXPORT_FIELDS` *or* in the
exclusion list below, with a reason. Adding a column without touching either
side now fails here instead of shipping silently — see
`test_check_type_coverage.py` / `test_condition_registry.py` for the same
pattern applied to `CheckType` and `AlertCondition`.
"""

from __future__ import annotations

from whatisup.models.monitor import Monitor
from whatisup.services.config_sync import _MONITOR_EXPORT_FIELDS

# Columns deliberately absent from the IaC export/import — every one is a
# conscious choice, not an oversight. Grouped by reason:
_EXCLUDED_COLUMNS = {
    # Identity / bookkeeping — meaningless (or actively wrong) to round-trip
    # across a git-tracked config file.
    "id",
    "created_at",
    "updated_at",
    # Ownership — re-assigned to the importing user at import time
    # (`import_config`'s `owner_id=user.id`); portable IaC must not carry a
    # foreign owner/team id across tenants.
    "owner_id",
    "team_id",
    # Resolved by name instead of by raw id: `export_config` emits `"group"`
    # (the group's `name`) and `import_config` resolves it back through
    # `group_name_to_id` — the same reason `owner_id`/`team_id` are excluded,
    # a raw `group_id` UUID isn't portable across a re-import either.
    "group_id",
    # Server-generated, globally unique, regenerated on demand — not
    # something a config file should pin (mirrors `_EXPORT_STRIP_FIELDS` in
    # `api/v1/monitors/import_export.py`, the other export path).
    "heartbeat_token",
    # Runtime state / computed baselines — recomputed by the app after
    # import, never user-authored config. Also excluded by
    # `api/v1/monitors/import_export.py`'s `_EXPORT_STRIP_FIELDS`, which this
    # list is deliberately kept consistent with.
    "last_heartbeat_at",
    "schema_baseline",
    "schema_baseline_updated_at",
    "dns_baseline_ips",
}


def test_every_monitor_column_is_exported_or_explicitly_excluded() -> None:
    all_columns = set(Monitor.__table__.columns.keys())
    covered = set(_MONITOR_EXPORT_FIELDS) | _EXCLUDED_COLUMNS

    missing = all_columns - covered
    assert missing == set(), (
        "Monitor column(s) neither exported by config_sync nor explicitly "
        f"excluded — silently dropped from every IaC export/import: {missing}. "
        "Add to _MONITOR_EXPORT_FIELDS (if it's user config) or to "
        "_EXCLUDED_COLUMNS in this test (with a reason, if it's runtime state)."
    )


def test_export_fields_are_real_columns() -> None:
    """Catches a typo the other way — a listed field that doesn't exist would
    silently export/import as `None` via `getattr(m, field, None)` instead of
    erroring (`config_sync.export_config`'s `getattr(m, field, None)`)."""
    all_columns = set(Monitor.__table__.columns.keys())
    bogus = set(_MONITOR_EXPORT_FIELDS) - all_columns
    assert bogus == set()


def test_excluded_columns_are_real_and_not_double_counted() -> None:
    """The exclusion list itself must stay accurate: no stale entry for a
    renamed/removed column, and no overlap with the export allowlist (which
    would make the exclusion's documented reason misleading)."""
    all_columns = set(Monitor.__table__.columns.keys())
    assert _EXCLUDED_COLUMNS <= all_columns
    assert _EXCLUDED_COLUMNS.isdisjoint(_MONITOR_EXPORT_FIELDS)
