"""What the application's own metrics did around an incident (plan V2, C-3).

The blackbox checks say *that* something broke. The metrics the tenant pushes
say *what else was happening at the time* — queue depth climbing, cache hit rate
collapsing, worker count dropping. This module puts the two side by side.

How the comparison is made
──────────────────────────
For each series the monitor reports, the mean over the incident window is
compared with the mean over a baseline window of the **same length ending where
the incident starts**. Same length, immediately before: a series with a daily
shape is then compared against itself an hour ago rather than against an average
that flattens the shape away.

Ranked by relative change, largest first, so the answer opens with the series
that moved most.

What this deliberately does not claim
─────────────────────────────────────
**Correlation, never causation.** The output says a series *moved*; it does not
say it caused anything, and the wording all the way to the UI keeps that
distinction. A deploy that both slowed the service and drained a queue produces
a strong correlation with no causal link in either direction.

Where it refuses to answer
──────────────────────────
Three cases produce an explicit "not comparable" rather than a number, because
each of them is a way of manufacturing a figure out of nothing:

* **no baseline samples** — a series that started reporting *with* the incident
  has no "before" to compare to. Showing +∞, or 100%, would be an invention.
* **too few samples on either side** — two points against three is not a trend,
  and a ratio computed from them is noise with a decimal point.
* **a baseline mean of zero** — the relative change is undefined. Reported as an
  absolute delta instead, which is the honest form of the same observation.

Scope is one monitor's own series. Not a design shortcut: metrics are pushed
per monitor, so this can never reach across tenants.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.custom_metric import CustomMetric, MetricSeries
from whatisup.models.incident import Incident

logger = structlog.get_logger(__name__)

#: Shortest window either side of the comparison. An incident that lasted forty
#: seconds would otherwise be compared against forty seconds of baseline, which
#: for a metric pushed once a minute means zero samples against zero samples.
MIN_WINDOW = timedelta(minutes=5)

#: Longest window considered. A three-day incident does not need three days of
#: baseline to show what moved, and the query would walk the whole retention.
MAX_WINDOW = timedelta(hours=6)

#: Below this on either side, a ratio is noise with a decimal point.
MIN_SAMPLES = 3


@dataclass(frozen=True)
class SeriesMovement:
    """How one series behaved during the incident, next to its own baseline."""

    metric_name: str
    labels: dict[str, str]
    unit: str | None
    incident_avg: float | None
    incident_samples: int
    baseline_avg: float | None
    baseline_samples: int
    #: Relative change, e.g. ``0.42`` for +42%. None when not comparable.
    change_ratio: float | None
    #: Absolute change. Always available when both sides have samples — it is
    #: what gets reported when the baseline mean is zero and a ratio cannot be.
    change_absolute: float | None
    #: Machine-readable reason the comparison could not be made, if it could not.
    #: One of: no_baseline | no_incident_data | too_few_samples | zero_baseline
    not_comparable: str | None

    @property
    def magnitude(self) -> float:
        """Sort key. Not comparable sorts last, never in the middle."""
        if self.change_ratio is not None:
            return abs(self.change_ratio)
        return -1.0


def _window_for(incident: Incident, now: datetime) -> tuple[datetime, datetime]:
    """The incident window, clamped to something a comparison can chew on."""
    started = incident.started_at
    if started.tzinfo is None:  # SQLite hands back naive datetimes
        started = started.replace(tzinfo=UTC)
    ended = incident.resolved_at or now
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=UTC)

    length = ended - started
    if length < MIN_WINDOW:
        ended = started + MIN_WINDOW
    elif length > MAX_WINDOW:
        # Keep the head of the incident rather than the tail: what a series did
        # as things broke is more informative than what it did once the
        # operators were already on it.
        ended = started + MAX_WINDOW
    return started, min(ended, now)


async def _averages(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    start: datetime,
    end: datetime,
    *,
    end_exclusive: bool = False,
) -> dict[str, tuple[float, int]]:
    """Mean and sample count per series over ``[start, end]``.

    ``end_exclusive`` is what keeps the two windows from overlapping: the
    baseline runs up to — but not including — the instant the incident starts,
    because a sample taken exactly then belongs to the incident. Counting it on
    both sides pulls the baseline towards the incident and shrinks every change
    it is supposed to reveal.

    One grouped query rather than one per series: a monitor may legitimately
    report hundreds of them (bounded by the C-1 cardinality cap), and this runs
    on an interactive request.
    """
    upper = CustomMetric.pushed_at < end if end_exclusive else CustomMetric.pushed_at <= end
    rows = (
        await db.execute(
            select(
                CustomMetric.series_hash,
                func.avg(CustomMetric.value).label("avg_val"),
                func.count(CustomMetric.id).label("n"),
            )
            .where(
                CustomMetric.monitor_id == monitor_id,
                CustomMetric.pushed_at >= start,
                upper,
            )
            .group_by(CustomMetric.series_hash)
        )
    ).all()
    return {r.series_hash: (float(r.avg_val), int(r.n)) for r in rows}


def _compare(
    series: MetricSeries,
    incident: tuple[float, int] | None,
    baseline: tuple[float, int] | None,
) -> SeriesMovement:
    inc_avg, inc_n = incident or (None, 0)
    base_avg, base_n = baseline or (None, 0)

    common = {
        "metric_name": series.metric_name,
        "labels": series.labels or {},
        "unit": series.unit,
        "incident_avg": inc_avg,
        "incident_samples": inc_n,
        "baseline_avg": base_avg,
        "baseline_samples": base_n,
    }

    if inc_n == 0:
        return SeriesMovement(
            **common, change_ratio=None, change_absolute=None, not_comparable="no_incident_data"
        )
    if base_n == 0:
        # Started reporting with the incident: there is no "before".
        return SeriesMovement(
            **common, change_ratio=None, change_absolute=None, not_comparable="no_baseline"
        )
    if inc_n < MIN_SAMPLES or base_n < MIN_SAMPLES:
        return SeriesMovement(
            **common, change_ratio=None, change_absolute=None, not_comparable="too_few_samples"
        )

    delta = inc_avg - base_avg
    if base_avg == 0:
        # A ratio against zero is undefined, not infinite. The absolute delta
        # says the same thing without pretending.
        return SeriesMovement(
            **common, change_ratio=None, change_absolute=delta, not_comparable="zero_baseline"
        )
    return SeriesMovement(
        **common,
        change_ratio=delta / abs(base_avg),
        change_absolute=delta,
        not_comparable=None,
    )


async def correlate_incident_metrics(
    db: AsyncSession,
    incident: Incident,
    *,
    now: datetime | None = None,
) -> dict:
    """Rank this monitor's metric series by how much they moved.

    Computed on demand rather than snapshotted when the incident opened: at T+0
    there is nothing to correlate yet, and unlike a traceroute the samples are
    still in the table afterwards. The post-mortem is what freezes the verdict,
    because that document is meant to outlive ``METRICS_RETENTION_DAYS``.
    """
    now = now or datetime.now(UTC)
    start, end = _window_for(incident, now)
    window_seconds = int((end - start).total_seconds())
    baseline_start = start - (end - start)

    series = list(
        (
            await db.execute(
                select(MetricSeries).where(MetricSeries.monitor_id == incident.monitor_id)
            )
        )
        .scalars()
        .all()
    )
    if not series:
        return {
            "incident_id": incident.id,
            "window_start": start,
            "window_end": end,
            "baseline_start": baseline_start,
            "window_seconds": window_seconds,
            "series": [],
        }

    during = await _averages(db, incident.monitor_id, start, end)
    before = await _averages(db, incident.monitor_id, baseline_start, start, end_exclusive=True)

    movements = [_compare(s, during.get(s.series_hash), before.get(s.series_hash)) for s in series]
    # Series with nothing at all on either side are noise in the answer, not
    # information: they were simply not reporting during this period.
    movements = [m for m in movements if m.incident_samples or m.baseline_samples]
    movements.sort(key=lambda m: m.magnitude, reverse=True)

    return {
        "incident_id": incident.id,
        "window_start": start,
        "window_end": end,
        "baseline_start": baseline_start,
        "window_seconds": window_seconds,
        "series": movements,
    }


def format_markdown(correlation: dict, *, limit: int = 8) -> str:
    """The correlation as a post-mortem section.

    Rendered at generation time so the document keeps the finding once the
    samples themselves have aged out of ``METRICS_RETENTION_DAYS``.
    """
    movements = correlation["series"][:limit]
    if not movements:
        return "_No application metrics were being pushed for this monitor during the incident._"

    lines = [
        "| Metric | During | Baseline | Change |",
        "|--------|--------|----------|--------|",
    ]
    for m in movements:
        label = m.metric_name + _format_labels(m.labels)
        unit = f" {m.unit}" if m.unit else ""
        during = f"{m.incident_avg:g}{unit}" if m.incident_avg is not None else "—"
        base = f"{m.baseline_avg:g}{unit}" if m.baseline_avg is not None else "—"
        if m.change_ratio is not None:
            change = f"{m.change_ratio:+.0%}"
        elif m.not_comparable == "zero_baseline" and m.change_absolute is not None:
            change = f"{m.change_absolute:+g}{unit}"
        else:
            change = _NOT_COMPARABLE_LABEL.get(m.not_comparable, "not comparable")
        lines.append(f"| `{label}` | {during} | {base} | {change} |")

    lines.append("")
    lines.append(
        "_Series are ranked by how much they moved against the equivalent window "
        "immediately before the incident. This shows correlation, not causation._"
    )
    return "\n".join(lines)


_NOT_COMPARABLE_LABEL = {
    "no_baseline": "no baseline",
    "no_incident_data": "no data during",
    "too_few_samples": "too few samples",
    "zero_baseline": "baseline was zero",
}


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + inner + "}"
