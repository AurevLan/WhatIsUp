"""Pure alert-condition predicates — single source of truth for matching.

R-1 (état des lieux 2026-07-21): ``fire_alerts`` (real dispatch,
``services/incident_alerts.py``) and ``simulate_rule`` (UI preview,
``services/alert.py``) each reimplemented condition matching and silently
diverged — the preview knew 4 of the value-based conditions the dispatch
handles. Every value-based decision now goes through one pure predicate
defined here; callers keep their own data acquisition (DB queries, event-type
gating) and pass plain values in.

``any_down`` / ``all_down`` are incident-scope decisions, not value
comparisons — they stay with their callers.
"""

from __future__ import annotations

DEFAULT_ANOMALY_ZSCORE = 3.0


def ssl_expiry_matches(
    ssl_valid: bool | None,
    ssl_days_remaining: int | None,
    warn_days: int | None,
) -> bool:
    """Cert invalid, or expiring within the monitor's warn window."""
    if ssl_valid is False:
        return True
    return (
        ssl_days_remaining is not None and warn_days is not None and ssl_days_remaining <= warn_days
    )


def response_time_above_matches(response_time_ms: float | None, threshold: float | None) -> bool:
    """Latency strictly above a fixed threshold; unset threshold never fires."""
    return threshold is not None and response_time_ms is not None and response_time_ms > threshold


def above_baseline_matches(
    response_time_ms: float | None,
    baseline_avg: float | None,
    factor: float | None,
) -> bool:
    """Latency strictly above ``factor ×`` the rolling average.

    No baseline (no history, avg ≤ 0) or unset factor never fires.
    """
    if factor is None or response_time_ms is None:
        return False
    if not baseline_avg or baseline_avg <= 0:
        return False
    return response_time_ms > baseline_avg * factor


def anomaly_matches(zscore: float | None, threshold: float | None) -> bool:
    """Z-score strictly above threshold (default 3.0); no z-score never fires."""
    return zscore is not None and zscore > (threshold or DEFAULT_ANOMALY_ZSCORE)


def schema_drift_matches(fingerprint: str | None, baseline: str | None) -> bool:
    """Response schema fingerprint differs from the recorded baseline.

    Missing fingerprint or missing baseline never fires.
    """
    return bool(fingerprint) and bool(baseline) and fingerprint != baseline
