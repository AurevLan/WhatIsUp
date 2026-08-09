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

#: Freshness window applied to pushed-metric conditions when the rule leaves it
#: unset. Five minutes matches the default scrape/push cadence of every agent
#: this is likely to face; a rule pushing less often must widen it explicitly,
#: which is why the UI surfaces the field rather than hiding this default.
DEFAULT_METRIC_WINDOW_SECONDS = 300


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


# ── Pushed metrics (plan V2, C-4) ─────────────────────────────────────────────
#
# ``latest_value`` below is always "the most recent sample inside the rule's
# freshness window", never simply "the most recent sample". The distinction is
# the whole safety property of these three predicates: a value from an agent
# that died an hour ago must not keep paging (above/below), and must instead be
# what fires ``metric_absent``. The caller resolves the window; these functions
# only decide.


def metric_above_matches(latest_value: float | None, threshold: float | None) -> bool:
    """Fresh sample strictly above the threshold.

    No fresh sample, or an unset threshold, never fires — a missing agent is
    ``metric_absent``'s job, not this one's.
    """
    return threshold is not None and latest_value is not None and latest_value > threshold


def metric_below_matches(latest_value: float | None, threshold: float | None) -> bool:
    """Fresh sample strictly below the threshold.

    Symmetric with ``metric_above_matches``, including the "no data never
    fires" rule: silence must not look like a cache hit rate of zero.
    """
    return threshold is not None and latest_value is not None and latest_value < threshold


def metric_absent_matches(latest_value: float | None, has_ever_been_pushed: bool) -> bool:
    """No sample inside the freshness window, for a metric that has existed.

    ``has_ever_been_pushed`` is what keeps a typo in ``metric_name`` from
    paging forever: a series nobody ever wrote is not a series that stopped.
    """
    return has_ever_been_pushed and latest_value is None
