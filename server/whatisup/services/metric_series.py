"""Resolving a label selector to the series it designates (plan V2, C-1).

Before labels, ``AlertRule.metric_name`` *was* the series. Now a name is a
family, so everything that used to say "the series called X" has to say "the
series called X matching this selector" — the alert evaluator, the rule preview
and the read API alike, which is why this lives on its own rather than inside
any one of them.

What a rule without a selector watches
──────────────────────────────────────
Every series of that name, firing when **any** of them matches. Two candidate
rules were possible and the choice is not neutral:

- *Only the label-less series.* Existing C-4 rules would keep watching exactly
  what they watched — until the day the application starts labelling that
  metric, at which point the rule silently stops matching anything and the
  alert goes quiet forever. A monitoring system that goes quiet because the data
  got richer is the worst outcome available.
- *Any series of that name.* Adding labels can make an existing rule noisier,
  never silent. Noise is visible and fixable; silence is neither.

So: any. The same "any" applies to ``metric_absent`` — one dead shard is worth
paging about even while its siblings still report.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import dialect_name
from whatisup.models.custom_metric import MetricSeries


def labels_match(series_labels: dict | None, selector: dict | None) -> bool:
    """Subset match: every selector pair must be present on the series.

    ``{"route": "/api"}`` selects ``{"route": "/api", "method": "GET"}``. An
    empty or absent selector matches everything — see the module docstring.
    """
    if not selector:
        return True
    labels = series_labels or {}
    return all(str(labels.get(k)) == str(v) for k, v in selector.items())


async def resolve_series(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    metric_name: str,
    selector: dict | None = None,
) -> list[MetricSeries]:
    """Series of ``metric_name`` on this monitor that satisfy ``selector``.

    PostgreSQL filters with JSONB containment so the GIN index does the work;
    SQLite has no containment operator, so the tests' backend filters in Python
    over the monitor's series — a set bounded by the cardinality cap, not by
    time, so this stays cheap even as a fallback.
    """
    stmt = select(MetricSeries).where(
        MetricSeries.monitor_id == monitor_id,
        MetricSeries.metric_name == metric_name,
    )
    if selector and dialect_name(db) == "postgresql":
        stmt = stmt.where(MetricSeries.labels.op("@>")(selector))

    rows = list((await db.execute(stmt)).scalars().all())
    if selector and dialect_name(db) != "postgresql":
        rows = [r for r in rows if labels_match(r.labels, selector)]
    return rows


async def resolve_series_hashes(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    metric_name: str,
    selector: dict | None = None,
) -> list[str]:
    """Just the hashes — what the point queries actually filter on."""
    return [s.series_hash for s in await resolve_series(db, monitor_id, metric_name, selector)]
