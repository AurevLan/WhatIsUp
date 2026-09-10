"""Pre-configured alert matrix templates the user can apply in one click.

Each template is a ready-to-use set of alerting rules tuned for a common use case
(standard reliability, strict/paging setup, silent/low-noise). Channels are
intentionally left empty — the user still picks which channels fire after applying.
"""

from __future__ import annotations

from typing import Any

# Templates are keyed by check_type → list of templates.
# Each template has {id, name_key, description_key, rows: [{condition, ...params}]}.
# Conditions are only included when they are meaningful for the check_type.
#
# Plan cap v2, 6f (F1-conditions + F4) — `any_down`/`all_down` merged into
# `availability` (a quorum setting) and `response_time_above` /
# `response_time_above_baseline` / `anomaly_detection` merged into
# `latency_anomaly` (a sensitivity mode). A matrix row is one-per-condition,
# so a "strict" template that used to pair `all_down_immediate` (min_duration
# 0) with `any_down_quick` (min_duration 30) — two rows, two conditions — can
# no longer express both: they are now the same condition. The immediate,
# any-probe-down row (`availability_immediate`) subsumes the delayed one — it
# pages on strictly more situations, strictly sooner — so "strict" keeps only
# that single row. Likewise a "strict" template that paired an absolute
# latency row with a z-score row keeps only the absolute one; the statistical
# sensitivity mode remains available manually, just not pre-selected by a
# built-in template.

_COMMON_ROWS: dict[str, dict[str, Any]] = {
    "availability_immediate": {
        "condition": "availability",
        "min_duration_seconds": 0,
    },
    "availability_quick": {
        "condition": "availability",
        "min_duration_seconds": 60,
    },
    "availability_patient": {
        "condition": "availability",
        "min_duration_seconds": 300,
    },
    "ssl_expiry": {"condition": "ssl_expiry"},
    "latency_absolute_2s": {
        "condition": "latency_anomaly",
        "threshold_value": 2000,
        "min_duration_seconds": 120,
    },
    "latency_relative_3x": {
        "condition": "latency_anomaly",
        "baseline_factor": 3.0,
        "min_duration_seconds": 120,
    },
    "schema_drift": {"condition": "schema_drift"},
}


def _row(key: str, **overrides: Any) -> dict[str, Any]:
    base = dict(_COMMON_ROWS[key])
    base.update(overrides)
    return base


# Templates are declared per check_type. Conditions not supported by a given
# check_type are simply omitted — so a "strict" template for dns has fewer rows
# than a "strict" template for http.

_HTTP_STANDARD = [
    _row("availability_quick"),
    _row("ssl_expiry"),
    _row("latency_relative_3x"),
]
_HTTP_STRICT = [
    _row("availability_immediate"),
    _row("ssl_expiry"),
    _row("latency_absolute_2s"),
]
_HTTP_SILENT = [
    _row("availability_patient"),
    _row("ssl_expiry"),
]


TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "http": [
        {"id": "standard", "rows": _HTTP_STANDARD},
        {"id": "strict", "rows": _HTTP_STRICT},
        {"id": "silent", "rows": _HTTP_SILENT},
    ],
    "tcp": [
        {"id": "standard", "rows": [_row("availability_quick"), _row("latency_absolute_2s")]},
        {"id": "strict", "rows": [_row("availability_immediate")]},
        {"id": "silent", "rows": [_row("availability_patient")]},
    ],
    "dns": [
        {"id": "standard", "rows": [_row("availability_quick")]},
        {"id": "strict", "rows": [_row("availability_immediate")]},
        {"id": "silent", "rows": [_row("availability_patient")]},
    ],
    "keyword": [
        {"id": "standard", "rows": [_row("availability_quick")]},
        {"id": "strict", "rows": [_row("availability_immediate")]},
        {"id": "silent", "rows": [_row("availability_patient")]},
    ],
    "json_path": [
        {"id": "standard", "rows": [_row("availability_quick"), _row("schema_drift")]},
        {"id": "strict", "rows": [_row("availability_immediate"), _row("schema_drift")]},
        {"id": "silent", "rows": [_row("availability_patient")]},
    ],
    "scenario": [
        {
            "id": "standard",
            "rows": [
                _row("availability_quick"),
                _row("latency_absolute_2s", threshold_value=10000),
            ],
        },
        {
            "id": "strict",
            "rows": [
                _row("availability_immediate"),
                _row("latency_absolute_2s", threshold_value=5000),
            ],
        },
        {"id": "silent", "rows": [_row("availability_patient")]},
    ],
    "heartbeat": [
        {"id": "standard", "rows": [_row("availability_quick", min_duration_seconds=0)]},
        {
            "id": "strict",
            "rows": [_row("availability_quick", min_duration_seconds=0)],
        },
        {"id": "silent", "rows": [_row("availability_patient")]},
    ],
}


def get_templates(check_type: str) -> list[dict[str, Any]]:
    return TEMPLATES.get(check_type, TEMPLATES["http"])
