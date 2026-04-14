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

_COMMON_ROWS: dict[str, dict[str, Any]] = {
    "any_down_quick": {
        "condition": "any_down",
        "min_duration_seconds": 60,
        "renotify_after_minutes": 30,
    },
    "any_down_patient": {
        "condition": "any_down",
        "min_duration_seconds": 300,
        "renotify_after_minutes": 360,
    },
    "all_down_immediate": {
        "condition": "all_down",
        "min_duration_seconds": 0,
        "renotify_after_minutes": 15,
    },
    "ssl_expiry": {"condition": "ssl_expiry"},
    "response_time_above_2s": {
        "condition": "response_time_above",
        "threshold_value": 2000,
        "min_duration_seconds": 120,
    },
    "response_baseline_3x": {
        "condition": "response_time_above_baseline",
        "baseline_factor": 3.0,
        "min_duration_seconds": 120,
    },
    "anomaly_z3": {
        "condition": "anomaly_detection",
        "anomaly_zscore_threshold": 3.0,
        "min_duration_seconds": 60,
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
    _row("any_down_quick"),
    _row("ssl_expiry"),
    _row("response_baseline_3x"),
]
_HTTP_STRICT = [
    _row("all_down_immediate"),
    _row("any_down_quick", min_duration_seconds=30),
    _row("ssl_expiry"),
    _row("response_time_above_2s"),
    _row("anomaly_z3"),
]
_HTTP_SILENT = [
    _row("any_down_patient"),
    _row("ssl_expiry"),
]


TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "http": [
        {"id": "standard", "rows": _HTTP_STANDARD},
        {"id": "strict", "rows": _HTTP_STRICT},
        {"id": "silent", "rows": _HTTP_SILENT},
    ],
    "tcp": [
        {"id": "standard", "rows": [_row("any_down_quick"), _row("response_time_above_2s")]},
        {"id": "strict", "rows": [_row("all_down_immediate"), _row("any_down_quick", min_duration_seconds=30)]},
        {"id": "silent", "rows": [_row("any_down_patient")]},
    ],
    "dns": [
        {"id": "standard", "rows": [_row("any_down_quick")]},
        {"id": "strict", "rows": [_row("all_down_immediate"), _row("any_down_quick", min_duration_seconds=30)]},
        {"id": "silent", "rows": [_row("any_down_patient")]},
    ],
    "keyword": [
        {"id": "standard", "rows": [_row("any_down_quick")]},
        {"id": "strict", "rows": [_row("all_down_immediate"), _row("any_down_quick", min_duration_seconds=30)]},
        {"id": "silent", "rows": [_row("any_down_patient")]},
    ],
    "json_path": [
        {"id": "standard", "rows": [_row("any_down_quick"), _row("schema_drift")]},
        {"id": "strict", "rows": [_row("all_down_immediate"), _row("any_down_quick", min_duration_seconds=30), _row("schema_drift")]},
        {"id": "silent", "rows": [_row("any_down_patient")]},
    ],
    "scenario": [
        {"id": "standard", "rows": [_row("any_down_quick"), _row("response_time_above_2s", threshold_value=10000)]},
        {"id": "strict", "rows": [_row("all_down_immediate"), _row("any_down_quick", min_duration_seconds=30), _row("response_time_above_2s", threshold_value=5000)]},
        {"id": "silent", "rows": [_row("any_down_patient")]},
    ],
    "heartbeat": [
        {"id": "standard", "rows": [_row("any_down_quick", min_duration_seconds=0)]},
        {"id": "strict", "rows": [_row("any_down_quick", min_duration_seconds=0, renotify_after_minutes=10)]},
        {"id": "silent", "rows": [_row("any_down_patient")]},
    ],
}


def get_templates(check_type: str) -> list[dict[str, Any]]:
    return TEMPLATES.get(check_type, TEMPLATES["http"])
