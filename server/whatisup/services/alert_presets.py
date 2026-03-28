"""Smart alert presets by check_type — generates sensible default rules."""

from __future__ import annotations

from whatisup.models.alert import AlertCondition

# Preset definitions: for each check_type, a list of recommended alert rules
# with their condition and default parameters.
ALERT_PRESETS: dict[str, list[dict]] = {
    "http": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when down",
            "min_duration_seconds": 0,
            "default": True,
        },
        {
            "condition": AlertCondition.ssl_expiry,
            "label": "SSL certificate expiry",
            "min_duration_seconds": 0,
            "default": True,
        },
        {
            "condition": AlertCondition.response_time_above,
            "label": "Slow response time",
            "threshold_value": 5000,
            "min_duration_seconds": 0,
            "default": False,
        },
    ],
    "keyword": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when down / keyword mismatch",
            "min_duration_seconds": 0,
            "default": True,
        },
        {
            "condition": AlertCondition.ssl_expiry,
            "label": "SSL certificate expiry",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "json_path": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when down / value mismatch",
            "min_duration_seconds": 0,
            "default": True,
        },
        {
            "condition": AlertCondition.schema_drift,
            "label": "API schema changed",
            "min_duration_seconds": 0,
            "default": False,
        },
    ],
    "tcp": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when unreachable",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "udp": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when unreachable",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "dns": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when resolution fails",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "smtp": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when unreachable",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "ping": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when unreachable",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "scenario": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when scenario fails",
            "min_duration_seconds": 0,
            "default": True,
        },
        {
            "condition": AlertCondition.response_time_above,
            "label": "Slow scenario execution",
            "threshold_value": 30000,
            "min_duration_seconds": 0,
            "default": False,
        },
    ],
    "heartbeat": [
        {
            "condition": AlertCondition.any_down,
            "label": "Heartbeat missed",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "domain_expiry": [
        {
            "condition": AlertCondition.any_down,
            "label": "Domain expiration warning",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "composite": [
        {
            "condition": AlertCondition.any_down,
            "label": "Alert when composite status is down",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
}


def get_presets(check_type: str) -> list[dict]:
    """Return recommended alert presets for a given check type."""
    return ALERT_PRESETS.get(check_type, ALERT_PRESETS["http"])
