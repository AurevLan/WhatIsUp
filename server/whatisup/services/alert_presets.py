"""Smart alert presets by check_type — generates sensible default rules."""

from __future__ import annotations

from whatisup.models.alert import AlertCondition

# Preset definitions: for each check_type, a list of recommended alert rules
# with their condition and default parameters.
ALERT_PRESETS: dict[str, list[dict]] = {
    "http": [
        {
            "condition": AlertCondition.availability,
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
            "condition": AlertCondition.latency_anomaly,
            "label": "Slow response time",
            "threshold_value": 5000,
            "min_duration_seconds": 0,
            "default": False,
        },
    ],
    "tcp": [
        {
            "condition": AlertCondition.availability,
            "label": "Alert when unreachable",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "dns": [
        {
            "condition": AlertCondition.availability,
            "label": "Alert when resolution fails",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "smtp": [
        {
            "condition": AlertCondition.availability,
            "label": "Alert when unreachable",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "ping": [
        {
            "condition": AlertCondition.availability,
            "label": "Alert when unreachable",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "scenario": [
        {
            "condition": AlertCondition.availability,
            "label": "Alert when scenario fails",
            "min_duration_seconds": 0,
            "default": True,
        },
        {
            "condition": AlertCondition.latency_anomaly,
            "label": "Slow scenario execution",
            "threshold_value": 30000,
            "min_duration_seconds": 0,
            "default": False,
        },
    ],
    "heartbeat": [
        {
            "condition": AlertCondition.availability,
            "label": "Heartbeat missed",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
    "domain_expiry": [
        {
            "condition": AlertCondition.availability,
            "label": "Domain expiration warning",
            "min_duration_seconds": 0,
            "default": True,
        },
    ],
}


def get_presets(check_type: str) -> list[dict]:
    """Return recommended alert presets for a given check type."""
    return ALERT_PRESETS.get(check_type, ALERT_PRESETS["http"])
